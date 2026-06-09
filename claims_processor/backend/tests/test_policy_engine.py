"""
Tests for the deterministic policy engine.
Each test corresponds to one or more of the 12 test cases.
"""
from __future__ import annotations

from datetime import date
from typing import List

import pytest

from core.models import (
    ClaimCategory,
    ClaimSubmission,
    Document,
    DocumentType,
    ExtractedDocument,
    ExtractedField,
    RejectionReason,
)
from core.trace import TraceBuilder


def _make_submission(**kwargs) -> ClaimSubmission:
    defaults = dict(
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category=ClaimCategory.CONSULTATION,
        treatment_date=date(2024, 11, 1),
        claimed_amount=1500.0,
        documents=[Document(file_id="F001", actual_type=DocumentType.PRESCRIPTION)],
    )
    defaults.update(kwargs)
    return ClaimSubmission(**defaults)


def _make_extraction(**kwargs) -> ExtractedDocument:
    defaults = dict(
        file_id="F001",
        document_type=DocumentType.PRESCRIPTION,
        diagnosis=ExtractedField(value="Viral Fever"),
    )
    defaults.update(kwargs)
    return ExtractedDocument(**defaults)


class TestMemberEligibility:
    def test_valid_member_passes(self, policy_engine, trace):
        sub = _make_submission(member_id="EMP001")
        checks, rejections, breakdown, _, _ = policy_engine.evaluate(sub, [], trace)
        assert RejectionReason.MEMBER_NOT_FOUND not in rejections

    def test_unknown_member_rejected(self, policy_engine, trace):
        sub = _make_submission(member_id="UNKNOWN999")
        _, rejections, _, _, _ = policy_engine.evaluate(sub, [], trace)
        assert RejectionReason.MEMBER_NOT_FOUND in rejections


class TestWaitingPeriods:
    def test_initial_waiting_period_blocks_early_claim(self, policy_engine, trace):
        # EMP001 joined 2024-04-01; treatment 10 days later is within 30-day initial wait
        sub = _make_submission(
            member_id="EMP001",
            treatment_date=date(2024, 4, 10),
        )
        _, rejections, _, eligibility_date, _ = policy_engine.evaluate(sub, [], trace)
        assert RejectionReason.WAITING_PERIOD in rejections
        assert eligibility_date == date(2024, 5, 1)

    def test_diabetes_waiting_period_tc005(self, policy_engine, trace):
        # TC005: EMP005 joined 2024-09-01, diabetes claim on 2024-10-15 (44 days < 90)
        ext = _make_extraction(diagnosis=ExtractedField(value="Type 2 Diabetes Mellitus"))
        sub = _make_submission(
            member_id="EMP005",
            treatment_date=date(2024, 10, 15),
            claimed_amount=3000.0,
        )
        _, rejections, _, eligibility_date, _ = policy_engine.evaluate(sub, [ext], trace)
        assert RejectionReason.WAITING_PERIOD in rejections
        from datetime import date as d, timedelta
        assert eligibility_date == date(2024, 9, 1) + timedelta(days=90)  # 2024-11-30

    def test_diabetes_after_waiting_period_passes(self, policy_engine, trace):
        ext = _make_extraction(diagnosis=ExtractedField(value="Type 2 Diabetes Mellitus"))
        sub = _make_submission(
            member_id="EMP005",
            treatment_date=date(2025, 1, 15),  # well after 90-day wait
            claimed_amount=1500.0,
        )
        _, rejections, _, _, _ = policy_engine.evaluate(sub, [ext], trace)
        assert RejectionReason.WAITING_PERIOD not in rejections


class TestExclusions:
    def test_bariatric_excluded_tc012(self, policy_engine, trace):
        ext = _make_extraction(
            diagnosis=ExtractedField(value="Morbid Obesity — BMI 37"),
            treatment=ExtractedField(value="Bariatric Consultation"),
        )
        sub = _make_submission(
            member_id="EMP009",
            treatment_date=date(2024, 10, 18),
            claimed_amount=8000.0,
        )
        _, rejections, _, _, _ = policy_engine.evaluate(sub, [ext], trace)
        assert RejectionReason.EXCLUDED_CONDITION in rejections

    def test_viral_fever_not_excluded(self, policy_engine, trace):
        ext = _make_extraction(diagnosis=ExtractedField(value="Viral Fever"))
        sub = _make_submission()
        _, rejections, _, _, _ = policy_engine.evaluate(sub, [ext], trace)
        assert RejectionReason.EXCLUDED_CONDITION not in rejections


