# Architecture Document
## Plum Health Insurance Claims Processing System

---

## Overview

This system automates the manual claims review process for Plum's Group Health Insurance product. It accepts a claim submission (member details, treatment type, amount, documents), processes it through a multi-agent pipeline, and produces an explainable decision: APPROVED, PARTIAL, REJECTED, or MANUAL_REVIEW.

The core design principle is: **LLMs where human-like understanding is needed, deterministic code where correctness is non-negotiable.**

---

## System Architecture

```
                         ┌─────────────────────────────────────────────────────┐
                         │                 ClaimsPipeline                       │
                         │                 (Orchestrator)                        │
                         └──────────────────────┬──────────────────────────────┘
                                                 │
          ┌──────────────────────────────────────▼──────────────────────────────────────────┐
          │                         Stage 1: Validation Gate                                 │
          │                        DocumentValidatorAgent                                    │
          │  • Required doc type completeness check                                          │
          │  • Document quality check (UNREADABLE detection)                                 │
          │  • Cross-document patient identity consistency                                   │
          │                                                                                  │
          │  BLOCKING GATE — pipeline halts here with specific error if any check fails      │
          └──────────────────────────────────┬───────────────────────────────────────────────┘
                                             │ (if passes)
          ┌──────────────────────────────────▼───────────────────────────────────────────────┐
          │                     Stage 2: Extraction (parallel per doc)                        │
          │                        DocumentExtractorAgent                                    │
          │  • Structured path: pre-parsed content → direct mapping                          │
          │  • Vision path: raw image/PDF → Claude claude-haiku-4-5 API call                      │
          │  • Field-level confidence scoring                                                 │
          │  • Graceful degradation: extraction failures → degraded=True                     │
          └──────────────────────────────────┬───────────────────────────────────────────────┘
                                             │
               ┌──────────────────┬──────────▼───────────────┬────────────────┐
               │                  │                           │                │
          ┌────▼───────┐  ┌───────▼──────────┐    ┌──────────▼──────┐       │
          │  Fraud     │  │  Policy Engine   │    │  Line-item      │       │
          │  Detector  │  │  (deterministic) │    │  Evaluator      │       │
          │  Agent     │  │                  │    │  (dental/vision)│       │
          │            │  │  • Member check  │    │                 │       │
          │  Can fail  │  │  • Waiting period│    │  Procedure-level│       │
          │  safely —  │  │  • Exclusions    │    │  coverage rules │       │
          │  pipeline  │  │  • Pre-auth      │    │                 │       │
          │  continues │  │  • Per-claim cap │    │                 │       │
          └────┬───────┘  │  • Financial calc│    └──────────┬──────┘       │
               │          └───────┬──────────┘               │              │
               └──────────────────┴──────────────────────────┘              │
                                             │                               │
          ┌──────────────────────────────────▼───────────────────────────────────────────────┐
          │                          Stage 6: Decision Synthesis                               │
          │                              DecisionMaker                                        │
          │  • Hierarchy: MANUAL_REVIEW > REJECTED > PARTIAL > APPROVED                      │
          │  • Confidence score: base 1.0, penalties for degraded components/extractions      │
          │  • Line-item reasoning for partial decisions                                      │
          │  • Human-readable reason text                                                     │
          └──────────────────────────────────┬───────────────────────────────────────────────┘
                                             │
                                     ClaimResult
                          (ValidationFailedResult | ClaimDecisionResult)
```

---

## Component Responsibilities

### ClaimsPipeline (core/pipeline.py)
The only entry point for claim processing. Responsible for:
- Sequencing all stages
- Catching component failures and continuing in degraded mode
- Passing the shared `TraceBuilder` context to all stages

**Why a pipeline?** It enforces the stage order, makes the control flow explicit, and provides a single place to handle cross-cutting concerns like timing and degradation tracking.

### DocumentValidatorAgent (agents/document_validator.py)
Stateless, synchronous, LLM-free. Runs before any expensive processing.

