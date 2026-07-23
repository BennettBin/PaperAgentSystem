# P02 Failure Clustering and Human-in-the-Loop Governance

P02 is an offline governance mechanism. Failed evaluation results are clustered with the existing closed error taxonomy; raw output and Trace payloads are excluded from the review list. Candidate records require provenance, authorization, build version, human review and, for private data, explicit consent plus anonymization.

Candidates remain in staging until approved. Promotion invokes an operator-supplied regression and safety Gate Runner and requires both versioned reports before writing a new current version. Rollback changes only the offline dataset pointer and appends an audit record. The module never mutates production prompts or model weights.

Verification: 36 combined P02/API/L04/dataset-contract tests passed; Ruff and mypy passed. Truth class is `unit_fixture`; no training-effect claim is made.
