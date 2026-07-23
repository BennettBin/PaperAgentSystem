# PaperAgent Model Card

## Production profiles

| Role | Serving model | Frozen ID | Use |
|---|---|---|---|
| Small decision | `qwen3:1.7b` | `8f68893c685c` | bounded routing/decision experiments |
| Answer/evaluation | `qwen3.5:4b` | `2a654d98e6fb` | evidence-grounded generation and frozen evaluations |

Models run locally through the Model Runtime Port. Every reported call records model, profile, version, input/output usage and latency. The production answer chain must fail explicitly when a model is unavailable; it does not substitute Fake answers.

## Intended use

Paper reading, section QA, multi-paper comparison support, drafting assistance and citation verification with user-provided or authorized documents. Outputs require source inspection for consequential academic claims.

## Non-goals and risks

- Not an autonomous scientific authority or a source of invented experiments.
- Frozen B0–B3 Task Success is only 6.33%–8.0%; verification, generation and routing are the dominant failure classes.
- Dynamic Planner and Multi-Agent are NO-GO and non-default.
- No project SFT/RL Adapter is claimed: Stage O was explicitly skipped.
- Local monetary cost is recorded as zero but excludes electricity and hardware amortization.

## Evaluation and governance

See `evaluation/reports/p04_final_v1/report.json`. Promotion requires frozen evaluation, security checks and explicit policy change. Model/Profile changes are versioned and rollbackable.
