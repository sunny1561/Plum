"""
Core data models for the claims processing pipeline.
All inter-agent contracts are expressed as Pydantic models for strict validation.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class DocumentType(str, Enum):
    PRESCRIPTION = "PRESCRIPTION"
    HOSPITAL_BILL = "HOSPITAL_BILL"
    LAB_REPORT = "LAB_REPORT"
    PHARMACY_BILL = "PHARMACY_BILL"
    DENTAL_REPORT = "DENTAL_REPORT"
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"
    DIAGNOSTIC_REPORT = "DIAGNOSTIC_REPORT"
    UNKNOWN = "UNKNOWN"


class ClaimCategory(str, Enum):
    CONSULTATION = "CONSULTATION"
    DIAGNOSTIC = "DIAGNOSTIC"
    PHARMACY = "PHARMACY"
    DENTAL = "DENTAL"
    VISION = "VISION"
    ALTERNATIVE_MEDICINE = "ALTERNATIVE_MEDICINE"


class DecisionType(str, Enum):
    APPROVED = "APPROVED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class DocumentQuality(str, Enum):
    GOOD = "GOOD"
    POOR = "POOR"
    UNREADABLE = "UNREADABLE"


class TraceStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    INFO = "INFO"
    ERROR = "ERROR"


class RejectionReason(str, Enum):
    WAITING_PERIOD = "WAITING_PERIOD"
    EXCLUDED_CONDITION = "EXCLUDED_CONDITION"
    PRE_AUTH_MISSING = "PRE_AUTH_MISSING"
    PER_CLAIM_EXCEEDED = "PER_CLAIM_EXCEEDED"
    ANNUAL_LIMIT_EXCEEDED = "ANNUAL_LIMIT_EXCEEDED"
    MEMBER_NOT_FOUND = "MEMBER_NOT_FOUND"
    POLICY_INACTIVE = "POLICY_INACTIVE"
    NOT_COVERED = "NOT_COVERED"
    SUBMISSION_DEADLINE_MISSED = "SUBMISSION_DEADLINE_MISSED"


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------

class Document(BaseModel):
    file_id: str
    file_name: Optional[str] = None
    actual_type: Optional[DocumentType] = None
    quality: DocumentQuality = DocumentQuality.GOOD
    content: Optional[Dict[str, Any]] = None
    raw_bytes: Optional[bytes] = None
    patient_name_on_doc: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True


class ClaimSubmission(BaseModel):
    claim_id: str = Field(default_factory=lambda: f"CLM_{uuid.uuid4().hex[:8].upper()}")
    member_id: str
    policy_id: str
    claim_category: ClaimCategory
    treatment_date: date
    claimed_amount: float
    hospital_name: Optional[str] = None
    documents: List[Document]
    ytd_claims_amount: float = 0.0
    claims_history: List[Dict[str, Any]] = Field(default_factory=list)
    simulate_component_failure: bool = False
    submitted_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("claimed_amount")
    @classmethod
    def amount_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("claimed_amount must be positive")
        return v

    @field_validator("documents")
    @classmethod
    def at_least_one_document(cls, v: List[Document]) -> List[Document]:
        if not v:
            raise ValueError("At least one document is required")
        return v


# ---------------------------------------------------------------------------
# Trace / Observability models
# ---------------------------------------------------------------------------

class TraceEntry(BaseModel):
    component: str
    step: str
    status: TraceStatus
    detail: str
    data: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Intermediate processing models
# ---------------------------------------------------------------------------

class ValidationIssue(BaseModel):
    code: str
    severity: Literal["BLOCKING", "SOFT_BLOCK", "WARNING"]
    message: str
    documents_involved: List[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    passed: bool
    issues: List[ValidationIssue] = Field(default_factory=list)
    trace: List[TraceEntry] = Field(default_factory=list)

    @property
    def has_blocking_issues(self) -> bool:
        return any(i.severity in ("BLOCKING", "SOFT_BLOCK") for i in self.issues)

    @property
    def blocking_messages(self) -> List[str]:
        return [i.message for i in self.issues if i.severity in ("BLOCKING", "SOFT_BLOCK")]


class ExtractedField(BaseModel):
    value: Any
    confidence: float = 1.0
    source: str = "structured"


class ExtractedDocument(BaseModel):
    file_id: str
    document_type: DocumentType
    patient_name: Optional[ExtractedField] = None
    doctor_name: Optional[ExtractedField] = None
    doctor_registration: Optional[ExtractedField] = None
    date: Optional[ExtractedField] = None
    diagnosis: Optional[ExtractedField] = None
    treatment: Optional[ExtractedField] = None
    medicines: List[str] = Field(default_factory=list)
    tests_ordered: List[str] = Field(default_factory=list)
    line_items: List[Dict[str, Any]] = Field(default_factory=list)
    total_amount: Optional[float] = None
    hospital_name: Optional[ExtractedField] = None
    extraction_confidence: float = 1.0
    extraction_errors: List[str] = Field(default_factory=list)
    degraded: bool = False


class FraudSignal(BaseModel):
    signal_type: str
    description: str
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    data: Optional[Dict[str, Any]] = None


class FraudResult(BaseModel):
    fraud_score: float = 0.0
    signals: List[FraudSignal] = Field(default_factory=list)
    requires_manual_review: bool = False
    degraded: bool = False
    trace: List[TraceEntry] = Field(default_factory=list)


class PolicyCheck(BaseModel):
    check_name: str
    passed: bool
    detail: str
    impact: Optional[str] = None


class LineItemDecision(BaseModel):
    description: str
    claimed_amount: float
    approved_amount: float
    reason: Optional[str] = None
    covered: bool = True


class FinancialBreakdown(BaseModel):
    claimed_amount: float
    sub_limit_cap: Optional[float] = None
    network_discount_amount: float = 0.0
    network_discount_percent: float = 0.0
    copay_amount: float = 0.0
    copay_percent: float = 0.0
    approved_amount: float = 0.0


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------

class ValidationFailedResult(BaseModel):
    status: Literal["VALIDATION_FAILED"] = "VALIDATION_FAILED"
    claim_id: str
    errors: List[str]
    issues: List[ValidationIssue] = Field(default_factory=list)
    trace: List[TraceEntry] = Field(default_factory=list)
    processing_time_ms: int = 0


class ClaimDecisionResult(BaseModel):
    status: Literal["DECIDED"] = "DECIDED"
    claim_id: str
    decision: DecisionType
    approved_amount: float
    claimed_amount: float
    reason: str
    confidence_score: float
    rejection_reasons: List[RejectionReason] = Field(default_factory=list)
    financial_breakdown: Optional[FinancialBreakdown] = None
    line_items: List[LineItemDecision] = Field(default_factory=list)
    policy_checks: List[PolicyCheck] = Field(default_factory=list)
    fraud_signals: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    eligibility_date: Optional[date] = None
    degraded_components: List[str] = Field(default_factory=list)
    processing_errors: List[str] = Field(default_factory=list)
    trace: List[TraceEntry] = Field(default_factory=list)
    processing_time_ms: int = 0


ClaimResult = Union[ValidationFailedResult, ClaimDecisionResult]
