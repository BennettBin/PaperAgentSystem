# PaperAgent L03 Metric Catalog

This file is generated from `evaluation.metrics.catalog`. The Python catalog is the executable truth.
Format/schema validity metrics are diagnostic and must never replace task correctness.

## effect

| Metric | Direction | Unit | Formula | Denominator | Applicability | Outlier handling |
|---|---|---|---|---|---|---|
| task_success | higher_is_better | ratio | mean(case task_success indicator) | all executed cases | all task families | Values are bounded to [0,1]; undefined denominators are excluded and counted. |
| answer_correctness | higher_is_better | score | mean(programmatic/LLM/human correctness score) | cases with a correctness judgment | answer-producing cases | Values are bounded to [0,1]; undefined denominators are excluded and counted. |
| citation_precision | higher_is_better | ratio | macro mean TP/(TP+FP) | cases with at least one predicted citation | citation cases | Values are bounded to [0,1]; undefined denominators are excluded and counted. |
| citation_recall | higher_is_better | ratio | macro mean TP/(TP+FN) | cases with Gold evidence | evidence-required cases | Values are bounded to [0,1]; undefined denominators are excluded and counted. |
| claim_support_rate | higher_is_better | ratio | macro mean supported_claims/total_claims | cases emitting factual claims | factual answer and writing cases | Values are bounded to [0,1]; undefined denominators are excluded and counted. |
| hallucination_rate | lower_is_better | ratio | macro mean hallucinated_claims/total_claims | cases emitting factual claims | factual answer and writing cases | Values are bounded to [0,1]; undefined denominators are excluded and counted. |

## routing

| Metric | Direction | Unit | Formula | Denominator | Applicability | Outlier handling |
|---|---|---|---|---|---|---|
| intent_top1 | higher_is_better | ratio | mean(intent_rank <= 1) | cases with intent Gold | routing cases | Values are bounded to [0,1]; undefined denominators are excluded and counted. |
| intent_top3 | higher_is_better | ratio | mean(intent_rank <= 3) | cases with intent Gold | routing cases | Values are bounded to [0,1]; undefined denominators are excluded and counted. |
| skill_top1 | higher_is_better | ratio | mean(skill_rank <= 1) | cases with Skill Gold | Skill routing cases | Values are bounded to [0,1]; undefined denominators are excluded and counted. |
| skill_top3 | higher_is_better | ratio | mean(skill_rank <= 3) | cases with Skill Gold | Skill routing cases | Values are bounded to [0,1]; undefined denominators are excluded and counted. |
| tool_selection_f1 | higher_is_better | ratio | macro set F1(expected_tools, selected_tools) | cases with expected Tool set | Tool-using cases | Values are bounded to [0,1]; undefined denominators are excluded and counted. |
| argument_exact_rate | higher_is_better | ratio | mean(argument_exact indicator) | Tool calls with Gold arguments | argument-generation cases | Values are bounded to [0,1]; undefined denominators are excluded and counted. |
| argument_schema_valid_rate | higher_is_better | ratio | mean(argument_schema_valid indicator) | all generated Tool calls | argument-generation cases | Values are bounded to [0,1]; undefined denominators are excluded and counted. |

## trajectory

| Metric | Direction | Unit | Formula | Denominator | Applicability | Outlier handling |
|---|---|---|---|---|---|---|
| plan_validity | higher_is_better | ratio | mean(plan_valid indicator) | cases requiring a Plan | L3-L6 planning cases | Values are bounded to [0,1]; undefined denominators are excluded and counted. |
| required_step_recall | higher_is_better | ratio | macro mean matched_required_steps/required_steps | cases with required steps | planning cases | Values are bounded to [0,1]; undefined denominators are excluded and counted. |
| invalid_step_rate | lower_is_better | ratio | macro mean invalid_steps/total_steps | cases with emitted Plan steps | planning cases | Values are bounded to [0,1]; undefined denominators are excluded and counted. |
| tool_success_rate | higher_is_better | ratio | macro mean successful_tool_calls/total_tool_calls | cases with Tool calls | Tool-using cases | Values are bounded to [0,1]; undefined denominators are excluded and counted. |
| replan_success_rate | higher_is_better | ratio | mean(replan_succeeded indicator) | cases where replan was attempted | failure/replan cases | Values are bounded to [0,1]; undefined denominators are excluded and counted. |
| loop_rate | lower_is_better | ratio | mean(loop_detected indicator) | all executed cases | all Agent cases | Values are bounded to [0,1]; undefined denominators are excluded and counted. |

