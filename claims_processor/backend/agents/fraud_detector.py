"""
Fraud Detection Agent — Stage 3 of the pipeline.

Evaluates behavioral and document-level signals to compute a fraud score.
Does NOT auto-reject — high scores escalate to MANUAL_REVIEW.
This agent can be intentionally failed via simulate_component_failure to test
pipeline resilience (TC011).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from core.models import (
    ClaimSubmission,
    ExtractedDocument,
    FraudResult,
    FraudSignal,
)
from core.trace import TraceBuilder

COMPONENT = "fraud_detector"

# Mirrors policy fraud_thresholds
_DEFAULT_SAME_DAY_LIMIT = 2
_DEFAULT_HIGH_VALUE_THRESHOLD = 25_000
_DEFAULT_FRAUD_SCORE_REVIEW_THRESHOLD = 0.80


class FraudDetectorAgent:
    """
    Evaluates fraud signals against configurable thresholds from the policy.
    All signals are additive; final score is capped at 1.0.
    """

    def __init__(self, fraud_thresholds: Dict[str, Any]) -> None:
        self._thresholds = fraud_thresholds

    async def analyze(
        self,
        submission: ClaimSubmission,
        extractions: List[ExtractedDocument],
        trace: TraceBuilder,
    ) -> FraudResult:
        if submission.simulate_component_failure:
            raise RuntimeError(
                "Simulated component failure in FraudDetectorAgent (simulate_component_failure=true)"
            )

        trace.info(COMPONENT, "start",
                   f"Analyzing fraud signals for claim {submission.claim_id}")

        signals: List[FraudSignal] = []
        score = 0.0

        # --- Signal 1: Same-day claim frequency ---
        # When the same-day limit is exceeded we treat it as a hard escalation trigger
        # (not just a score contribution), matching the policy's intent for TC009.
        today_str = submission.treatment_date.isoformat()
        same_day = [
            c for c in submission.claims_history
            if str(c.get("date", "")) == today_str
        ]
        limit = self._thresholds.get("same_day_claims_limit", _DEFAULT_SAME_DAY_LIMIT)
        same_day_limit_exceeded = len(same_day) >= limit
        if same_day_limit_exceeded:
            signal_score = 1.0  # guarantees manual review regardless of other scores
            score = max(score, signal_score)
            signals.append(FraudSignal(
                signal_type="EXCESSIVE_SAME_DAY_CLAIMS",
                description=(
                    f"Member has {len(same_day)} prior claim(s) on {today_str}, "
                    f"exceeding the same-day limit of {limit}. "
                    f"Prior claims: {[c.get('claim_id') for c in same_day]}."
                ),
                severity="HIGH",
                data={"existing_count": len(same_day), "limit": limit, "claims": same_day},
            ))
            trace.warn(COMPONENT, "same_day_claims",
                       f"{len(same_day)} existing claims on {today_str} (limit: {limit}) — "
                       f"hard escalation to MANUAL_REVIEW",
                       {"count": len(same_day), "limit": limit})
        else:
            trace.passed(COMPONENT, "same_day_claims",
                         f"{len(same_day)} same-day claim(s) — within limit of {limit}")

        # --- Signal 2: High-value claim ---
        hv_threshold = self._thresholds.get("high_value_claim_threshold", _DEFAULT_HIGH_VALUE_THRESHOLD)
        if submission.claimed_amount > hv_threshold:
            signal_score = 0.20
            score += signal_score
            signals.append(FraudSignal(
                signal_type="HIGH_VALUE_CLAIM",
                description=(
                    f"Claimed amount ₹{submission.claimed_amount:,.0f} exceeds the "
                    f"high-value threshold of ₹{hv_threshold:,.0f}."
                ),
                severity="MEDIUM",
                data={"amount": submission.claimed_amount, "threshold": hv_threshold},
            ))
            trace.warn(COMPONENT, "high_value",
                       f"₹{submission.claimed_amount} > high-value threshold ₹{hv_threshold}")
        else:
            trace.passed(COMPONENT, "high_value",
                         f"Claim amount ₹{submission.claimed_amount} below high-value threshold")

        # --- Signal 3: Document alteration indicators ---
        for ext in extractions:
            for err in ext.extraction_errors:
                if "alteration" in err.lower() or "correction" in err.lower():
                    signal_score = 0.25
                    score += signal_score
                    signals.append(FraudSignal(
                        signal_type="DOCUMENT_ALTERATION_SUSPECTED",
                        description=f"Document {ext.file_id} shows signs of alteration: {err}",
                        severity="HIGH",
                        data={"file_id": ext.file_id},
                    ))
                    trace.warn(COMPONENT, "document_alteration",
                               f"Alteration signal on {ext.file_id}")

        # --- Signal 4: Multiple providers same day ---
        same_day_providers = {c.get("provider") for c in same_day if c.get("provider")}
        if len(same_day_providers) >= 2:
            signal_score = 0.20
            score += signal_score
            signals.append(FraudSignal(
                signal_type="MULTIPLE_PROVIDERS_SAME_DAY",
                description=(
                    f"Claims submitted from {len(same_day_providers)} different providers "
                    f"on the same day: {', '.join(str(p) for p in same_day_providers)}."
                ),
                severity="MEDIUM",
                data={"providers": list(same_day_providers)},
            ))
            trace.warn(COMPONENT, "multiple_providers",
                       f"{len(same_day_providers)} providers on {today_str}")
        else:
            trace.passed(COMPONENT, "multiple_providers",
                         "No multiple-provider same-day pattern detected")

        score = min(score, 1.0)
        review_threshold = self._thresholds.get(
            "fraud_score_manual_review_threshold", _DEFAULT_FRAUD_SCORE_REVIEW_THRESHOLD
        )
        requires_review = score >= review_threshold or (
            submission.claimed_amount > self._thresholds.get("auto_manual_review_above", 25000)
        )

        if signals:
            trace.warn(COMPONENT, "fraud_summary",
                       f"Fraud score: {score:.2f} — {len(signals)} signal(s) detected",
                       {"score": score, "signals": [s.signal_type for s in signals],
                        "requires_manual_review": requires_review})
        else:
            trace.passed(COMPONENT, "fraud_summary",
                         f"No fraud signals detected — score: {score:.2f}")

        return FraudResult(
            fraud_score=score,
            signals=signals,
            requires_manual_review=requires_review,
            degraded=False,
            trace=trace.entries(),
        )
