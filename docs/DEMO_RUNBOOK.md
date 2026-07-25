# 3–5 Minute Demo Runbook

## Before recording

Start the product with `docker compose up -d --build`. Do not present previously generated evaluation reports as current results; rerun evaluation against the current revision before showing quality or cost numbers.

## Timeline

1. **0:00–0:35 — Problem and architecture**: show the README diagram; explain why multi-file academic work needs evidence, bounded plans and verification.
2. **0:35–1:15 — Route and Plan**: show a single-paper task using Dynamic Planner + Safe RAG, including its public plan state.
3. **1:15–2:00 — Agent roles**: submit an eligible multi-paper comparison and show Coordinator, parallel Paper Readers, Evidence, Critic, Writer and Verifier events.
4. **2:00–2:40 — Citation and Verifier**: open persisted evidence references and explain the independent multi-Agent Verifier plus ProductService evidence boundary.
5. **2:40–3:20 — Failure and fallback**: explain Reader partial failure, optional Critic degradation, one bounded Writer revision and dual-gate opt-out.
6. **3:20–4:00 — Evaluation status**: state that old-code results were invalidated and current quality, Token and P95 numbers require a fresh version-bound run.

Never say that every task uses Multi-Agent or quote old-code evaluation numbers. Do not show an admin token, prompt text, private paper正文 or hidden reasoning while recording.