Three checks in priority order:
1. **Required types** — Does the submitted document set contain all required types for the claim category? Error messages name both what was submitted and what was missing.
2. **Quality check** — Any `UNREADABLE` document triggers a soft-block with a specific re-upload instruction.
3. **Patient identity** — Cross-checks names across all documents. Detects TC003-style mismatch.

**Why no LLM here?** These checks must be fast, deterministic, and cheap. They run on every claim before any inference. A wrong document type is a structural problem that needs no AI to detect.

### DocumentExtractorAgent (agents/document_extractor.py)
Async, with two execution paths:

- **Structured path** (test cases, pre-parsed inputs): directly maps the `content` dict to the `ExtractedDocument` model. Confidence = 1.0.
- **Vision path** (real images/PDFs): calls `claude-haiku-4-5-20251001` with a structured extraction prompt. Parses the JSON response into the model. Handles markdown-wrapped JSON. Degrades gracefully on API errors.

Individual document failures never propagate to the pipeline level — each failed document returns `degraded=True` and the pipeline tracks the degradation in the confidence score.

**Why claude-haiku-4-5 for extraction?** It's fast and cost-efficient for this structured extraction task. claude-sonnet-4-6 would be overkill unless complex multi-hop reasoning is required (e.g., interpreting a complex clinical discharge summary).

### FraudDetectorAgent (agents/fraud_detector.py)
Evaluates behavioral and document-level fraud signals:
- Same-day claim frequency vs policy limit
- High-value claim threshold
- Document alteration markers
- Multiple providers on the same day

Scores are additive, capped at 1.0. High scores escalate to MANUAL_REVIEW rather than auto-rejecting — fraud is probabilistic, and human review is the right response.

**Critical design choice**: This agent intentionally raises an exception when `simulate_component_failure=True` (TC011). The pipeline is designed to catch this and continue with a degraded fraud result. This tests the pipeline's resilience contract.

### PolicyEngine (core/policy_engine.py)
Purely deterministic. No LLM, no network calls.

Checks in order (first rejection short-circuits):
1. Member eligibility (is the member in the roster?)
2. Initial 30-day waiting period
3. Condition-specific waiting period (diabetes=90d, maternity=270d, etc.)
4. Policy exclusions (keyword matching against diagnosis/treatment text)
5. Pre-authorization requirements (high-value MRI/CT/PET)
6. Per-claim monetary limit
7. Annual OPD limit
8. Submission deadline
9. Financial calculation (network discount → co-pay → approved amount)

**Why deterministic?** Policy rules need to be auditable and testable. A policy change should produce a code change that can be reviewed and tested in isolation. LLM-driven policy evaluation would be non-deterministic, hard to version, and impossible to formally verify.

### DecisionMaker (agents/decision_maker.py)
Synthesizes all signals into a final decision using a strict hierarchy:
1. MANUAL_REVIEW (fraud signals exceed threshold)
2. REJECTED (any policy check failed)
3. PARTIAL (some line items approved, some excluded)
4. APPROVED (all checks pass)

Confidence score formula:
```
confidence = 1.0
           - (degraded_components × 0.20)
           - (degraded_extractions × 0.10)
           - (low_confidence_extractions × 0.05)
           - (fraud_signals_present × 0.10)
```

### TraceBuilder (core/trace.py)
A simple append-only log that is passed through the entire pipeline. Every component emits structured `TraceEntry` objects with component, step, status, detail, and optional data payload. The final result carries the complete trace.

**Why pass-by-reference instead of events/pub-sub?** This is a synchronous request-response pipeline, not an event-driven system. The simplicity of passing a mutable object is appropriate here. At 10x scale, we'd move to structured logging with a trace ID that can be queried in a log aggregation system.

---

## Key Design Decisions

### 1. Deterministic Policy Engine (not LLM-driven)
**Considered**: Using Claude to interpret policy rules and evaluate claims.
**Rejected**: LLM-driven policy evaluation is non-deterministic, expensive per claim, hard to test, and creates an audit trail problem (the reason a claim was rejected must be stable and reproducible).
**Chose**: Pure Python policy engine loaded from `policy_terms.json`. Every check is a testable function. Policy changes = code changes = code review.

