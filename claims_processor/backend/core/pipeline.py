"""
Claims Processing Pipeline — Orchestrator.

Coordinates all agents in sequence, handles partial failures, and assembles
the final result. The pipeline is stateless — create a new instance per request
or share one across requests (all agents are also stateless).

Stage order:
  1. DocumentValidatorAgent  — blocking gate, stops early on bad docs
  2. DocumentExtractorAgent  — parallel extraction from all docs
  3. FraudDetectorAgent      — behavioral + document fraud signals
  4. PolicyEngine.evaluate   — deterministic policy rules
  5. PolicyEngine.evaluate_line_items — per-item (dental/vision)
  6. DecisionMaker.synthesize — final decision assembly
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.decision_maker import DecisionMaker
from agents.document_extractor import DocumentExtractorAgent
from agents.document_validator import DocumentValidatorAgent
from agents.fraud_detector import FraudDetectorAgent
from core.models import (
    ClaimCategory,
    ClaimResult,
    ClaimSubmission,
    FraudResult,
    ValidationFailedResult,
)
from core.policy_engine import PolicyEngine
from core.trace import TraceBuilder

logger = logging.getLogger(__name__)

_CATEGORIES_WITH_LINE_ITEM_RULES = {ClaimCategory.DENTAL, ClaimCategory.VISION}


class ClaimsPipeline:
    def __init__(self, policy_path: Path) -> None:
        policy_engine = PolicyEngine(policy_path)

        self._validator = DocumentValidatorAgent(
            policy_document_requirements=self._build_doc_requirements(policy_engine)
        )
        self._extractor = DocumentExtractorAgent()
        self._fraud_detector = FraudDetectorAgent(
            fraud_thresholds=self._load_fraud_thresholds(policy_engine)
        )
        self._policy_engine = policy_engine
        self._decision_maker = DecisionMaker()

    async def process(self, submission: ClaimSubmission) -> ClaimResult:
        trace = TraceBuilder()
        start_ms = time.monotonic()

        trace.info("pipeline", "start",
                   f"Processing claim {submission.claim_id} | "
                   f"Member: {submission.member_id} | "
                   f"Category: {submission.claim_category.value} | "
                   f"Amount: ₹{submission.claimed_amount:,.2f}")

        # ----------------------------------------------------------------
        # Stage 1 — Document Validation Gate
        # ----------------------------------------------------------------
        validation_result = self._validator.validate(submission, trace)

        if validation_result.has_blocking_issues:
            elapsed = int((time.monotonic() - start_ms) * 1000)
            trace.failed("pipeline", "complete",
                         "Pipeline halted at document validation stage")
            return ValidationFailedResult(
                claim_id=submission.claim_id,
                errors=validation_result.blocking_messages,
                issues=validation_result.issues,
                trace=trace.entries(),
                processing_time_ms=elapsed,
            )

        # ----------------------------------------------------------------
        # Stage 2 — Document Extraction (parallel across all docs)
        # ----------------------------------------------------------------
        trace.info("pipeline", "extraction_start",
                   f"Extracting from {len(submission.documents)} document(s)")

        extractions = await self._extractor.extract_all(submission, trace)

        degraded_components: List[str] = []
        processing_errors: List[str] = []

        extraction_failures = [e for e in extractions if e.degraded]
        if extraction_failures:
            ids = [e.file_id for e in extraction_failures]
            processing_errors.extend([
                f"Extraction partially failed for: {', '.join(ids)}"
            ])
            trace.warn("pipeline", "extraction_degraded",
                       f"{len(extraction_failures)} document(s) failed extraction",
                       {"file_ids": ids})

        # ----------------------------------------------------------------
        # Stage 3 — Fraud Detection
        # ----------------------------------------------------------------
        try:
            fraud_result = await self._fraud_detector.analyze(submission, extractions, trace)
        except Exception as exc:
            logger.warning("Fraud detection failed (degraded): %s", exc)
            fraud_result = FraudResult(degraded=True)
            degraded_components.append("fraud_detector")
            processing_errors.append(f"Fraud detection skipped: {exc!s}")
            trace.error("pipeline", "fraud_detection_failed",
                        f"FraudDetectorAgent failed: {exc!s} — continuing with degraded result")

        # ----------------------------------------------------------------
        # Stage 4 — Policy Evaluation (deterministic)
        # ----------------------------------------------------------------
        (
            policy_checks,
            rejection_reasons,
            breakdown,
            eligibility_date,
            warnings,
        ) = self._policy_engine.evaluate(submission, extractions, trace)

        # ----------------------------------------------------------------
        # Stage 5 — Line-item evaluation (dental / vision)
        # ----------------------------------------------------------------
        line_item_decisions = []
        if submission.claim_category in _CATEGORIES_WITH_LINE_ITEM_RULES:
            line_item_decisions = self._policy_engine.evaluate_line_items(
                submission, extractions, trace
            )

        # ----------------------------------------------------------------
        # Stage 6 — Decision Synthesis
        # ----------------------------------------------------------------
        result = self._decision_maker.synthesize(
            submission=submission,
            extractions=extractions,
            fraud_result=fraud_result,
            policy_checks=policy_checks,
            rejection_reasons=rejection_reasons,
            breakdown=breakdown,
            line_item_decisions=line_item_decisions,
            eligibility_date=eligibility_date,
            warnings=warnings,
            degraded_components=degraded_components,
            processing_errors=processing_errors,
            trace=trace,
        )

        elapsed = int((time.monotonic() - start_ms) * 1000)
        result.processing_time_ms = elapsed

        trace.info("pipeline", "complete",
                   f"Pipeline finished in {elapsed}ms — {result.decision.value}")

        return result

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def _build_doc_requirements(self, engine: PolicyEngine) -> Dict[str, Any]:
        from core.models import ClaimCategory
        result = {}
        for cat in ClaimCategory:
            result[cat.value] = engine.get_document_requirements(cat)
        return result

    def _load_fraud_thresholds(self, engine: PolicyEngine) -> Dict[str, Any]:
        # Access internal policy dict for fraud thresholds
        return engine._policy.get("fraud_thresholds", {})
