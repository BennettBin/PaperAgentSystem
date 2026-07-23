# PaperAgent Final Evaluation Report

## B0-B3 and production-safe policy

| System | N | Task Success (95% CI) | Citation Recall | Mean Token | P95 ms |
|---|---:|---:|---:|---:|---:|
| b0_vanilla_rag | 300 | 0.0800 [0.0500, 0.1100] | 0.4528 | 1488.3 | 6032.4 |
| b1_fixed_workflow | 300 | 0.0633 [0.0400, 0.0900] | 0.4294 | 1159.5 | 5750.8 |
| b2_bounded_react | 300 | 0.0633 [0.0367, 0.0917] | 0.4073 | 1019.5 | 9376.6 |
| b3_full_4b | 300 | 0.0700 [0.0467, 0.0967] | 0.3977 | 1132.5 | 10502.3 |
| production_safe_path | 300 | 0.0633 [0.0400, 0.0900] | 0.4294 | 1159.5 | 5750.8 |

## Ablations

- planner: **NO-GO**; evaluation/reports/m06_planner_ablation_v1/report.json.
- multi_agent: **NO-GO**; evaluation/reports/n05_multi_agent_ablation_v1/report.json.
- sft: **UNAVAILABLE**; Stage O was explicitly skipped by the user; no effect estimate exists..
- cascade: **UNAVAILABLE**; Stage O was explicitly skipped by the user; no effect estimate exists..

## Limitations

- All B0-B3 Task Success confidence intervals overlap; no baseline beats B0 significantly.
- Planner and Multi-Agent are effect No-Go and remain non-default.
- SFT and Cascade are unavailable because Stage O was explicitly skipped.
- The 10% human audit validates dataset answer-type Gold, not final generated outputs.
- Local monetary cost is zero-valued accounting and excludes electricity/hardware amortization.
