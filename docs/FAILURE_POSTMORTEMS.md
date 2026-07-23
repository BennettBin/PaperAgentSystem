# Failure Postmortems

## 1. Planner improved structure but not end-to-end success

- Signal: M02 final Plan Schema validity 100%, invalid Tool calls 0 and Required Step Recall 96.84%.
- Counter-signal: M06 L3–L5 Task Success improvement was only +1.33pp with paired 95% CI [-3.33pp, 6.00pp]; recovery gain was 0pp and Token/success rose 78.55%.
- Root cause: a valid Plan cannot repair weak evidence retrieval/generation, and 53.33% of M02 cases already depended on safe fallback.
- Decision: retain bounded Planner mechanisms and recovery semantics, but keep the path opt-in. Do not tune on the frozen test set.
- Evidence: `evaluation/reports/m06_planner_ablation_v1/report.json`.

## 2. Multi-Agent raised Claim Support but destroyed efficiency

- Signal: Full System improved Claim Support by 5.63pp versus Single Agent.
- Counter-signal: Task Success fell 1.11pp with 95% CI [-3.33pp, 0]; total Token increased 398.03%.
- Root cause: repeated Critic/Verifier passes added 886.6 Token and 6.61s without quality gain; the final revision reduced Claim Support by 2.07pp.
- Decision: production default remains Single Agent; deterministic verification is retained, extra LLM review/revision is disabled.
- Evidence: `evaluation/reports/n05_multi_agent_ablation_v1/report.json`.

## 3. Baseline quality exposed verification/generation bottlenecks

- Signal: B0–B3 Task Success was 8.0% / 6.33% / 6.33% / 7.0%; no paired Task Success CI established improvement over B0.
- Trace finding: verification, generation and routing were the three leading actionable error families.
- Root cause: small local models frequently produced incomplete or unsupported answers even when retrieval and schemas were valid.
- Decision: report the low baseline openly, keep citation validation fail-closed, and prioritize new development data plus evidence/generation improvements over adding orchestration depth.
- Evidence: `evaluation/reports/l05_baselines_v1/baseline_report.json` and `evaluation/reports/p04_final_v1/report.json`.
