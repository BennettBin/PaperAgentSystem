# Failure Postmortems

## 1. Old evaluation results outlived their code path

- Signal: current routing, Planner integration and multi-Agent defaults no longer matched the assumptions recorded by previous reports.
- Root cause: generated evaluation artifacts were being treated as timeless product facts instead of version-bound evidence.
- Decision: remove old scores and decisions from current product documentation and set effect status to `pending_re_evaluation`.
- Prevention: every new report must record the code revision, model/Profile, prompts, role manifests, dataset and runtime flags.

## 2. Default enablement can be mistaken for universal routing

- Signal: saying “Multi-Agent is default” can be misread as “every task launches six roles.”
- Root cause: feature defaults and route eligibility were described together without distinguishing them.
- Decision: keep both gates default-on, but require at least two distinct papers plus explicit comparison/review/synthesis intent.
- Fallback: setting either gate to `false`, an unavailable Adapter or an ineligible request returns to the bounded Planner/Safe RAG path.

## 3. Mechanism evidence is not effect evidence

- Signal: role, DAG, Blackboard, revision and persistence tests prove execution semantics but not answer-quality improvement.
- Decision: report those checks as mechanism verification only; quality, cost and latency remain unknown until the current version is re-evaluated.
