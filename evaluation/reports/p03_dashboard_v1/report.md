# P03 Evaluation Dashboard

The administrator-only Dashboard reads versioned offline artifacts. Its primary L05 view contains 300 frozen B3 rows; N05 contributes 90 Single-Agent and 90 Full-System rows so Claim Support and its paired delta are displayed from a real denominator. L05 Claim Support remains explicitly N/A because that report did not measure it.

Filters cover task family, difficulty, language, model, error category and system. Every available aggregate retains its contributing case IDs. Case detail is restricted by strict Schema to public Plan/Action/Observation/Citation/Public Trace structures; prompt text, paper正文, secrets and hidden reasoning have no accepted field.

Verification: 15 Python/API tests passed, including exact L05 metric parity, N05 Claim Support/delta parity and a repeated 300-row load/filter/drilldown P95 gate below two seconds. Ruff, mypy, TypeScript and the Next.js production build passed. The separate route is `/admin/evaluation`; it requires `X-Admin-Token` and is not linked from the ordinary conversation UI.
