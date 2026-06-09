"""
Document Validation Gate — Stage 1 of the pipeline.

This agent runs synchronously BEFORE any processing and stops the pipeline
on hard failures. It is fast and has no LLM dependency.

Checks (in order):
  1. Required document types are present for the claim category
  2. No documents are unreadable (quality=UNREADABLE)
  3. Patient names across documents are consistent (if extractable)
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

from core.models import (
    ClaimCategory,
    ClaimSubmission,
    Document,
    DocumentType,
    DocumentQuality,
    ValidationIssue,
    ValidationResult,
)
from core.trace import TraceBuilder

COMPONENT = "document_validator"


class DocumentValidatorAgent:
    """
    Stateless validator. All methods are class-level so there's no shared mutable state
    between claims.
    """

    def __init__(self, policy_document_requirements: Dict[str, Dict[str, List[str]]]) -> None:
        self._requirements = policy_document_requirements

    def validate(self, submission: ClaimSubmission, trace: TraceBuilder) -> ValidationResult:
        issues: List[ValidationIssue] = []

        trace.info(COMPONENT, "start",
                   f"Validating {len(submission.documents)} document(s) for "
                   f"{submission.claim_category.value} claim")

        # --- Check 1: Required document types ---
        self._check_required_types(submission, issues, trace)

        # --- Check 2: Document quality ---
        self._check_document_quality(submission, issues, trace)

        # --- Check 3: Cross-document patient identity ---
        self._check_patient_identity_consistency(submission, issues, trace)

        passed = len(issues) == 0
        if passed:
            trace.passed(COMPONENT, "validation_complete",
                         "All document checks passed — proceeding to extraction")
        else:
            blocking = [i for i in issues if i.severity in ("BLOCKING", "SOFT_BLOCK")]
            trace.failed(COMPONENT, "validation_complete",
                         f"{len(blocking)} blocking issue(s) found — pipeline halted",
                         {"issues": [i.code for i in issues]})

        return ValidationResult(passed=passed, issues=issues, trace=trace.entries())

    # ------------------------------------------------------------------
    # Check implementations
    # ------------------------------------------------------------------

    def _check_required_types(
        self,
        submission: ClaimSubmission,
        issues: List[ValidationIssue],
        trace: TraceBuilder,
    ) -> None:
        cat = submission.claim_category.value
        requirements = self._requirements.get(cat, {})
        required_types: List[str] = requirements.get("required", [])

        submitted_types: Dict[str, List[str]] = {}
        for doc in submission.documents:
            doc_type = (doc.actual_type or DocumentType.UNKNOWN).value
            submitted_types.setdefault(doc_type, []).append(doc.file_name or doc.file_id)

        missing: List[str] = []
        extra_instead: List[str] = []

        for req_type in required_types:
            if req_type not in submitted_types:
                missing.append(req_type)
                trace.failed(COMPONENT, "required_type_check",
                             f"Missing required document type: {req_type} for {cat} claim",
                             {"required": req_type, "submitted_types": list(submitted_types.keys())})
            else:
                trace.passed(COMPONENT, "required_type_check",
                             f"Required document {req_type} is present")

        if missing:
            submitted_display = ", ".join(
                f"{k} (×{len(v)})" for k, v in submitted_types.items()
            ) or "none"
            missing_display = ", ".join(missing)

            issues.append(ValidationIssue(
                code="MISSING_REQUIRED_DOCUMENTS",
                severity="BLOCKING",
                message=(
                    f"For a {cat} claim, the following required document(s) are missing: "
                    f"{missing_display}. "
                    f"You submitted: {submitted_display}. "
                    f"Please upload the missing document(s) and resubmit."
                ),
                documents_involved=list(submitted_types.keys()),
            ))

    def _check_document_quality(
        self,
        submission: ClaimSubmission,
        issues: List[ValidationIssue],
        trace: TraceBuilder,
    ) -> None:
        for doc in submission.documents:
            if doc.quality == DocumentQuality.UNREADABLE:
                doc_type = (doc.actual_type or DocumentType.UNKNOWN).value
                file_label = doc.file_name or doc.file_id
                trace.failed(COMPONENT, "quality_check",
                             f"Document '{file_label}' ({doc_type}) is unreadable",
                             {"file_id": doc.file_id, "type": doc_type})
                issues.append(ValidationIssue(
                    code="UNREADABLE_DOCUMENT",
                    severity="SOFT_BLOCK",
                    message=(
                        f"The {doc_type.replace('_', ' ').lower()} you uploaded "
                        f"('{file_label}') is too blurry or low-quality to read. "
                        f"Please re-upload a clear, well-lit photo or scan of the "
                        f"{doc_type.replace('_', ' ').lower()} and resubmit."
                    ),
                    documents_involved=[doc.file_id],
                ))
            else:
                trace.passed(COMPONENT, "quality_check",
                             f"Document {doc.file_name or doc.file_id} quality is acceptable")

    def _check_patient_identity_consistency(
        self,
        submission: ClaimSubmission,
        issues: List[ValidationIssue],
        trace: TraceBuilder,
    ) -> None:
        """
        If patient names are available on documents (either from patient_name_on_doc
        or from the pre-structured content), check that they are consistent.
        """
        name_by_doc: Dict[str, str] = {}

        for doc in submission.documents:
            name: Optional[str] = doc.patient_name_on_doc

            # also check structured content
            if name is None and doc.content:
                name = doc.content.get("patient_name")

            if name:
                doc_type = (doc.actual_type or DocumentType.UNKNOWN).value
                normalized = _normalize_name(name)
                name_by_doc[doc_type] = name  # keep original for display

        if len(name_by_doc) < 2:
            # not enough named docs to cross-check
            trace.info(COMPONENT, "identity_check",
                       "Not enough patient names on documents to cross-check identity")
            return

        unique_normalized = {_normalize_name(n) for n in name_by_doc.values()}

        if len(unique_normalized) > 1:
            names_detail = "; ".join(
                f"{doc_type}: '{name}'" for doc_type, name in name_by_doc.items()
            )
            trace.failed(COMPONENT, "identity_check",
                         f"Patient name mismatch: {names_detail}")
            issues.append(ValidationIssue(
                code="PATIENT_NAME_MISMATCH",
                severity="BLOCKING",
                message=(
                    f"The patient names on your documents do not match. {names_detail}. "
                    f"All documents in a single claim must belong to the same patient. "
                    f"Please verify you have uploaded the correct documents and resubmit."
                ),
                documents_involved=list(name_by_doc.keys()),
            ))
        else:
            trace.passed(COMPONENT, "identity_check",
                         f"Patient name consistent across {len(name_by_doc)} document(s)",
                         {"name": next(iter(name_by_doc.values()))})


def _normalize_name(name: str) -> str:
    """Case-fold and strip extra whitespace for fuzzy name comparison."""
    return re.sub(r"\s+", " ", name.strip().lower())
