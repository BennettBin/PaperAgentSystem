# N05 multi-Agent ablation

Truth class: `offline_real_model`. Decision: `NO-GO`.

| Metric | Value |
|---|---:|
| Paired cases | 2 |
| Task Success delta | 0.0000 |
| Claim Support delta | 0.5000 |
| Token/success increase | None |
| Conflict Recall delta | None |
| Severe unsupported reduction | None |

| Gate | Passed |
|---|---|
| claim_support_gain | yes |
| conflict_recall_gain | no |
| severe_unsupported_reduction | no |
| six_group_matrix_complete | yes |
| token_increase_within_limit | no |

## Limitations

- Conflict gold is unavailable in frozen L4/L5; conflict Recall and its promotion gate are unavailable.
- The frozen single-Agent report has no claim-level unsupported-fact annotation, so reduction is unavailable.
