# Component Contracts
## Plum Claims Processing System

Each contract below is precise enough that a reimplementation of the component would be drop-in compatible.

---

## ClaimsPipeline

**Module**: `core/pipeline.py`

### Input
```python
submission: ClaimSubmission
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `claim_id` | `str` | No (auto-generated) | UUID-based claim identifier |
| `member_id` | `str` | Yes | Must match a member in the policy roster |
| `policy_id` | `str` | Yes | Policy identifier |
| `claim_category` | `ClaimCategory` | Yes | CONSULTATION / DIAGNOSTIC / PHARMACY / DENTAL / VISION / ALTERNATIVE_MEDICINE |
| `treatment_date` | `date` | Yes | Date of treatment |
| `claimed_amount` | `float` | Yes | Must be > 0 |
| `hospital_name` | `str` | No | If set, checked against network hospital list |
| `documents` | `List[Document]` | Yes | At least 1 document required |
| `ytd_claims_amount` | `float` | No (default 0) | Year-to-date OPD claims consumed |
| `claims_history` | `List[Dict]` | No | Prior claims for fraud detection |
| `simulate_component_failure` | `bool` | No | Forces FraudDetectorAgent to fail |

### Output
`ClaimResult = Union[ValidationFailedResult, ClaimDecisionResult]`

Discriminated by the `status` field.

#### ValidationFailedResult
```python
{
  "status": "VALIDATION_FAILED",
  "claim_id": str,
  "errors": List[str],          # human-readable blocking messages
  "issues": List[ValidationIssue],
  "trace": List[TraceEntry],
  "processing_time_ms": int
}
```

#### ClaimDecisionResult
```python
{
  "status": "DECIDED",
  "claim_id": str,
  "decision": "APPROVED" | "PARTIAL" | "REJECTED" | "MANUAL_REVIEW",
  "approved_amount": float,      # 0.0 if REJECTED or MANUAL_REVIEW
  "claimed_amount": float,
  "reason": str,                 # human-readable primary reason
  "confidence_score": float,     # 0.0–1.0
  "rejection_reasons": List[str],
  "financial_breakdown": FinancialBreakdown | None,
  "line_items": List[LineItemDecision],
  "policy_checks": List[PolicyCheck],
  "fraud_signals": List[str],
  "warnings": List[str],
  "eligibility_date": date | None,  # when waiting period ends (WAITING_PERIOD rejections)
  "degraded_components": List[str],
  "processing_errors": List[str],
  "trace": List[TraceEntry],
  "processing_time_ms": int
}
```

### Errors raised
- None (all errors are captured in the result, never thrown to the caller)

---

## DocumentValidatorAgent

**Module**: `agents/document_validator.py`

### Input
```python
submission: ClaimSubmission
trace: TraceBuilder
```

### Output
```python
ValidationResult(
  passed: bool,
  issues: List[ValidationIssue],
  trace: List[TraceEntry]
)
```

`ValidationIssue`:
```python
{
  "code": "MISSING_REQUIRED_DOCUMENTS" | "UNREADABLE_DOCUMENT" | "PATIENT_NAME_MISMATCH",
  "severity": "BLOCKING" | "SOFT_BLOCK" | "WARNING",
  "message": str,   # actionable, specific, names the problematic documents
  "documents_involved": List[str]
}
```

### Guarantees
- `MISSING_REQUIRED_DOCUMENTS` messages must name the submitted types AND the missing types.
- `UNREADABLE_DOCUMENT` messages must name the specific file and request re-upload.
- `PATIENT_NAME_MISMATCH` messages must include both names found.
- Runs in O(n) where n = number of documents. No network calls.

### Errors raised
- None — all exceptional cases produce issues, not exceptions.

---

## DocumentExtractorAgent

**Module**: `agents/document_extractor.py`

### Input
```python
submission: ClaimSubmission
trace: TraceBuilder
```

### Output
```python
List[ExtractedDocument]   # one per input document, always the same length
```

`ExtractedDocument`:
```python
{
  "file_id": str,
  "document_type": DocumentType,
  "patient_name": ExtractedField | None,
  "doctor_name": ExtractedField | None,
  "doctor_registration": ExtractedField | None,
  "date": ExtractedField | None,
  "diagnosis": ExtractedField | None,
  "treatment": ExtractedField | None,
  "medicines": List[str],
  "tests_ordered": List[str],
  "line_items": List[{"description": str, "amount": float}],
  "total_amount": float | None,
  "hospital_name": ExtractedField | None,
  "extraction_confidence": float,   # 0.0–1.0
  "extraction_errors": List[str],
  "degraded": bool
}
```

`ExtractedField`:
```python
{"value": Any, "confidence": float, "source": "structured" | "vision"}
```

### Execution modes
1. `content` present → structured extraction, `extraction_confidence = 1.0`
2. `raw_bytes` present → vision extraction via Anthropic API
3. Neither → `degraded=True`, `extraction_confidence = 0.3`

### Guarantees
- Output list length always equals input document count.
- Individual failures produce `degraded=True` entries, never propagate as exceptions.
- Vision extraction timeout: inherits from Anthropic SDK default (600s).

### Errors raised
- Never raises. All failures are captured in `degraded=True` entries.

---

## FraudDetectorAgent

**Module**: `agents/fraud_detector.py`

### Input
```python
submission: ClaimSubmission
extractions: List[ExtractedDocument]
trace: TraceBuilder
```

### Output
```python
FraudResult(
  fraud_score: float,              # 0.0–1.0 (additive signals, capped)
  signals: List[FraudSignal],
  requires_manual_review: bool,
  degraded: bool,
  trace: List[TraceEntry]
)
```

`FraudSignal`:
```python
{
  "signal_type": str,
  "description": str,
  "severity": "HIGH" | "MEDIUM" | "LOW",
  "data": Dict | None
}
```

### Signal scoring
| Signal | Score contribution |
|--------|--------------------|
| Same-day claims ≥ limit | 0.45 |
| High-value claim (> threshold) | 0.20 |
| Document alteration | 0.25 |
| Multiple providers same day | 0.20 |

`requires_manual_review = True` when `fraud_score >= 0.80` OR `amount > auto_manual_review_above`.

### Special behavior
When `submission.simulate_component_failure = True`, raises `RuntimeError`. This is intentional — it tests the pipeline's degradation path.

### Errors raised
- `RuntimeError` when `simulate_component_failure=True`
- All other errors: logged, result in `degraded=True`

---

## PolicyEngine

**Module**: `core/policy_engine.py`

### `evaluate(submission, extractions, trace)`

Runs all policy checks in order.

**Input**: `ClaimSubmission`, `List[ExtractedDocument]`, `TraceBuilder`

**Output**: `Tuple[List[PolicyCheck], List[RejectionReason], Optional[FinancialBreakdown], Optional[date], List[str]]`

| Position | Type | Description |
|----------|------|-------------|
| 0 | `List[PolicyCheck]` | Every check that was run, with pass/fail status |
| 1 | `List[RejectionReason]` | Populated if any hard policy check failed |
| 2 | `FinancialBreakdown \| None` | None if rejected; populated if approved |
| 3 | `date \| None` | Eligibility date for waiting-period rejections |
| 4 | `List[str]` | Non-fatal warnings |

**Short-circuit behavior**: Returns immediately on first rejection (no further checks run).

### `evaluate_line_items(submission, extractions, trace)`

For DENTAL and VISION claims. Evaluates each bill line item against covered/excluded procedure lists.

**Output**: `List[LineItemDecision]`

### Financial calculation order (critical for TC010)
```
1. Start with claimed_amount
2. Apply network_discount_percent if hospital is in network_hospitals list
3. Apply copay_percent to the post-discount amount
4. approved_amount = (claimed_amount × (1 - network_discount)) × (1 - copay)
```

**Network discount is always applied BEFORE co-pay.**

### Errors raised
- `FileNotFoundError` if `policy_terms.json` not found at initialization
- Never raises during evaluation (all edge cases return rejection reasons)

---

## DecisionMaker

**Module**: `agents/decision_maker.py`

### `synthesize(submission, extractions, fraud_result, policy_checks, rejection_reasons, breakdown, line_item_decisions, eligibility_date, warnings, degraded_components, processing_errors, trace)`

### Output
`ClaimDecisionResult` (see ClaimsPipeline output contract above)

### Decision hierarchy (deterministic)
```
1. IF fraud_result.requires_manual_review → MANUAL_REVIEW
2. ELIF rejection_reasons non-empty → REJECTED
3. ELIF line_items has both covered and non-covered items → PARTIAL
4. ELSE → APPROVED
```

### Confidence formula
```
confidence = 1.0
           - len(degraded_components) × 0.20
           - len(degraded_extractions) × 0.10
           - len(low_confidence_extractions) × 0.05
           - (1 if non-review fraud signals else 0) × 0.10
```
Clamped to [0.0, 1.0].

### Errors raised
- None (all synthesis is based on well-typed inputs)

---

## TraceBuilder

**Module**: `core/trace.py`

Single-claim scoped, not thread-safe.

### Methods
| Method | Status emitted |
|--------|----------------|
| `info(component, step, detail, data?)` | INFO |
| `passed(component, step, detail, data?)` | PASS |
| `failed(component, step, detail, data?)` | FAIL |
| `warn(component, step, detail, data?)` | WARN |
| `error(component, step, detail, data?)` | ERROR |
| `span(component, step)` | Context manager — emits PASS on exit, ERROR on exception |

### Output
`entries() → List[TraceEntry]`

`TraceEntry`:
```python
{
  "component": str,
  "step": str,
  "status": "PASS" | "FAIL" | "WARN" | "INFO" | "ERROR",
  "detail": str,
  "data": Dict | None,
  "timestamp": datetime
}
```