## efficiency

| Metric | Direction | Unit | Formula | Denominator | Applicability | Outlier handling |
|---|---|---|---|---|---|---|
| model_calls | lower_is_better | calls/case | mean(model_calls) | all executed cases | all cases | Reject negative/non-finite inputs; retain all valid cases and report bootstrap CI. |
| tool_calls | lower_is_better | calls/case | mean(tool_calls) | all executed cases | all cases | Reject negative/non-finite inputs; retain all valid cases and report bootstrap CI. |
| input_tokens | lower_is_better | tokens/case | mean(input_tokens) | cases with complete usage | model-backed cases | Reject negative/non-finite inputs; retain all valid cases and report bootstrap CI. |
| output_tokens | lower_is_better | tokens/case | mean(output_tokens) | cases with complete usage | model-backed cases | Reject negative/non-finite inputs; retain all valid cases and report bootstrap CI. |
| latency_p50_ms | lower_is_better | milliseconds | 50th percentile end-to-end latency | all executed cases | all cases | Retain timeouts at the configured budget ceiling; reject negative/non-finite values; report P50/P95. |
| latency_p95_ms | lower_is_better | milliseconds | 95th percentile end-to-end latency | all executed cases | all cases | Retain timeouts at the configured budget ceiling; reject negative/non-finite values; report P50/P95. |

## cost

| Metric | Direction | Unit | Formula | Denominator | Applicability | Outlier handling |
|---|---|---|---|---|---|---|
| tokens_per_success | lower_is_better | tokens/success | mean(input_tokens+output_tokens among successful cases) | successful cases with complete usage | model-backed successful cases | Reject negative/non-finite inputs; retain all valid cases and report bootstrap CI. |
| four_b_call_rate | lower_is_better | ratio | macro mean four_b_calls/total_model_calls | cases with model calls | model-backed cases | Values are bounded to [0,1]; undefined denominators are excluded and counted. |
| gpu_seconds | lower_is_better | GPU-seconds/case | mean(gpu_seconds) | cases with GPU accounting | local model cases | Reject negative/non-finite inputs; retain all valid cases and report bootstrap CI. |
| monetary_cost | lower_is_better | currency/case | mean(monetary_cost) | cases using priced services | paid-provider cases | Reject negative/non-finite inputs; retain all valid cases and report bootstrap CI. |

## robustness

| Metric | Direction | Unit | Formula | Denominator | Applicability | Outlier handling |
|---|---|---|---|---|---|---|
| failure_recovery_rate | higher_is_better | ratio | mean(recovery_succeeded indicator) | cases with injected/observed recoverable failure | failure cases | Values are bounded to [0,1]; undefined denominators are excluded and counted. |
| partial_failure_usability | higher_is_better | ratio | mean(partial_result_usable indicator) | partial-failure cases | multi-source partial failures | Values are bounded to [0,1]; undefined denominators are excluded and counted. |
| cancellation_response_ms | lower_is_better | milliseconds | mean(cancel_terminal_at-cancel_requested_at) | cancellation cases | cancellable tasks | Retain timeouts at the configured budget ceiling; reject negative/non-finite values; report P50/P95. |
| prompt_injection_block_rate | higher_is_better | ratio | mean(injection_blocked indicator) | Prompt Injection cases | security cases | Values are bounded to [0,1]; undefined denominators are excluded and counted. |

## Statistical reporting

- Absolute values use the metric-specific statistic above.
- Main metrics report seeded percentile-bootstrap 95% confidence intervals.
- Candidate-vs-baseline comparisons require paired `case_id` values and use paired bootstrap deltas.
- Undefined denominators are excluded and reported; they are never coerced to zero.
- Reports retain dataset/config/model/Profile/Prompt versions and Judge provenance.
