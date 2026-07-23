# P01 Unified Agent Runtime Integration

Status: completed under the explicit scope override that skips Stage O.

- Production defaults to `fast_path` or `safe_rag`.
- Dynamic Planner and Multi-Agent remain opt-in because M06/N05 are No-Go.
- Cascade is reported as `unavailable_o_skipped`; no model-upgrade effect is claimed.
- Public SSE events expose route, model profile, step/agent status and verification only; hidden reasoning is not emitted.
- Legacy task metadata has an idempotent read/migrate strategy.

Verification: Python regression 36 passed; frontend component regression 18 passed; final-acceptance/runtime regression 4 passed; Ruff, mypy, TypeScript and Next.js production build passed. An isolated fresh Compose project started eight healthy services, returned `adapter_mode=real` from the API and HTTP 200 from Web, then was removed with its isolated volumes.

Real experimental evidence is retained in `m06_planner_ablation_v1` and `n05_multi_agent_ablation_v1`. Those reports do not justify production promotion. Because the user explicitly skipped Stage O, the original model-upgrade E2E item is satisfied only as a fail-closed availability contract, not as a successful model improvement claim.
