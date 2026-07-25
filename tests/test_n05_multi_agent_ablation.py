from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from evaluation.n05_multi_agent_ablation import N05CaseScore, build_n05_report


def _row(
    case_id: str,
    system_id: str,
    *,
    success: bool,
    support: float,
    tokens: int,
    unsupported: float | None = None,
    conflict_recall: float | None = None,
) -> N05CaseScore:
    return N05CaseScore(
        case_id=case_id,
        system_id=system_id,
        task_success=success,
        claim_support_rate=support,
        omission_rate=1 - support,
        total_tokens=tokens,
        latency_ms=100,
        severe_unsupported_rate=unsupported,
        conflict_recall=conflict_recall,
    )


def test_report_fails_closed_when_frozen_dataset_has_no_conflict_gold() -> None:
    rows = []
    for index in range(20):
        case_id = f"case-{index}"
        rows.append(
            _row(case_id, "single_agent", success=index < 10, support=0.50, tokens=100)
        )
        for system in ("reader_parallel", "evidence", "critic", "verifier"):
            rows.append(
                _row(case_id, system, success=index < 11, support=0.55, tokens=110)
            )
        rows.append(
            _row(
                case_id,
                "full_system",
                success=index < 13,
                support=0.65,
                tokens=130,
                unsupported=0.01,
            )
        )
    report = build_n05_report(rows, truth_class="offline_real_model")
    assert report["matrix_complete"]
    assert report["metrics"]["claim_support_delta"] == pytest.approx(0.15)
    assert report["gates"]["claim_support_gain"]
    assert report["gates"]["token_increase_within_limit"]
    assert not report["gates"]["conflict_recall_gain"]
    assert not report["gates"]["severe_unsupported_reduction"]
    assert not report["all_gates_passed"]
    assert "unavailable" in report["limitations"][0].casefold()


def test_no_go_policy_keeps_multi_agent_off_the_default_path() -> None:
    policy = yaml.safe_load(Path("backend/subagents/promotion_policy.yaml").read_text("utf-8"))
    assert policy["production_default"] == "single_agent"
    assert policy["multi_agent_enabled_by_default"] is False
    assert policy["roles"]["critic"] == "experimental_only"
    assert (
        policy["roles"]["verifier"]
        == "experimental_only_with_deterministic_boundary"
    )
    assert policy["full_revision_enabled"] is False
    assert policy["experimental_full_revision_max_rounds"] == 1
