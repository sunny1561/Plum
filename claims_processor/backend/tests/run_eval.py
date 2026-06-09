"""
Evaluation runner for all 12 test cases.

Usage:
    cd claims_processor/backend
    python -m tests.run_eval

Runs every test case through the pipeline synchronously and prints a
pass/fail report with the full decision output.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.routes import _build_submission_from_test_case, _check_test_outcome
from core.pipeline import ClaimsPipeline

POLICY_PATH = Path(__file__).parent.parent.parent.parent / "policy_terms.json"
TC_PATH = Path(__file__).parent.parent.parent.parent / "test_cases.json"

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


async def _run_all() -> None:
    pipeline = ClaimsPipeline(POLICY_PATH)

    with open(TC_PATH) as f:
        tc_data = json.load(f)

    cases = tc_data["test_cases"]
    results: List[Dict[str, Any]] = []

    print(f"\n{BOLD}{'=' * 70}")
    print("  Plum Claims Processing — Evaluation Report")
    print(f"{'=' * 70}{RESET}\n")

    for case in cases:
        case_id = case["case_id"]
        case_name = case["case_name"]
        expected = case["expected"]

        try:
            submission = _build_submission_from_test_case(case)
            result = await pipeline.process(submission)
            result_dict = result.model_dump(mode="json")
            passed = _check_test_outcome(expected, result_dict)
            error = None
        except Exception as exc:
            result_dict = {"error": str(exc)}
            passed = False
            error = str(exc)

        results.append({
            "case_id": case_id,
            "case_name": case_name,
            "passed": passed,
            "expected": expected,
            "result": result_dict,
            "error": error,
        })

        status_icon = f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"
        print(f"{status_icon}  {BOLD}{case_id}{RESET}: {case_name}")

        # Print key result fields
        if error:
            print(f"     {RED}ERROR: {error}{RESET}")
        else:
            status = result_dict.get("status", "?")
            decision = result_dict.get("decision", "N/A")
            approved = result_dict.get("approved_amount", 0)
            confidence = result_dict.get("confidence_score", 0)

            if status == "VALIDATION_FAILED":
                errors = result_dict.get("errors", [])
                print(f"     Status: VALIDATION_FAILED")
                for err in errors:
                    print(f"     ↳ {YELLOW}{err[:100]}...{RESET}" if len(err) > 100 else f"     ↳ {err}")
            else:
                print(f"     Decision: {_colorize_decision(decision)} | "
                      f"Approved: ₹{approved:,.2f} | Confidence: {confidence:.2f}")

                # Show financial breakdown if available
                bd = result_dict.get("financial_breakdown")
                if bd and bd.get("network_discount_amount", 0) > 0:
                    print(f"     Breakdown: ₹{bd['claimed_amount']:,.2f} "
                          f"→ -{bd['network_discount_amount']:.2f} (network) "
                          f"→ -{bd['copay_amount']:.2f} (copay) "
                          f"→ ₹{bd['approved_amount']:.2f}")

            # Expected vs actual
            exp_decision = expected.get("decision")
            if exp_decision != decision and exp_decision is not None:
                print(f"     {RED}Expected: {exp_decision} | Got: {decision}{RESET}")

            # Show degraded components
            degraded = result_dict.get("degraded_components", [])
            if degraded:
                print(f"     {YELLOW}⚠ Degraded: {', '.join(degraded)}{RESET}")

        print()

    # Summary
    total = len(results)
    passing = sum(1 for r in results if r["passed"])
    failing = total - passing

    print(f"{BOLD}{'=' * 70}")
    print(f"  Summary: {GREEN}{passing}{RESET}/{total} passing  |  "
          f"{RED if failing else GREEN}{failing}{RESET} failing")
    print(f"{'=' * 70}{RESET}\n")

    if failing > 0:
        print(f"{BOLD}Failing cases:{RESET}")
        for r in results:
            if not r["passed"]:
                print(f"  • {r['case_id']}: {r['case_name']}")
        print()

    # Write full JSON report
    report_path = Path(__file__).parent.parent / "eval_output.json"
    with open(report_path, "w") as f:
        json.dump({
            "summary": {"total": total, "passing": passing, "failing": failing},
            "cases": results,
        }, f, indent=2, default=str)
    print(f"Full report written to: {report_path}")


def _colorize_decision(decision: str) -> str:
    colors = {
        "APPROVED": GREEN,
        "PARTIAL": YELLOW,
        "REJECTED": RED,
        "MANUAL_REVIEW": YELLOW,
    }
    color = colors.get(decision, RESET)
    return f"{color}{decision}{RESET}"


if __name__ == "__main__":
    asyncio.run(_run_all())
