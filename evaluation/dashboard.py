"""Offline evaluation dashboard query and public drill-down contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from evaluation.metrics.statistics import (
    ConfidenceInterval,
    bootstrap_mean_ci,
    paired_bootstrap_delta,
    percentile,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DashboardStep(_StrictModel):
    title: str = Field(min_length=1)
    status: str = Field(min_length=1)


class DashboardAction(_StrictModel):
    name: str = Field(min_length=1)
    status: str = Field(min_length=1)


class DashboardObservation(_StrictModel):
    code: str = Field(min_length=1)
    status: str = Field(min_length=1)


class DashboardCitation(_StrictModel):
    evidence_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    page: int = Field(ge=1)
    section: str | None = None


class PublicTraceEvent(_StrictModel):
    kind: str = Field(min_length=1)
    title: str = Field(min_length=1)
    status: str = Field(min_length=1)


class DashboardCase(_StrictModel):
    report_version: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    system_id: str = Field(min_length=1)
    task_family: str = Field(min_length=1)
    difficulty: str = Field(min_length=1)
    language: Literal["zh", "en", "mixed"]
    model: str = Field(min_length=1)
    error_category: str | None = None
    task_success: bool
    claim_support: float | None = Field(default=None, ge=0, le=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    four_b_calls: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    monetary_cost: float = Field(ge=0)
    plan: list[DashboardStep] = Field(default_factory=list)
    actions: list[DashboardAction] = Field(default_factory=list)
    observations: list[DashboardObservation] = Field(default_factory=list)
    citations: list[DashboardCitation] = Field(default_factory=list)
    public_trace: list[PublicTraceEvent] = Field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class DashboardFilters(_StrictModel):
    task_family: str | None = None
    difficulty: str | None = None
    language: Literal["zh", "en", "mixed"] | None = None
    model: str | None = None
    error_category: str | None = None
    system_id: str | None = None


class DashboardMetric(_StrictModel):
    value: float | None
    numerator: float | None
    denominator: int
    unit: str
    confidence_interval: ConfidenceInterval | None = None
    case_ids: list[str]


class DashboardResponse(_StrictModel):
    report_versions: list[str]
    filters: DashboardFilters
    row_count: int
    case_ids: list[str]
    metrics: dict[str, DashboardMetric]


class DashboardComparison(_StrictModel):
    baseline_id: str
    candidate_id: str
    paired_case_count: int
    task_success_delta: ConfidenceInterval
    claim_support_delta: ConfidenceInterval | None


class OfflineEvaluationDashboard:
    """In-memory read model derived only from versioned offline report rows."""

    def __init__(self, rows: list[DashboardCase]) -> None:
        keys = [(item.system_id, item.case_id) for item in rows]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate system/case dashboard row")
        self._rows = list(rows)
        self._by_key = {(item.system_id, item.case_id): item for item in rows}

    @classmethod
    def from_jsonl(cls, path: Path) -> OfflineEvaluationDashboard:
        return cls(
            [
                DashboardCase.model_validate_json(line)
                for line in path.read_text("utf-8").splitlines()
                if line.strip()
            ]
        )

    def query(self, filters: DashboardFilters) -> DashboardResponse:
        rows = [item for item in self._rows if _matches(item, filters)]
        case_ids = [item.case_id for item in rows]
        if not rows:
            return DashboardResponse(
                report_versions=[],
                filters=filters,
                row_count=0,
                case_ids=[],
                metrics={},
            )
        successes = [float(item.task_success) for item in rows]
        supported = [item for item in rows if item.claim_support is not None]
        total_tokens = [float(item.total_tokens) for item in rows]
        model_call_count = sum(item.model_calls for item in rows)
        four_b_count = sum(item.four_b_calls for item in rows)
        successful_count = sum(item.task_success for item in rows)
        costs = sum(item.monetary_cost for item in rows)
        metrics = {
            "task_success": DashboardMetric(
                value=sum(successes) / len(rows),
                numerator=sum(successes),
                denominator=len(rows),
                unit="ratio",
                confidence_interval=bootstrap_mean_ci(successes, samples=300, seed=202603),
                case_ids=case_ids,
            ),
            "claim_support": DashboardMetric(
                value=(
                    sum(item.claim_support or 0.0 for item in supported) / len(supported)
                    if supported
                    else None
                ),
                numerator=(
                    sum(item.claim_support or 0.0 for item in supported)
                    if supported
                    else None
                ),
                denominator=len(supported),
                unit="ratio",
                confidence_interval=(
                    bootstrap_mean_ci(
                        [float(item.claim_support) for item in supported if item.claim_support is not None],
                        samples=300,
                        seed=202604,
                    )
                    if supported
                    else None
                ),
                case_ids=[item.case_id for item in supported],
            ),
            "total_tokens": DashboardMetric(
                value=sum(total_tokens) / len(rows),
                numerator=sum(total_tokens),
                denominator=len(rows),
                unit="mean_tokens_per_case",
                case_ids=case_ids,
            ),
            "four_b_call_rate": DashboardMetric(
                value=four_b_count / model_call_count if model_call_count else None,
                numerator=float(four_b_count),
                denominator=model_call_count,
                unit="ratio_of_model_calls",
                case_ids=case_ids,
            ),
            "p95_latency_ms": DashboardMetric(
                value=percentile([float(item.latency_ms) for item in rows], 0.95),
                numerator=None,
                denominator=len(rows),
                unit="milliseconds",
                case_ids=case_ids,
            ),
            "cost_per_success": DashboardMetric(
                value=costs / successful_count if successful_count else None,
                numerator=costs,
                denominator=successful_count,
                unit="local_monetary_cost_per_success",
                case_ids=case_ids,
            ),
        }
        return DashboardResponse(
            report_versions=sorted({item.report_version for item in rows}),
            filters=filters,
            row_count=len(rows),
            case_ids=case_ids,
            metrics=metrics,
        )

    def compare(self, baseline_id: str, candidate_id: str) -> DashboardComparison:
        baseline = {
            item.case_id: item for item in self._rows if item.system_id == baseline_id
        }
        candidate = {
            item.case_id: item for item in self._rows if item.system_id == candidate_id
        }
        paired_ids = sorted(set(baseline) & set(candidate))
        if not paired_ids:
            raise ValueError("comparison requires paired cases")
        support_ids = [
            case_id
            for case_id in paired_ids
            if baseline[case_id].claim_support is not None
            and candidate[case_id].claim_support is not None
        ]
        return DashboardComparison(
            baseline_id=baseline_id,
            candidate_id=candidate_id,
            paired_case_count=len(paired_ids),
            task_success_delta=paired_bootstrap_delta(
                [float(candidate[case_id].task_success) for case_id in paired_ids],
                [float(baseline[case_id].task_success) for case_id in paired_ids],
                samples=300,
                seed=202605,
            ),
            claim_support_delta=(
                paired_bootstrap_delta(
                    [cast(float, candidate[case_id].claim_support) for case_id in support_ids],
                    [cast(float, baseline[case_id].claim_support) for case_id in support_ids],
                    samples=300,
                    seed=202606,
                )
                if support_ids
                else None
            ),
        )

    def case_detail(self, case_id: str, system_id: str) -> DashboardCase:
        try:
            return self._by_key[(system_id, case_id)]
        except KeyError as exc:
            raise KeyError(f"dashboard case not found: {system_id}/{case_id}") from exc


def _matches(item: DashboardCase, filters: DashboardFilters) -> bool:
    for field in (
        "task_family",
        "difficulty",
        "language",
        "model",
        "error_category",
        "system_id",
    ):
        expected = getattr(filters, field)
        if expected is not None and getattr(item, field) != expected:
            return False
    return True
