"""
Shared fixtures for the test suite.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add backend/ to sys.path so `from core.models import ...` works in tests
sys.path.insert(0, str(Path(__file__).parent.parent))

POLICY_PATH = Path(__file__).parent.parent.parent.parent / "policy_terms.json"


@pytest.fixture
def policy_engine():
    from core.policy_engine import PolicyEngine
    return PolicyEngine(POLICY_PATH)


@pytest.fixture
def pipeline():
    from core.pipeline import ClaimsPipeline
    return ClaimsPipeline(POLICY_PATH)


@pytest.fixture
def trace():
    from core.trace import TraceBuilder
    return TraceBuilder()
