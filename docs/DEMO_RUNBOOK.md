# 3–5 Minute Demo Runbook

## Before recording

Run `python -m evaluation.p05_demo`. Optionally start the product with `docker compose up -d --build` and open `/admin/evaluation` with a configured `ADMIN_API_TOKEN`.

## Timeline

1. **0:00–0:35 — Problem and architecture**: show the README diagram; explain why multi-file academic work needs evidence, bounded plans and verification.
2. **0:35–1:15 — Route and Plan**: show Demo steps 1–2. State that Dynamic Planner is now the default public planning/state layer for document tasks, while Safe RAG remains the bounded product executor and fallback; Plan v1→v2 is a real code-path mechanism fixture, not an effect claim.
3. **1:15–2:00 — Agent roles**: show the five bounded roles, depth 1 and five calls/case. Immediately show the N05 NO-GO decision.
4. **2:00–2:40 — Citation and Verifier**: show the two Gold evidence IDs/pages for `l4-001`, then the Full-System outcome (Claim Support 0.5, Task Success false).
5. **2:40–3:20 — Cost and Dashboard**: show 9,401 Token and 39,779 ms for the selected frozen case, then `/admin/evaluation` metrics and sample drilldown.
6. **3:20–4:00 — Decision**: distinguish the 2026-07-25 product-policy default for bounded Dynamic Planner from an evaluation effect claim; explain why Multi-Agent still was not promoted and how P02 staging, regression/safety gates and rollback work.

Never describe Multi-Agent or the free-form experimental executor as the production default. Do not show an admin token, prompt text, private paper正文 or hidden reasoning while recording.
