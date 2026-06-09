"""
Document Extraction Agent — Stage 2 of the pipeline.

Extracts structured information from each document. Supports two modes:
  - Structured mode: document has a pre-populated `content` dict (used in test cases
    and when a prior system has already parsed the document).
  - Vision mode: document has `raw_bytes` (image/PDF) — calls Claude via the
    Anthropic API to extract fields using its vision capability.

The agent never fails the entire pipeline — extraction errors are captured in
`extraction_errors` and reflected in `extraction_confidence`.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from typing import Any, Dict, List, Optional

from core.models import (
    ClaimSubmission,
    Document,
    DocumentType,
    ExtractedDocument,
    ExtractedField,
)
from core.trace import TraceBuilder

logger = logging.getLogger(__name__)
COMPONENT = "document_extractor"

_EXTRACTION_PROMPT = """
You are extracting structured information from an Indian medical document.
Return ONLY valid JSON with these fields (use null for missing fields):

{
  "document_type": "<PRESCRIPTION|HOSPITAL_BILL|LAB_REPORT|PHARMACY_BILL|DENTAL_REPORT|DISCHARGE_SUMMARY|UNKNOWN>",
  "patient_name": "<string|null>",
  "doctor_name": "<string|null>",
  "doctor_registration": "<string|null>",
  "date": "<YYYY-MM-DD|null>",
  "diagnosis": "<string|null>",
  "treatment": "<string|null>",
  "medicines": ["<medicine name>"],
  "tests_ordered": ["<test name>"],
  "line_items": [{"description": "<str>", "amount": <number>}],
  "total_amount": <number|null>,
  "hospital_name": "<string|null>",
  "confidence": <0.0-1.0>
}

