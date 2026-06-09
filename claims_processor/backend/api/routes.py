"""
FastAPI route definitions for the claims processing API.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse

from core.models import ClaimResult, ClaimSubmission
from core.pipeline import ClaimsPipeline

logger = logging.getLogger(__name__)


router = APIRouter()

# In-memory store — replace with a database in production
_claims_store: Dict[str, Dict[str, Any]] = {}
_pipeline: ClaimsPipeline | None = None


def init_pipeline(policy_path: Path) -> None:
    global _pipeline
    _pipeline = ClaimsPipeline(policy_path)
    logger.info("Pipeline initialized with policy: %s", policy_path)


def _get_pipeline() -> ClaimsPipeline:
    if _pipeline is None:
        raise RuntimeError("Pipeline not initialized")
    return _pipeline


# ---------------------------------------------------------------------------
# Claims endpoints
# ---------------------------------------------------------------------------

@router.post("/claims", response_model=None, status_code=201)
async def submit_claim(submission: ClaimSubmission) -> JSONResponse:
    """
    Submit a new health insurance claim for processing.
    Returns either a ValidationFailedResult or ClaimDecisionResult.
    """
    pipeline = _get_pipeline()
    result = await pipeline.process(submission)

    # Persist result
    _claims_store[submission.claim_id] = result.model_dump(mode="json")

    return JSONResponse(
        content=result.model_dump(mode="json"),
        status_code=201,
    )


@router.get("/claims", response_model=None)
async def list_claims() -> JSONResponse:
    """List all processed claims (summary view)."""
    summaries = []
    for claim_id, data in _claims_store.items():
        summaries.append({
            "claim_id": claim_id,
            "status": data.get("status"),
            "decision": data.get("decision"),
            "approved_amount": data.get("approved_amount"),
            "claimed_amount": data.get("claimed_amount"),
            "confidence_score": data.get("confidence_score"),
            "processing_time_ms": data.get("processing_time_ms"),
        })
    return JSONResponse(content=summaries)


@router.get("/claims/{claim_id}", response_model=None)
async def get_claim(claim_id: str) -> JSONResponse:
    """Retrieve the full result for a processed claim."""
    if claim_id not in _claims_store:
        raise HTTPException(status_code=404, detail=f"Claim '{claim_id}' not found")
    return JSONResponse(content=_claims_store[claim_id])


# ---------------------------------------------------------------------------
# Test-case runner endpoints
# ---------------------------------------------------------------------------

@router.get("/test-cases", response_model=None)
async def list_test_cases() -> JSONResponse:
    """Return all 12 test cases from test_cases.json."""
    tc_path = Path(__file__).parent.parent.parent.parent / "test_cases.json"
    if not tc_path.exists():
        raise HTTPException(status_code=404, detail="test_cases.json not found")
    with open(tc_path) as f:
        data = json.load(f)
    return JSONResponse(content=data)


@router.post("/test-cases/{case_id}/run", response_model=None)
async def run_test_case(case_id: str) -> JSONResponse:
    """
    Run a specific test case from test_cases.json through the full pipeline.
    Builds the ClaimSubmission from the test case input and processes it.
    """
    tc_path = Path(__file__).parent.parent.parent.parent / "test_cases.json"
    with open(tc_path) as f:
        all_cases = json.load(f)

    case = next(
        (c for c in all_cases.get("test_cases", []) if c["case_id"] == case_id),
        None,
    )
    if case is None:
        raise HTTPException(status_code=404, detail=f"Test case '{case_id}' not found")

    try:
        submission = _build_submission_from_test_case(case)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to build submission: {exc!s}")

    pipeline = _get_pipeline()
    result = await pipeline.process(submission)

    _claims_store[submission.claim_id] = result.model_dump(mode="json")

    return JSONResponse(
        content={
            "case_id": case_id,
            "case_name": case.get("case_name"),
            "expected": case.get("expected"),
            "result": result.model_dump(mode="json"),
        },
        status_code=200,
    )


@router.post("/test-cases/run-all", response_model=None)
async def run_all_test_cases() -> JSONResponse:
    """Run all 12 test cases and return a comparison report."""
    tc_path = Path(__file__).parent.parent.parent.parent / "test_cases.json"
    with open(tc_path) as f:
        all_cases = json.load(f)

    pipeline = _get_pipeline()
    report = []

    for case in all_cases.get("test_cases", []):
        try:
            submission = _build_submission_from_test_case(case)
            result = await pipeline.process(submission)
            _claims_store[submission.claim_id] = result.model_dump(mode="json")
            result_data = result.model_dump(mode="json")
        except Exception as exc:
            result_data = {"error": str(exc)}

        expected = case.get("expected", {})
        passed = _check_test_outcome(expected, result_data)

        report.append({
            "case_id": case["case_id"],
            "case_name": case.get("case_name"),
            "passed": passed,
            "expected": expected,
            "result": result_data,
        })

    total = len(report)
    passing = sum(1 for r in report if r["passed"])
    return JSONResponse(content={
        "summary": {"total": total, "passing": passing, "failing": total - passing},
        "cases": report,
    })


# ---------------------------------------------------------------------------
# Members / policy endpoints
# ---------------------------------------------------------------------------

@router.get("/members", response_model=None)
async def list_members() -> JSONResponse:
    pipeline = _get_pipeline()
    members = pipeline._policy_engine.get_members()
    return JSONResponse(content=members)


@router.get("/policy", response_model=None)
async def get_policy() -> JSONResponse:
    pipeline = _get_pipeline()
    return JSONResponse(content=pipeline._policy_engine._policy)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_submission_from_test_case(case: Dict[str, Any]) -> ClaimSubmission:
    from core.models import ClaimCategory, Document, DocumentQuality, DocumentType

    inp = case["input"]
    docs_raw = inp.get("documents", [])

    documents = []
    for d in docs_raw:
        actual_type_str = d.get("actual_type")
        actual_type = DocumentType(actual_type_str) if actual_type_str else None

        quality_str = d.get("quality", "GOOD")
        quality = DocumentQuality(quality_str)
        documents.append(Document(
            file_id=d.get("file_id", ""),
            file_name=d.get("file_name"),
            actual_type=actual_type,
            quality=quality,
            content=d.get("content"),
            patient_name_on_doc=d.get("patient_name_on_doc"),
        ))

    return ClaimSubmission(
        member_id=inp["member_id"],
        policy_id=inp["policy_id"],
        claim_category=ClaimCategory(inp["claim_category"]),
        treatment_date=inp["treatment_date"],
        claimed_amount=float(inp["claimed_amount"]),
        hospital_name=inp.get("hospital_name"),
        documents=documents,
        ytd_claims_amount=float(inp.get("ytd_claims_amount", 0)),
        claims_history=inp.get("claims_history", []),
        simulate_component_failure=inp.get("simulate_component_failure", False),
    )


def _check_test_outcome(expected: Dict[str, Any], result: Dict[str, Any]) -> bool:
    """
    Loosely verify a result against its expected outcome.
    Returns True if the main observable properties match.
    """
    expected_decision = expected.get("decision")
    if expected_decision is None:
        # Test expects pipeline to be blocked (validation failure)
        return result.get("status") == "VALIDATION_FAILED"

    actual_decision = result.get("decision")
    if actual_decision != expected_decision:
        return False
    # Check approved amount if specified
    expected_amount = expected.get("approved_amount")
    if expected_amount is not None:
        actual_amount = result.get("approved_amount", 0)
        if abs(float(actual_amount) - float(expected_amount)) > 1.0:
            return False

    return True
