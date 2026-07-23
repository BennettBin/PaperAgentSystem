# L05 frozen baseline report

Truth class: `offline_real_model`; dataset: `paperagent-eval-v1`.

| System | Cases | Task success | Answer correctness | Citation recall | p50 ms | p95 ms | Tokens | 4B call rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| b0_vanilla_rag | 300 | 0.0800 | 0.2437 | 0.4528 | 4414 | 6032 | 446486 | 1.0000 |
| b1_fixed_workflow | 300 | 0.0633 | 0.2189 | 0.4294 | 4202 | 5751 | 347840 | 1.0000 |
| b2_bounded_react | 300 | 0.0633 | 0.1913 | 0.4073 | 6984 | 9377 | 305850 | 0.5000 |
| b3_full_4b | 300 | 0.0700 | 0.2153 | 0.3977 | 7952 | 10502 | 339736 | 1.0000 |

Top actionable failures: verification, generation, routing