Document:
"""


class DocumentExtractorAgent:
    """
    Async extractor. Processes all documents for a claim in parallel.
    Falls back gracefully when the LLM is unavailable.
    """

    def __init__(self) -> None:
        self._client = _get_anthropic_client()

    async def extract_all(
        self,
        submission: ClaimSubmission,
        trace: TraceBuilder,
    ) -> List[ExtractedDocument]:
        """Process all documents concurrently, returning one ExtractedDocument per input."""
        tasks = [
            self._extract_one(doc, trace)
            for doc in submission.documents
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        extracted: List[ExtractedDocument] = []
        for doc, result in zip(submission.documents, results):
            if isinstance(result, Exception):
                trace.error(COMPONENT, "extract_one",
                            f"Extraction failed for {doc.file_id}: {result!s}",
                            {"file_id": doc.file_id})
                extracted.append(_make_degraded(doc, str(result)))
            else:
                extracted.append(result)  # type: ignore[arg-type]

        return extracted

    async def _extract_one(self, doc: Document, trace: TraceBuilder) -> ExtractedDocument:
        # --- Structured path: content already provided (test fixtures) ---
        if doc.content:
            result = _from_structured_content(doc)
            trace.passed(COMPONENT, "extract_one",
                         f"Extracted from structured content — {doc.file_id}",
                         {"type": result.document_type.value, "confidence": result.extraction_confidence})
            return result

        # --- Vision path: call Anthropic API ---
        if doc.raw_bytes:
            if not self._client:
                trace.warn(COMPONENT, "extract_one",
                           f"No Anthropic API key — skipping vision extraction for {doc.file_id}")
                result = _make_degraded(doc, "ANTHROPIC_API_KEY not configured")
                result.document_type = doc.actual_type or DocumentType.UNKNOWN
                return result

            result = await self._call_vision_api(doc, trace)
            return result

        # --- Fallback: use actual_type if provided, return minimal extraction ---
        trace.warn(COMPONENT, "extract_one",
                   f"No content or raw_bytes for {doc.file_id} — using metadata only")
        return ExtractedDocument(
            file_id=doc.file_id,
            document_type=doc.actual_type or DocumentType.UNKNOWN,
            extraction_confidence=0.3,
            extraction_errors=["No extractable content provided"],
            degraded=True,
        )

    async def _call_vision_api(self, doc: Document, trace: TraceBuilder) -> ExtractedDocument:
        """Call Claude claude-sonnet-4-6 with the document image and parse the response."""
        try:
            encoded = base64.b64encode(doc.raw_bytes).decode()  # type: ignore[arg-type]
            mime_type = "image/jpeg" if not doc.file_name else _infer_mime(doc.file_name)

            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._client.messages.create(  # type: ignore[union-attr]
                    model="claude-haiku-4-5-20251001",
                    max_tokens=1024,
                    messages=[{
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {"type": "base64", "media_type": mime_type, "data": encoded},
                            },
                            {"type": "text", "text": _EXTRACTION_PROMPT},
                        ],
                    }],
                ),
            )

            raw = response.content[0].text.strip()
            # Claude sometimes wraps in ```json ... ```
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]

            data: Dict[str, Any] = json.loads(raw)
            result = _from_api_response(doc, data)
            trace.passed(COMPONENT, "vision_extraction",
                         f"Vision extraction complete for {doc.file_id}",
                         {"confidence": result.extraction_confidence})
            return result

        except json.JSONDecodeError as exc:
            trace.error(COMPONENT, "vision_extraction",
                        f"LLM returned non-JSON for {doc.file_id}: {exc!s}")
            return _make_degraded(doc, f"JSON parse error: {exc!s}")
        except Exception as exc:
            trace.error(COMPONENT, "vision_extraction",
                        f"API call failed for {doc.file_id}: {exc!s}")
            return _make_degraded(doc, str(exc))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _from_structured_content(doc: Document) -> ExtractedDocument:
    c = doc.content or {}
    doc_type = doc.actual_type or DocumentType.UNKNOWN

    line_items: List[Dict[str, Any]] = []
    raw_items = c.get("line_items", [])
    for item in raw_items:
        line_items.append({
            "description": item.get("description", ""),
            "amount": float(item.get("amount", 0)),
        })

    total = c.get("total") or c.get("total_amount")
    if total is None and line_items:
        total = sum(i["amount"] for i in line_items)

    medicines = c.get("medicines", [])
    tests_ordered = c.get("tests_ordered", [])

    # Infer tests from lab report content
    if doc_type == DocumentType.LAB_REPORT:
        test_name = c.get("test_name")
        if test_name and test_name not in tests_ordered:
            tests_ordered = [test_name] + tests_ordered

    diagnosis_val = c.get("diagnosis") or c.get("diagnosis_text")
    treatment_val = c.get("treatment") or c.get("procedure")

    return ExtractedDocument(
        file_id=doc.file_id,
        document_type=doc_type,
        patient_name=_field(c.get("patient_name")),
        doctor_name=_field(c.get("doctor_name")),
        doctor_registration=_field(c.get("doctor_registration")),
        date=_field(c.get("date")),
        diagnosis=_field(diagnosis_val),
        treatment=_field(treatment_val),
        medicines=medicines if isinstance(medicines, list) else [],
        tests_ordered=tests_ordered if isinstance(tests_ordered, list) else [],
        line_items=line_items,
        total_amount=float(total) if total is not None else None,
        hospital_name=_field(c.get("hospital_name")),
        extraction_confidence=1.0,
    )


def _from_api_response(doc: Document, data: Dict[str, Any]) -> ExtractedDocument:
    raw_type = data.get("document_type", "UNKNOWN").upper()
    try:
        doc_type = DocumentType(raw_type)
    except ValueError:
        doc_type = doc.actual_type or DocumentType.UNKNOWN

    items = data.get("line_items", []) or []
    line_items = [{"description": str(i.get("description", "")), "amount": float(i.get("amount", 0))} for i in items]

    return ExtractedDocument(
        file_id=doc.file_id,
        document_type=doc_type,
        patient_name=_field(data.get("patient_name")),
        doctor_name=_field(data.get("doctor_name")),
        doctor_registration=_field(data.get("doctor_registration")),
        date=_field(data.get("date")),
        diagnosis=_field(data.get("diagnosis")),
        treatment=_field(data.get("treatment")),
        medicines=data.get("medicines") or [],
        tests_ordered=data.get("tests_ordered") or [],
        line_items=line_items,
        total_amount=data.get("total_amount"),
        hospital_name=_field(data.get("hospital_name")),
        extraction_confidence=float(data.get("confidence", 0.8)),
    )


def _make_degraded(doc: Document, error: str) -> ExtractedDocument:
    return ExtractedDocument(
        file_id=doc.file_id,
        document_type=doc.actual_type or DocumentType.UNKNOWN,
        extraction_confidence=0.0,
        extraction_errors=[error],
        degraded=True,
    )


def _field(value: Any) -> Optional[ExtractedField]:
    if value is None:
        return None
    return ExtractedField(value=value)


def _infer_mime(filename: str) -> str:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "pdf": "application/pdf", "webp": "image/webp"}.get(ext, "image/jpeg")


def _get_anthropic_client() -> Any:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set — vision extraction will be skipped")
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        logger.warning("anthropic package not installed — vision extraction unavailable")
        return None
