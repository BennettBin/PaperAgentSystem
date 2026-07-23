# M06 Planner ablation

Truth class: `offline_real_model`. Decision: `NO-GO`.

| Metric | Value |
|---|---:|
| Best old L3-L5 Task Success | 0.0533 |
| Full candidate L3-L5 Task Success | 0.0667 |
| Paired delta | 0.0133 |
| Invalid Tool Call reduction | 0.0000 |
| Recovery-rate delta | 0.0000 |
| Token/success increase | 0.7855 |

| Gate | Passed |
|---|---|
| fault_recovery_improves_15pp | no |
| five_group_matrix_complete | yes |
| invalid_tool_call_rate_reduces_25pct | no |
| l3_l5_success_improves_8pp | no |
| token_per_success_increase_lte_15pct | no |
| zero_loops_and_unauthorized_calls | yes |
