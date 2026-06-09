"""
Decision Maker — Final stage of the pipeline.

Synthesizes policy engine outputs, fraud signals, and extraction quality into
a single structured decision. All logic here is deterministic — the LLM
is not involved in the final decision so results are reproducible.

Decision hierarchy (first match wins):
  MANUAL_REVIEW  — fraud signals exceed threshold OR high-value auto-review
  REJECTED       — any hard policy check failed
  PARTIAL        — some line items approved, some rejected (dental/vision categories)
  APPROVED       — all checks passed, full amount approved
"""
from __future__ import annotations

from typing import List, Optional

from core.models import (
    ClaimCategory,
    ClaimDecisionResult,
    ClaimSubmission,
    DecisionType,
    ExtractedDocument,
    FinancialBreakdown,
    FraudResult,
    LineItemDecision,
    PolicyCheck,
    RejectionReason,
    ValidationFailedResult,
)
from core.trace import TraceBuilder

COMPONENT = "decision_maker"

# Confidence penalties
_PENALTY_DEGRADED_COMPONENT = 0.20
_PENALTY_LOW_QUALITY_EXTRACTION = 0.10
_PENALTY_FRAUD_SIGNALS = 0.10
_PENALTY_PARTIAL_EXTRACTION = 0.05
_BASE_CONFIDENCE = 1.0