### 2. Document Classification from `actual_type` (not vision classifier)
**Considered**: Using a vision model to classify each uploaded document before extraction.
**Recognized**: In a real deployment, the member selects the document type at upload time. For test cases, `actual_type` is the ground truth. A classification step would add latency for a problem that the UI can solve through UX.
**Design for production**: Add a classification step only for documents where type is genuinely ambiguous, with low confidence triggering a human check.

### 3. Validation Gate Before Extraction
**Considered**: Running extraction first, then validating based on extracted content.
**Rejected**: Extraction is the most expensive step (LLM call). Running it on clearly wrong documents wastes money and adds latency. The gate is cheap and fast.

### 4. No Database (In-Memory Store)
**Considered**: PostgreSQL or SQLite for claim persistence.
**Chose**: In-memory dict for this implementation.
**Production plan**: PostgreSQL with a `claims` table indexed on `claim_id`, `member_id`, and `treatment_date`. Redis for caching policy terms (they change infrequently). The interface (pipeline returns a Pydantic model) is already storage-agnostic.

### 5. MANUAL_REVIEW Beats APPROVED for Fraud
The decision hierarchy deliberately places MANUAL_REVIEW above all other outcomes. A legitimate claim with strong fraud signals still goes to a human. This prevents the system from auto-approving potentially fraudulent claims just because the policy checks pass.

---

## Failure Modes & Resilience

| Component | Failure | Pipeline Response |
|-----------|---------|-------------------|
| DocumentValidatorAgent | Exception | 500 error (validation is synchronous and should never fail) |
| DocumentExtractorAgent (single doc) | API timeout / JSON parse error | Document marked `degraded=True`, extraction continues for other docs |
| FraudDetectorAgent | Any exception | `degraded_components` += "fraud_detector", fraud score set to 0, confidence penalty applied |
| PolicyEngine | Exception | 500 error (deterministic logic should never throw on valid inputs) |
| DecisionMaker | Exception | 500 error (synthesis should never fail given valid inputs) |

---

## Scaling to 10x Load (10M lives)

At the current scale (~75k claims/year ≈ ~200/day), the in-process pipeline works fine.

At 10x:

1. **Queue-based processing**: Move `ClaimsPipeline.process()` to a Celery/RQ worker. The API endpoint enqueues the job and returns a 202 with a claim_id. Polling/webhooks deliver the result.

2. **Extraction parallelism**: Currently per-claim document extraction is parallelized. With a queue, we'd also parallelize across claims.

3. **Policy engine caching**: Load `policy_terms.json` at startup (already done). At 10x scale, serve multiple policy versions from a database with a version key per claim.

4. **LLM rate limits**: At high volume, Anthropic API rate limits become a constraint. Solution: use a token bucket, batch extraction requests, and consider fine-tuning a smaller model on extracted document pairs.

5. **Observability**: Move from in-memory trace to structured logging (JSON lines to Datadog/CloudWatch). Add trace IDs, span IDs, and a dashboard for claim decision distribution.

6. **Database**: PostgreSQL with read replicas for claims history lookups (fraud detection). The same-day claim check currently looks at `claims_history` in the request body — in production, this comes from the database.

---

## What I Would Change Given More Time

1. **Real document generation**: Create a set of test PDFs with degraded quality (blur, stamps, handwriting) to validate the vision extraction path end-to-end.

2. **Confidence calibration**: The current confidence penalties are rough heuristics. A calibrated model trained on historical claims data would be more accurate.

3. **LLM for complex partial decisions**: For cases where a bill has ambiguous line items (e.g., "Medical Supplies" — is that pharmacy or consumables?), a short LLM call with the bill context and policy terms could determine coverage more accurately than keyword matching.

4. **Event sourcing**: Store the full trace as immutable audit events in an append-only log, not just in the response object. This enables replaying decisions after policy changes.

5. **Pre-auth integration**: In production, pre-auth status would be checked against an actual authorization registry, not inferred from the claim input.