class TestPreAuthorization:
    def test_mri_above_threshold_requires_pre_auth_tc007(self, policy_engine, trace):
        ext = _make_extraction(
            file_id="F012",
            document_type=DocumentType.PRESCRIPTION,
            tests_ordered=["MRI Lumbar Spine"],
        )
        sub = _make_submission(
            member_id="EMP007",
            claim_category=ClaimCategory.DIAGNOSTIC,
            treatment_date=date(2024, 11, 2),
            claimed_amount=15000.0,
        )
        _, rejections, _, _, _ = policy_engine.evaluate(sub, [ext], trace)
        assert RejectionReason.PRE_AUTH_MISSING in rejections

    def test_mri_below_threshold_does_not_require_pre_auth(self, policy_engine, trace):
        ext = _make_extraction(
            file_id="F012",
            document_type=DocumentType.PRESCRIPTION,
            tests_ordered=["MRI Lumbar Spine"],
        )
        sub = _make_submission(
            member_id="EMP007",
            claim_category=ClaimCategory.DIAGNOSTIC,
            claimed_amount=8000.0,  # under ₹10,000 threshold
        )
        _, rejections, _, _, _ = policy_engine.evaluate(sub, [ext], trace)
        assert RejectionReason.PRE_AUTH_MISSING not in rejections


class TestFinancialCalculations:
    def test_per_claim_limit_tc008(self, policy_engine, trace):
        sub = _make_submission(claimed_amount=7500.0)
        _, rejections, _, _, _ = policy_engine.evaluate(sub, [], trace)
        assert RejectionReason.PER_CLAIM_EXCEEDED in rejections

    def test_clean_consultation_approval_tc004(self, policy_engine, trace):
        ext = _make_extraction(diagnosis=ExtractedField(value="Viral Fever"))
        sub = _make_submission(
            claimed_amount=1500.0,
            treatment_date=date(2024, 11, 1),
            ytd_claims_amount=5000.0,
        )
        _, rejections, breakdown, _, _ = policy_engine.evaluate(sub, [ext], trace)
        assert not rejections
        assert breakdown is not None
        assert abs(breakdown.approved_amount - 1350.0) < 0.01  # 10% copay
        assert abs(breakdown.copay_amount - 150.0) < 0.01

    def test_network_discount_applied_before_copay_tc010(self, policy_engine, trace):
        ext = _make_extraction(diagnosis=ExtractedField(value="Acute Bronchitis"))
        sub = _make_submission(
            member_id="EMP010",
            claimed_amount=4500.0,
            hospital_name="Apollo Hospitals",
            treatment_date=date(2024, 11, 3),
            ytd_claims_amount=8000.0,
        )
        _, rejections, breakdown, _, _ = policy_engine.evaluate(sub, [ext], trace)
        assert not rejections
        assert breakdown is not None
        # Network discount 20%: 4500 * 0.8 = 3600
        # Copay 10%: 3600 * 0.9 = 3240
        assert abs(breakdown.network_discount_amount - 900.0) < 0.01
        assert abs(breakdown.copay_amount - 360.0) < 0.01
        assert abs(breakdown.approved_amount - 3240.0) < 0.01


class TestDentalLineItems:
    def test_dental_partial_approval_tc006(self, policy_engine, trace):
        ext = ExtractedDocument(
            file_id="F011",
            document_type=DocumentType.HOSPITAL_BILL,
            line_items=[
                {"description": "Root Canal Treatment", "amount": 8000.0},
                {"description": "Teeth Whitening", "amount": 4000.0},
            ],
            total_amount=12000.0,
        )
        sub = _make_submission(
            member_id="EMP002",
            claim_category=ClaimCategory.DENTAL,
            treatment_date=date(2024, 10, 15),
            claimed_amount=12000.0,
        )
        line_items = policy_engine.evaluate_line_items(sub, [ext], trace)
        covered = [i for i in line_items if i.covered]
        excluded = [i for i in line_items if not i.covered]
        assert len(covered) == 1
        assert covered[0].description == "Root Canal Treatment"
        assert covered[0].approved_amount == 8000.0
        assert len(excluded) == 1
        assert excluded[0].description == "Teeth Whitening"
        assert excluded[0].approved_amount == 0.0