class DecisionMaker:
    def synthesize(
        self,
        submission: ClaimSubmission,
        extractions: List[ExtractedDocument],
        fraud_result: FraudResult,
        policy_checks: List[PolicyCheck],
        rejection_reasons: List[RejectionReason],
        breakdown: Optional[FinancialBreakdown],
        line_item_decisions: List[LineItemDecision],
        eligibility_date,
        warnings: List[str],
        degraded_components: List[str],
        processing_errors: List[str],
        trace: TraceBuilder,
    ) -> ClaimDecisionResult:

        trace.info(COMPONENT, "start", "Synthesizing final claim decision")

        # --- Determine decision type ---
        decision, reason, approved_amount = self._determine_decision(
            submission=submission,
            rejection_reasons=rejection_reasons,
            fraud_result=fraud_result,
            breakdown=breakdown,
            line_item_decisions=line_item_decisions,
            policy_checks=policy_checks,
            eligibility_date=eligibility_date,
            trace=trace,
        )

        # --- Compute confidence score ---
        confidence = self._compute_confidence(
            decision=decision,
            extractions=extractions,
            fraud_result=fraud_result,
            degraded_components=degraded_components,
            rejection_reasons=rejection_reasons,
        )

        # --- Finalize line items ---
        final_line_items = self._finalize_line_items(
            submission=submission,
            line_item_decisions=line_item_decisions,
            breakdown=breakdown,
            decision=decision,
        )

        # --- Build fraud signal strings for output ---
        fraud_signal_strings = [s.description for s in fraud_result.signals]

        if degraded_components:
            warnings.append(
                f"The following pipeline components failed and were skipped: "
                f"{', '.join(degraded_components)}. "
                f"This claim should be manually reviewed to confirm the decision."
            )

        trace.passed(COMPONENT, "decision_complete",
                     f"Decision: {decision.value} | Amount: ₹{approved_amount:,.2f} | "
                     f"Confidence: {confidence:.2f}",
                     {"decision": decision.value, "approved": approved_amount,
                      "confidence": confidence})

        return ClaimDecisionResult(
            status="DECIDED",
            claim_id=submission.claim_id,
            decision=decision,
            approved_amount=approved_amount,
            claimed_amount=submission.claimed_amount,
            reason=reason,
            confidence_score=round(confidence, 2),
            rejection_reasons=rejection_reasons,
            financial_breakdown=breakdown,
            line_items=final_line_items,
            policy_checks=policy_checks,
            fraud_signals=fraud_signal_strings,
            warnings=warnings,
            eligibility_date=eligibility_date,
            degraded_components=degraded_components,
            processing_errors=processing_errors,
            trace=trace.entries(),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _determine_decision(
        self,
        submission: ClaimSubmission,
        rejection_reasons: List[RejectionReason],
        fraud_result: FraudResult,
        breakdown: Optional[FinancialBreakdown],
        line_item_decisions: List[LineItemDecision],
        policy_checks: List[PolicyCheck],
        eligibility_date,
        trace: TraceBuilder,
    ):
        # 1. Manual review (fraud) — checked first so legitimate partial claims
        #    still get routed to humans when there are fraud signals
        if fraud_result.requires_manual_review:
            signal_types = [s.signal_type for s in fraud_result.signals]
            reason = (
                f"Claim flagged for manual review due to fraud signals: "
                f"{', '.join(signal_types)}. "
                f"Fraud score: {fraud_result.fraud_score:.2f}. "
                f"A claims specialist will review within 2 business days."
            )
            trace.warn(COMPONENT, "decision",
                       "MANUAL_REVIEW — fraud signals triggered escalation")
            return DecisionType.MANUAL_REVIEW, reason, 0.0

        # 2. Rejected
        if rejection_reasons:
            reason = self._build_rejection_reason(
                rejection_reasons, policy_checks, eligibility_date, submission
            )
            trace.failed(COMPONENT, "decision",
                         f"REJECTED — reasons: {[r.value for r in rejection_reasons]}")
            return DecisionType.REJECTED, reason, 0.0

        # 3. Partial — some line items approved, some rejected
        if line_item_decisions:
            approved_items = [i for i in line_item_decisions if i.covered]
            rejected_items = [i for i in line_item_decisions if not i.covered]
            if rejected_items and approved_items:
                approved_amount = sum(i.approved_amount for i in approved_items)
                # apply copay/discount to the approved sub-total
                if breakdown:
                    ratio = approved_amount / submission.claimed_amount if submission.claimed_amount else 1
                    net_discount = breakdown.network_discount_amount * ratio
                    after_discount = approved_amount - net_discount
                    copay_pct = breakdown.copay_percent / 100
                    final_approved = round(after_discount * (1 - copay_pct), 2)
                else:
                    final_approved = approved_amount

                rejected_summary = "; ".join(
                    f"{i.description} (₹{i.claimed_amount:,.0f}) — {i.reason}"
                    for i in rejected_items
                )
                reason = (
                    f"Partial approval: ₹{final_approved:,.2f} approved. "
                    f"The following line items were not covered: {rejected_summary}."
                )
                trace.warn(COMPONENT, "decision",
                           f"PARTIAL — {len(approved_items)} approved, {len(rejected_items)} rejected")
                return DecisionType.PARTIAL, reason, final_approved

        # 4. Full approval
        if breakdown is None:
            # Should not reach here normally — breakdown should always be set for approvals
            approved_amount = submission.claimed_amount
        else:
            approved_amount = breakdown.approved_amount

        reason = self._build_approval_reason(submission, breakdown, policy_checks)
        trace.passed(COMPONENT, "decision",
                     f"APPROVED — ₹{approved_amount:,.2f}")
        return DecisionType.APPROVED, reason, approved_amount

    def _build_rejection_reason(
        self,
        reasons: List[RejectionReason],
        checks: List[PolicyCheck],
        eligibility_date,
        submission: ClaimSubmission,
    ) -> str:
        primary = reasons[0]
        failed_checks = [c for c in checks if not c.passed]
        detail = failed_checks[0].detail if failed_checks else ""

        if primary == RejectionReason.WAITING_PERIOD:
            eligibility_str = (
                f" You will be eligible from {eligibility_date}."
                if eligibility_date else ""
            )
            return f"Claim rejected: waiting period not served.{eligibility_str} {detail}"

        if primary == RejectionReason.EXCLUDED_CONDITION:
            return f"Claim rejected: treatment is excluded under this policy. {detail}"

        if primary == RejectionReason.PRE_AUTH_MISSING:
            return detail or "Pre-authorization was required but not obtained before the procedure."

        if primary == RejectionReason.PER_CLAIM_EXCEEDED:
            limit = next(
                (c for c in checks if c.check_name == "per_claim_limit" and not c.passed), None
            )
            return limit.detail if limit else (
                f"Claimed amount ₹{submission.claimed_amount:,.0f} exceeds the per-claim limit."
            )

        return detail or f"Claim rejected: {', '.join(r.value for r in reasons)}."

    def _build_approval_reason(
        self,
        submission: ClaimSubmission,
        breakdown: Optional[FinancialBreakdown],
        checks: List[PolicyCheck],
    ) -> str:
        if not breakdown:
            return f"Claim approved for ₹{submission.claimed_amount:,.2f}."

        parts = [f"Claimed: ₹{breakdown.claimed_amount:,.2f}"]

        if breakdown.network_discount_amount > 0:
            parts.append(
                f"network discount ({breakdown.network_discount_percent:.0f}%): "
                f"-₹{breakdown.network_discount_amount:,.2f}"
            )

        if breakdown.copay_amount > 0:
            parts.append(
                f"co-pay ({breakdown.copay_percent:.0f}%): -₹{breakdown.copay_amount:,.2f}"
            )

        parts.append(f"approved: ₹{breakdown.approved_amount:,.2f}")
        return " → ".join(parts) + "."

    def _compute_confidence(
        self,
        decision: DecisionType,
        extractions: List[ExtractedDocument],
        fraud_result: FraudResult,
        degraded_components: List[str],
        rejection_reasons: List[RejectionReason],
    ) -> float:
        score = _BASE_CONFIDENCE

        # Degraded pipeline components
        score -= len(degraded_components) * _PENALTY_DEGRADED_COMPONENT

        # Extraction quality
        degraded_docs = [e for e in extractions if e.degraded]
        score -= len(degraded_docs) * _PENALTY_LOW_QUALITY_EXTRACTION

        low_confidence_extractions = [
            e for e in extractions
            if not e.degraded and e.extraction_confidence < 0.7
        ]
        score -= len(low_confidence_extractions) * _PENALTY_PARTIAL_EXTRACTION

        # Fraud signals (even if not requiring manual review, they reduce confidence)
        if fraud_result.signals and not fraud_result.requires_manual_review:
            score -= _PENALTY_FRAUD_SIGNALS

        return max(0.0, min(1.0, score))

    def _finalize_line_items(
        self,
        submission: ClaimSubmission,
        line_item_decisions: List[LineItemDecision],
        breakdown: Optional[FinancialBreakdown],
        decision: DecisionType,
    ) -> List[LineItemDecision]:
        if line_item_decisions:
            return line_item_decisions

        # For non-itemized claims, return a single summary line
        if decision in (DecisionType.APPROVED, DecisionType.PARTIAL) and breakdown:
            return [LineItemDecision(
                description=f"{submission.claim_category.value.replace('_', ' ').title()} Claim",
                claimed_amount=breakdown.claimed_amount,
                approved_amount=breakdown.approved_amount,
                covered=True,
            )]

        return []
