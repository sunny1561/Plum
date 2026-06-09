"""
Tests for individual agents — validator, extractor, fraud detector.
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from core.models import (
    ClaimCategory,
    ClaimSubmission,
    Document,
    DocumentQuality,
    DocumentType,
)
from core.trace import TraceBuilder


def _doc(**kwargs) -> Document:
    defaults = {"file_id": "F001", "actual_type": DocumentType.PRESCRIPTION}
    defaults.update(kwargs)
    return Document(**defaults)


def _submission(**kwargs) -> ClaimSubmission:
    defaults = dict(
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category=ClaimCategory.CONSULTATION,
        treatment_date=date(2024, 11, 1),
        claimed_amount=1500.0,
        documents=[
            _doc(file_id="F001", actual_type=DocumentType.PRESCRIPTION),
            _doc(file_id="F002", actual_type=DocumentType.HOSPITAL_BILL),
        ],
    )
    defaults.update(kwargs)
    return ClaimSubmission(**defaults)


class TestDocumentValidator:
    def test_valid_consultation_passes(self, policy_engine, trace):
        from agents.document_validator import DocumentValidatorAgent
        from core.pipeline import ClaimsPipeline

        reqs = {cat.value: policy_engine.get_document_requirements(cat)
                for cat in ClaimCategory}
        validator = DocumentValidatorAgent(reqs)

        sub = _submission()
        result = validator.validate(sub, trace)
        assert result.passed
        assert not result.has_blocking_issues

    def test_missing_hospital_bill_blocks_tc001(self, policy_engine, trace):
        from agents.document_validator import DocumentValidatorAgent

        reqs = {cat.value: policy_engine.get_document_requirements(cat)
                for cat in ClaimCategory}
        validator = DocumentValidatorAgent(reqs)

        sub = _submission(documents=[
            _doc(file_id="F001", actual_type=DocumentType.PRESCRIPTION),
            _doc(file_id="F002", actual_type=DocumentType.PRESCRIPTION),
        ])
        result = validator.validate(sub, trace)
        assert result.has_blocking_issues
        msgs = " ".join(result.blocking_messages)
        assert "HOSPITAL_BILL" in msgs
        assert "PRESCRIPTION" in msgs

    def test_unreadable_document_blocks_tc002(self, policy_engine, trace):
        from agents.document_validator import DocumentValidatorAgent

        reqs = {cat.value: policy_engine.get_document_requirements(cat)
                for cat in ClaimCategory}
        validator = DocumentValidatorAgent(reqs)

        sub = _submission(
            claim_category=ClaimCategory.PHARMACY,
            documents=[
                _doc(file_id="F003", actual_type=DocumentType.PRESCRIPTION, quality=DocumentQuality.GOOD),
                _doc(file_id="F004", actual_type=DocumentType.PHARMACY_BILL,
                     quality=DocumentQuality.UNREADABLE, file_name="blurry_bill.jpg"),
            ],
        )
        result = validator.validate(sub, trace)
        assert result.has_blocking_issues
        msgs = " ".join(result.blocking_messages)
        assert "re-upload" in msgs.lower()

    def test_patient_name_mismatch_blocks_tc003(self, policy_engine, trace):
        from agents.document_validator import DocumentValidatorAgent

        reqs = {cat.value: policy_engine.get_document_requirements(cat)
                for cat in ClaimCategory}
        validator = DocumentValidatorAgent(reqs)

        sub = _submission(documents=[
            _doc(file_id="F005", actual_type=DocumentType.PRESCRIPTION,
                 patient_name_on_doc="Rajesh Kumar"),
            _doc(file_id="F006", actual_type=DocumentType.HOSPITAL_BILL,
                 patient_name_on_doc="Arjun Mehta"),
        ])
        result = validator.validate(sub, trace)
        assert result.has_blocking_issues
        msgs = " ".join(result.blocking_messages)
        assert "Rajesh Kumar" in msgs
        assert "Arjun Mehta" in msgs


class TestDocumentExtractor:
    def test_structured_content_extracted_correctly(self, trace):
        from agents.document_extractor import DocumentExtractorAgent

        extractor = DocumentExtractorAgent()
        doc = Document(
            file_id="F007",
            actual_type=DocumentType.PRESCRIPTION,
            content={
                "doctor_name": "Dr. Arun Sharma",
                "patient_name": "Rajesh Kumar",
                "diagnosis": "Viral Fever",
                "medicines": ["Paracetamol 650mg"],
            },
        )
        sub = _submission(documents=[doc])
        results = asyncio.get_event_loop().run_until_complete(
            extractor.extract_all(sub, trace)
        )
        assert len(results) == 1
        ext = results[0]
        assert ext.patient_name.value == "Rajesh Kumar"
        assert ext.diagnosis.value == "Viral Fever"
        assert ext.extraction_confidence == 1.0
        assert not ext.degraded

    def test_missing_content_returns_degraded(self, trace):
        from agents.document_extractor import DocumentExtractorAgent

        extractor = DocumentExtractorAgent()
        doc = Document(file_id="F_EMPTY", actual_type=DocumentType.PRESCRIPTION)
        sub = _submission(documents=[doc])
        results = asyncio.get_event_loop().run_until_complete(
            extractor.extract_all(sub, trace)
        )
        assert results[0].degraded
        assert results[0].extraction_confidence < 1.0


class TestFraudDetector:
    def test_multiple_same_day_claims_triggers_review_tc009(self, trace):
        from agents.fraud_detector import FraudDetectorAgent

        detector = FraudDetectorAgent({"same_day_claims_limit": 2, "high_value_claim_threshold": 25000,
                                        "fraud_score_manual_review_threshold": 0.80,
                                        "auto_manual_review_above": 25000})
        sub = _submission(
            member_id="EMP008",
            treatment_date=date(2024, 10, 30),
            claimed_amount=4800.0,
            claims_history=[
                {"claim_id": "CLM_0081", "date": "2024-10-30", "amount": 1200, "provider": "City Clinic A"},
                {"claim_id": "CLM_0082", "date": "2024-10-30", "amount": 1800, "provider": "City Clinic B"},
                {"claim_id": "CLM_0083", "date": "2024-10-30", "amount": 2100, "provider": "Wellness Center"},
            ],
        )
        result = asyncio.get_event_loop().run_until_complete(
            detector.analyze(sub, [], trace)
        )
        assert result.requires_manual_review
        signal_types = [s.signal_type for s in result.signals]
        assert "EXCESSIVE_SAME_DAY_CLAIMS" in signal_types

    def test_simulate_failure_raises_exception(self, trace):
        from agents.fraud_detector import FraudDetectorAgent

        detector = FraudDetectorAgent({})
        sub = _submission(simulate_component_failure=True)
        with pytest.raises(RuntimeError, match="Simulated"):
            asyncio.get_event_loop().run_until_complete(
                detector.analyze(sub, [], trace)
            )

    def test_normal_claim_has_no_fraud_signals(self, trace):
        from agents.fraud_detector import FraudDetectorAgent

        detector = FraudDetectorAgent({"same_day_claims_limit": 2, "high_value_claim_threshold": 25000,
                                        "fraud_score_manual_review_threshold": 0.80,
                                        "auto_manual_review_above": 25000})
        sub = _submission(claimed_amount=1500.0, claims_history=[])
        result = asyncio.get_event_loop().run_until_complete(
            detector.analyze(sub, [], trace)
        )
        assert not result.requires_manual_review
        assert len(result.signals) == 0
