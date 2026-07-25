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
- Previous evaluation artifacts were produced by an older code path and are not
  valid evidence for the current runtime. Current quality, cost and latency are
  pending a version-bound re-evaluation.
- Dynamic Planner is default for single-paper and ordinary document tasks.
  Eligible multi-paper comparison/review/synthesis tasks use the bounded
  multi-Agent DAG by default; either runtime gate can disable that route.
- No project SFT/RL Adapter is claimed: Stage O was explicitly skipped.
- Local monetary cost is recorded as zero but excludes electricity and hardware amortization.

## Evaluation and governance

The evaluation framework remains available, but no old result is cited as a current claim. New reports must bind the code revision, model/Profile, prompts, role manifests, dataset and runtime flags. Model/Profile changes remain versioned and rollbackable.
