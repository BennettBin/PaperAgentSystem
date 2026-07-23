"""Compute unified L03 metrics and paired baseline comparisons."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from evaluation.metrics.catalog import CORE_METRICS, MetricName
from evaluation.metrics.statistics import (
    ConfidenceInterval,
    bootstrap_statistic_ci,
    paired_bootstrap_statistic_delta,
    percentile,
)


class CaseMetricRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    task_success: bool
    answer_correctness: float | None = Field(default=None, ge=0, le=1)
    citation_true_positive: int = Field(default=0, ge=0)
    citation_false_positive: int = Field(default=0, ge=0)
    citation_false_negative: int = Field(default=0, ge=0)
    supported_claims: int = Field(default=0, ge=0)
    total_claims: int = Field(default=0, ge=0)
    hallucinated_claims: int = Field(default=0, ge=0)
    intent_rank: int | None = Field(default=None, ge=1)
    skill_rank: int | None = Field(default=None, ge=1)
    expected_tools: list[str] = Field(default_factory=list)
    selected_tools: list[str] = Field(default_factory=list)
    argument_exact: bool | None = None
    argument_schema_valid: bool | None = None
    plan_valid: bool | None = None
    required_steps_matched: int = Field(default=0, ge=0)
    required_steps_total: int = Field(default=0, ge=0)
    invalid_steps: int = Field(default=0, ge=0)
    total_steps: int = Field(default=0, ge=0)
    successful_tool_calls: int = Field(default=0, ge=0)
    total_tool_calls: int = Field(default=0, ge=0)
    replan_attempted: bool = False
    replan_succeeded: bool | None = None
    loop_detected: bool = False
    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    latency_ms: float = Field(ge=0)
    four_b_calls: int = Field(default=0, ge=0)
    total_model_calls: int = Field(default=0, ge=0)
    gpu_seconds: float | None = Field(default=None, ge=0)
    monetary_cost: float | None = Field(default=None, ge=0)
    recovery_attempted: bool = False
    recovery_succeeded: bool | None = None
    partial_failure_case: bool = False
    partial_result_usable: bool | None = None
    cancellation_case: bool = False
    cancellation_response_ms: float | None = Field(default=None, ge=0)
    prompt_injection_case: bool = False
    prompt_injection_blocked: bool | None = None


class MetricValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float
    numerator: float
    denominator: int
    excluded_cases: int
    ci: ConfidenceInterval


class MetricsReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    case_count: int
    metrics: dict[MetricName, MetricValue]


class MetricComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    absolute: float
    baseline: float
    delta: float
    absolute_ci: ConfidenceInterval
    baseline_ci: ConfidenceInterval
    delta_ci: ConfidenceInterval


class MetricsComparisonReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    baseline_id: str
    candidate_id: str
    paired_case_count: int
    metrics: dict[MetricName, MetricComparison]


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _tool_f1(expected: list[str], selected: list[str]) -> float | None:
    if not expected and not selected:
        return None
    expected_set = set(expected)
    selected_set = set(selected)
    true_positive = len(expected_set & selected_set)
    if not true_positive:
        return 0.0
    precision = true_positive / len(selected_set)
    recall = true_positive / len(expected_set)
    return 2 * precision * recall / (precision + recall)


class MetricsEngine:
    def __init__(self, *, seed: int = 0, bootstrap_samples: int = 2000) -> None:
        self._seed = seed
        self._bootstrap_samples = bootstrap_samples

    def _case_value(self, record: CaseMetricRecord, metric: MetricName) -> float | None:
        mapping: dict[MetricName, Any] = {
            MetricName.TASK_SUCCESS: float(record.task_success),
            MetricName.ANSWER_CORRECTNESS: record.answer_correctness,
            MetricName.CITATION_PRECISION: _ratio(record.citation_true_positive, record.citation_true_positive + record.citation_false_positive),
            MetricName.CITATION_RECALL: _ratio(record.citation_true_positive, record.citation_true_positive + record.citation_false_negative),
            MetricName.CLAIM_SUPPORT_RATE: _ratio(record.supported_claims, record.total_claims),
            MetricName.HALLUCINATION_RATE: _ratio(record.hallucinated_claims, record.total_claims),
            MetricName.INTENT_TOP1: None if record.intent_rank is None else float(record.intent_rank <= 1),
            MetricName.INTENT_TOP3: None if record.intent_rank is None else float(record.intent_rank <= 3),
            MetricName.SKILL_TOP1: None if record.skill_rank is None else float(record.skill_rank <= 1),
            MetricName.SKILL_TOP3: None if record.skill_rank is None else float(record.skill_rank <= 3),
            MetricName.TOOL_SELECTION_F1: _tool_f1(record.expected_tools, record.selected_tools),
            MetricName.ARGUMENT_EXACT_RATE: None if record.argument_exact is None else float(record.argument_exact),
            MetricName.ARGUMENT_SCHEMA_VALID_RATE: None if record.argument_schema_valid is None else float(record.argument_schema_valid),
            MetricName.PLAN_VALIDITY: None if record.plan_valid is None else float(record.plan_valid),
            MetricName.REQUIRED_STEP_RECALL: _ratio(record.required_steps_matched, record.required_steps_total),
            MetricName.INVALID_STEP_RATE: _ratio(record.invalid_steps, record.total_steps),
            MetricName.TOOL_SUCCESS_RATE: _ratio(record.successful_tool_calls, record.total_tool_calls),
            MetricName.REPLAN_SUCCESS_RATE: None if not record.replan_attempted or record.replan_succeeded is None else float(record.replan_succeeded),
            MetricName.LOOP_RATE: float(record.loop_detected),
            MetricName.MODEL_CALLS: float(record.model_calls),
            MetricName.TOOL_CALLS: float(record.tool_calls),
            MetricName.INPUT_TOKENS: float(record.input_tokens),
            MetricName.OUTPUT_TOKENS: float(record.output_tokens),
            MetricName.LATENCY_P50_MS: record.latency_ms,
            MetricName.LATENCY_P95_MS: record.latency_ms,
            MetricName.TOKENS_PER_SUCCESS: float(record.input_tokens + record.output_tokens) if record.task_success else None,
            MetricName.FOUR_B_CALL_RATE: _ratio(record.four_b_calls, record.total_model_calls),
            MetricName.GPU_SECONDS: record.gpu_seconds,
            MetricName.MONETARY_COST: record.monetary_cost,
            MetricName.FAILURE_RECOVERY_RATE: None if not record.recovery_attempted or record.recovery_succeeded is None else float(record.recovery_succeeded),
            MetricName.PARTIAL_FAILURE_USABILITY: None if not record.partial_failure_case or record.partial_result_usable is None else float(record.partial_result_usable),
            MetricName.CANCELLATION_RESPONSE_MS: record.cancellation_response_ms if record.cancellation_case else None,
            MetricName.PROMPT_INJECTION_BLOCK_RATE: None if not record.prompt_injection_case or record.prompt_injection_blocked is None else float(record.prompt_injection_blocked),
        }
        value = mapping[metric]
        return float(value) if value is not None else None

    def _values(self, records: list[CaseMetricRecord], metric: MetricName) -> list[float]:
        return [value for record in records if (value := self._case_value(record, metric)) is not None]

    def _statistic(self, metric: MetricName) -> Callable[[list[float]], float]:
        if metric is MetricName.LATENCY_P50_MS:
            return lambda values: percentile(values, 0.50)
        if metric is MetricName.LATENCY_P95_MS:
            return lambda values: percentile(values, 0.95)
        return lambda values: sum(values) / len(values)

    def compute(self, records: list[CaseMetricRecord]) -> MetricsReport:
        if not records:
            raise ValueError("metrics require at least one case record")
        metrics: dict[MetricName, MetricValue] = {}
        for offset, metric in enumerate(CORE_METRICS):
            values = self._values(records, metric)
            if not values:
                continue
            statistic = self._statistic(metric)
            ci = bootstrap_statistic_ci(
                values,
                statistic=statistic,
                samples=self._bootstrap_samples,
                seed=self._seed + offset,
            )
            metrics[metric] = MetricValue(
                value=ci.estimate,
                numerator=sum(values),
                denominator=len(values),
                excluded_cases=len(records) - len(values),
                ci=ci,
            )
        return MetricsReport(case_count=len(records), metrics=metrics)

    def compare(
        self,
        candidate: list[CaseMetricRecord],
        baseline: list[CaseMetricRecord],
        *,
        baseline_id: str,
        candidate_id: str,
    ) -> MetricsComparisonReport:
        baseline_by_id = {record.case_id: record for record in baseline}
        candidate_by_id = {record.case_id: record for record in candidate}
        case_ids = sorted(set(baseline_by_id) & set(candidate_by_id))
        if not case_ids:
            raise ValueError("comparison requires paired case IDs")
        metrics: dict[MetricName, MetricComparison] = {}
        for offset, metric in enumerate(CORE_METRICS):
            paired = [
                (
                    self._case_value(candidate_by_id[case_id], metric),
                    self._case_value(baseline_by_id[case_id], metric),
                )
                for case_id in case_ids
            ]
            valid = [(left, right) for left, right in paired if left is not None and right is not None]
            if not valid:
                continue
            candidate_values = [left for left, _ in valid]
            baseline_values = [right for _, right in valid]
            statistic = self._statistic(metric)
            absolute_ci = bootstrap_statistic_ci(candidate_values, statistic=statistic, samples=self._bootstrap_samples, seed=self._seed + offset)
            baseline_ci = bootstrap_statistic_ci(baseline_values, statistic=statistic, samples=self._bootstrap_samples, seed=self._seed + 1000 + offset)
            delta_ci = paired_bootstrap_statistic_delta(candidate_values, baseline_values, statistic=statistic, samples=self._bootstrap_samples, seed=self._seed + 2000 + offset)
            metrics[metric] = MetricComparison(
                absolute=absolute_ci.estimate,
                baseline=baseline_ci.estimate,
                delta=delta_ci.estimate,
                absolute_ci=absolute_ci,
                baseline_ci=baseline_ci,
                delta_ci=delta_ci,
            )
        return MetricsComparisonReport(
            baseline_id=baseline_id,
            candidate_id=candidate_id,
            paired_case_count=len(case_ids),
            metrics=metrics,
        )
