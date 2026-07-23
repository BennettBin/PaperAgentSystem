"""Authoritative formulas and reporting semantics for every L03 metric."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class MetricCategory(StrEnum):
    EFFECT = "effect"
    ROUTING = "routing"
    TRAJECTORY = "trajectory"
    EFFICIENCY = "efficiency"
    COST = "cost"
    ROBUSTNESS = "robustness"


class MetricDirection(StrEnum):
    HIGHER = "higher_is_better"
    LOWER = "lower_is_better"
    DESCRIPTIVE = "descriptive"


class MetricName(StrEnum):
    TASK_SUCCESS = "task_success"
    ANSWER_CORRECTNESS = "answer_correctness"
    CITATION_PRECISION = "citation_precision"
    CITATION_RECALL = "citation_recall"
    CLAIM_SUPPORT_RATE = "claim_support_rate"
    HALLUCINATION_RATE = "hallucination_rate"
    INTENT_TOP1 = "intent_top1"
    INTENT_TOP3 = "intent_top3"
    SKILL_TOP1 = "skill_top1"
    SKILL_TOP3 = "skill_top3"
    TOOL_SELECTION_F1 = "tool_selection_f1"
    ARGUMENT_EXACT_RATE = "argument_exact_rate"
    ARGUMENT_SCHEMA_VALID_RATE = "argument_schema_valid_rate"
    PLAN_VALIDITY = "plan_validity"
    REQUIRED_STEP_RECALL = "required_step_recall"
    INVALID_STEP_RATE = "invalid_step_rate"
    TOOL_SUCCESS_RATE = "tool_success_rate"
    REPLAN_SUCCESS_RATE = "replan_success_rate"
    LOOP_RATE = "loop_rate"
    MODEL_CALLS = "model_calls"
    TOOL_CALLS = "tool_calls"
    INPUT_TOKENS = "input_tokens"
    OUTPUT_TOKENS = "output_tokens"
    LATENCY_P50_MS = "latency_p50_ms"
    LATENCY_P95_MS = "latency_p95_ms"
    TOKENS_PER_SUCCESS = "tokens_per_success"
    FOUR_B_CALL_RATE = "four_b_call_rate"
    GPU_SECONDS = "gpu_seconds"
    MONETARY_COST = "monetary_cost"
    FAILURE_RECOVERY_RATE = "failure_recovery_rate"
    PARTIAL_FAILURE_USABILITY = "partial_failure_usability"
    CANCELLATION_RESPONSE_MS = "cancellation_response_ms"
    PROMPT_INJECTION_BLOCK_RATE = "prompt_injection_block_rate"


class MetricDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: MetricName
    category: MetricCategory
    direction: MetricDirection
    unit: str = Field(min_length=1)
    formula: str = Field(min_length=1)
    denominator: str = Field(min_length=1)
    applicability: str = Field(min_length=1)
    outlier_handling: str = Field(min_length=1)
    notes: str = Field(min_length=1)


def _metric(
    name: MetricName,
    category: MetricCategory,
    direction: MetricDirection,
    unit: str,
    formula: str,
    denominator: str,
    applicability: str,
    notes: str,
    *,
    outliers: str = "Reject negative/non-finite inputs; retain all valid cases and report bootstrap CI.",
) -> MetricDefinition:
    return MetricDefinition(
        name=name,
        category=category,
        direction=direction,
        unit=unit,
        formula=formula,
        denominator=denominator,
        applicability=applicability,
        outlier_handling=outliers,
        notes=notes,
    )


_RATE_OUTLIERS = "Values are bounded to [0,1]; undefined denominators are excluded and counted."
_LATENCY_OUTLIERS = (
    "Retain timeouts at the configured budget ceiling; reject negative/non-finite values; report P50/P95."
)


CORE_METRICS: dict[MetricName, MetricDefinition] = {
    MetricName.TASK_SUCCESS: _metric(MetricName.TASK_SUCCESS, MetricCategory.EFFECT, MetricDirection.HIGHER, "ratio", "mean(case task_success indicator)", "all executed cases", "all task families", "Requires final task correctness, not merely valid output format.", outliers=_RATE_OUTLIERS),
    MetricName.ANSWER_CORRECTNESS: _metric(MetricName.ANSWER_CORRECTNESS, MetricCategory.EFFECT, MetricDirection.HIGHER, "score", "mean(programmatic/LLM/human correctness score)", "cases with a correctness judgment", "answer-producing cases", "Judge provenance must be retained.", outliers=_RATE_OUTLIERS),
    MetricName.CITATION_PRECISION: _metric(MetricName.CITATION_PRECISION, MetricCategory.EFFECT, MetricDirection.HIGHER, "ratio", "macro mean TP/(TP+FP)", "cases with at least one predicted citation", "citation cases", "Unknown citations are false positives.", outliers=_RATE_OUTLIERS),
    MetricName.CITATION_RECALL: _metric(MetricName.CITATION_RECALL, MetricCategory.EFFECT, MetricDirection.HIGHER, "ratio", "macro mean TP/(TP+FN)", "cases with Gold evidence", "evidence-required cases", "Missing Gold support is a false negative.", outliers=_RATE_OUTLIERS),
    MetricName.CLAIM_SUPPORT_RATE: _metric(MetricName.CLAIM_SUPPORT_RATE, MetricCategory.EFFECT, MetricDirection.HIGHER, "ratio", "macro mean supported_claims/total_claims", "cases emitting factual claims", "factual answer and writing cases", "Claims must map to program-issued Evidence IDs.", outliers=_RATE_OUTLIERS),
    MetricName.HALLUCINATION_RATE: _metric(MetricName.HALLUCINATION_RATE, MetricCategory.EFFECT, MetricDirection.LOWER, "ratio", "macro mean hallucinated_claims/total_claims", "cases emitting factual claims", "factual answer and writing cases", "Unsupported material claims count as hallucinations.", outliers=_RATE_OUTLIERS),
    MetricName.INTENT_TOP1: _metric(MetricName.INTENT_TOP1, MetricCategory.ROUTING, MetricDirection.HIGHER, "ratio", "mean(intent_rank <= 1)", "cases with intent Gold", "routing cases", "No prediction is incorrect.", outliers=_RATE_OUTLIERS),
    MetricName.INTENT_TOP3: _metric(MetricName.INTENT_TOP3, MetricCategory.ROUTING, MetricDirection.HIGHER, "ratio", "mean(intent_rank <= 3)", "cases with intent Gold", "routing cases", "No prediction is incorrect.", outliers=_RATE_OUTLIERS),
    MetricName.SKILL_TOP1: _metric(MetricName.SKILL_TOP1, MetricCategory.ROUTING, MetricDirection.HIGHER, "ratio", "mean(skill_rank <= 1)", "cases with Skill Gold", "Skill routing cases", "Ambiguous cases use the allowed Skill set.", outliers=_RATE_OUTLIERS),
    MetricName.SKILL_TOP3: _metric(MetricName.SKILL_TOP3, MetricCategory.ROUTING, MetricDirection.HIGHER, "ratio", "mean(skill_rank <= 3)", "cases with Skill Gold", "Skill routing cases", "Ambiguous cases use the allowed Skill set.", outliers=_RATE_OUTLIERS),
    MetricName.TOOL_SELECTION_F1: _metric(MetricName.TOOL_SELECTION_F1, MetricCategory.ROUTING, MetricDirection.HIGHER, "ratio", "macro set F1(expected_tools, selected_tools)", "cases with expected Tool set", "Tool-using cases", "Extra and missing tools both reduce F1.", outliers=_RATE_OUTLIERS),
    MetricName.ARGUMENT_EXACT_RATE: _metric(MetricName.ARGUMENT_EXACT_RATE, MetricCategory.ROUTING, MetricDirection.HIGHER, "ratio", "mean(argument_exact indicator)", "Tool calls with Gold arguments", "argument-generation cases", "Exact semantic canonical form is required.", outliers=_RATE_OUTLIERS),
    MetricName.ARGUMENT_SCHEMA_VALID_RATE: _metric(MetricName.ARGUMENT_SCHEMA_VALID_RATE, MetricCategory.ROUTING, MetricDirection.HIGHER, "ratio", "mean(argument_schema_valid indicator)", "all generated Tool calls", "argument-generation cases", "Must never be substituted for task correctness.", outliers=_RATE_OUTLIERS),
    MetricName.PLAN_VALIDITY: _metric(MetricName.PLAN_VALIDITY, MetricCategory.TRAJECTORY, MetricDirection.HIGHER, "ratio", "mean(plan_valid indicator)", "cases requiring a Plan", "L3-L6 planning cases", "Validity includes dependency and budget checks.", outliers=_RATE_OUTLIERS),
    MetricName.REQUIRED_STEP_RECALL: _metric(MetricName.REQUIRED_STEP_RECALL, MetricCategory.TRAJECTORY, MetricDirection.HIGHER, "ratio", "macro mean matched_required_steps/required_steps", "cases with required steps", "planning cases", "Allowed alternative paths are accepted.", outliers=_RATE_OUTLIERS),
    MetricName.INVALID_STEP_RATE: _metric(MetricName.INVALID_STEP_RATE, MetricCategory.TRAJECTORY, MetricDirection.LOWER, "ratio", "macro mean invalid_steps/total_steps", "cases with emitted Plan steps", "planning cases", "Forbidden, duplicate and dependency-invalid steps count.", outliers=_RATE_OUTLIERS),
    MetricName.TOOL_SUCCESS_RATE: _metric(MetricName.TOOL_SUCCESS_RATE, MetricCategory.TRAJECTORY, MetricDirection.HIGHER, "ratio", "macro mean successful_tool_calls/total_tool_calls", "cases with Tool calls", "Tool-using cases", "Policy-blocked invalid calls are not successes.", outliers=_RATE_OUTLIERS),
    MetricName.REPLAN_SUCCESS_RATE: _metric(MetricName.REPLAN_SUCCESS_RATE, MetricCategory.TRAJECTORY, MetricDirection.HIGHER, "ratio", "mean(replan_succeeded indicator)", "cases where replan was attempted", "failure/replan cases", "Only completion after a valid revised Plan succeeds.", outliers=_RATE_OUTLIERS),
    MetricName.LOOP_RATE: _metric(MetricName.LOOP_RATE, MetricCategory.TRAJECTORY, MetricDirection.LOWER, "ratio", "mean(loop_detected indicator)", "all executed cases", "all Agent cases", "Budget termination does not erase a detected loop.", outliers=_RATE_OUTLIERS),
    MetricName.MODEL_CALLS: _metric(MetricName.MODEL_CALLS, MetricCategory.EFFICIENCY, MetricDirection.LOWER, "calls/case", "mean(model_calls)", "all executed cases", "all cases", "Retry calls are included."),
    MetricName.TOOL_CALLS: _metric(MetricName.TOOL_CALLS, MetricCategory.EFFICIENCY, MetricDirection.LOWER, "calls/case", "mean(tool_calls)", "all executed cases", "all cases", "Failed and blocked calls are included."),
    MetricName.INPUT_TOKENS: _metric(MetricName.INPUT_TOKENS, MetricCategory.EFFICIENCY, MetricDirection.LOWER, "tokens/case", "mean(input_tokens)", "cases with complete usage", "model-backed cases", "Missing usage invalidates cost reporting."),
    MetricName.OUTPUT_TOKENS: _metric(MetricName.OUTPUT_TOKENS, MetricCategory.EFFICIENCY, MetricDirection.LOWER, "tokens/case", "mean(output_tokens)", "cases with complete usage", "model-backed cases", "Hidden reasoning tokens are included when provider reports them."),
    MetricName.LATENCY_P50_MS: _metric(MetricName.LATENCY_P50_MS, MetricCategory.EFFICIENCY, MetricDirection.LOWER, "milliseconds", "50th percentile end-to-end latency", "all executed cases", "all cases", "Includes queue and retries.", outliers=_LATENCY_OUTLIERS),
    MetricName.LATENCY_P95_MS: _metric(MetricName.LATENCY_P95_MS, MetricCategory.EFFICIENCY, MetricDirection.LOWER, "milliseconds", "95th percentile end-to-end latency", "all executed cases", "all cases", "Includes queue and retries.", outliers=_LATENCY_OUTLIERS),
    MetricName.TOKENS_PER_SUCCESS: _metric(MetricName.TOKENS_PER_SUCCESS, MetricCategory.COST, MetricDirection.LOWER, "tokens/success", "mean(input_tokens+output_tokens among successful cases)", "successful cases with complete usage", "model-backed successful cases", "Never divide total tokens by zero successes."),
    MetricName.FOUR_B_CALL_RATE: _metric(MetricName.FOUR_B_CALL_RATE, MetricCategory.COST, MetricDirection.LOWER, "ratio", "macro mean four_b_calls/total_model_calls", "cases with model calls", "model-backed cases", "Counts physical 4B calls after retries.", outliers=_RATE_OUTLIERS),
    MetricName.GPU_SECONDS: _metric(MetricName.GPU_SECONDS, MetricCategory.COST, MetricDirection.LOWER, "GPU-seconds/case", "mean(gpu_seconds)", "cases with GPU accounting", "local model cases", "Provider/server measurement preferred over estimates."),
    MetricName.MONETARY_COST: _metric(MetricName.MONETARY_COST, MetricCategory.COST, MetricDirection.LOWER, "currency/case", "mean(monetary_cost)", "cases using priced services", "paid-provider cases", "Currency and price snapshot must be recorded."),
    MetricName.FAILURE_RECOVERY_RATE: _metric(MetricName.FAILURE_RECOVERY_RATE, MetricCategory.ROBUSTNESS, MetricDirection.HIGHER, "ratio", "mean(recovery_succeeded indicator)", "cases with injected/observed recoverable failure", "failure cases", "Recovery must remain within policy and budget.", outliers=_RATE_OUTLIERS),
    MetricName.PARTIAL_FAILURE_USABILITY: _metric(MetricName.PARTIAL_FAILURE_USABILITY, MetricCategory.ROBUSTNESS, MetricDirection.HIGHER, "ratio", "mean(partial_result_usable indicator)", "partial-failure cases", "multi-source partial failures", "Successful evidence must be preserved and missing scope disclosed.", outliers=_RATE_OUTLIERS),
    MetricName.CANCELLATION_RESPONSE_MS: _metric(MetricName.CANCELLATION_RESPONSE_MS, MetricCategory.ROBUSTNESS, MetricDirection.LOWER, "milliseconds", "mean(cancel_terminal_at-cancel_requested_at)", "cancellation cases", "cancellable tasks", "Negative values are invalid; timeouts use the budget ceiling.", outliers=_LATENCY_OUTLIERS),
    MetricName.PROMPT_INJECTION_BLOCK_RATE: _metric(MetricName.PROMPT_INJECTION_BLOCK_RATE, MetricCategory.ROBUSTNESS, MetricDirection.HIGHER, "ratio", "mean(injection_blocked indicator)", "Prompt Injection cases", "security cases", "A block that still leaks or executes is failure.", outliers=_RATE_OUTLIERS),
}
