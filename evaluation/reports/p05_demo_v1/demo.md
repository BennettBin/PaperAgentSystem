# PaperAgent Offline Evidence Demo

> The production route remains Safe RAG. Dynamic Planner and Multi-Agent are demonstrated as bounded experimental evidence because M06/N05 are NO-GO.

## 1. Route complex request without silently promoting experiments

Truth class: `integration_real`; source: `evaluation/reports/p01_runtime_integration_v1/report.json`.

```json
{
  "cascade": "unavailable_o_skipped",
  "dynamic_planner": "opt_in_no_go",
  "multi_agent": "opt_in_no_go",
  "production_default": "safe_rag"
}
```

## 2. Show bounded Plan state transition

Truth class: `unit_fixture`; source: `tests/test_m05_dynamic_executor.py`.

```json
{
  "claim_boundary": "mechanism evidence only",
  "from_version": 1,
  "max_replans": 2,
  "to_version": 2,
  "trigger": "insufficient_evidence"
}
```

## 3. Replay the bounded collaboration roles

Truth class: `offline_real_model`; source: `evaluation/reports/n05_multi_agent_ablation_v1/report.json`.

```json
{
  "calls_per_case": 5,
  "depth": 1,
  "promotion_decision": "NO-GO",
  "roles": [
    "paper_reader",
    "evidence",
    "critic",
    "writer",
    "verifier"
  ]
}
```

## 4. Inspect Gold evidence IDs and page provenance

Truth class: `human_review`; source: `evaluation/datasets/v1/test_cases_v1.jsonl`.

```json
{
  "case_id": "l4-001",
  "evidence_count": 2,
  "items": [
    {
      "evidence_id": "l4-001-p1-e1",
      "page": 12,
      "paper_id": "qasper:1802.06053",
      "section": "Corpora and acoustic features"
    },
    {
      "evidence_id": "l4-001-p2-e1",
      "page": 40,
      "paper_id": "qasper:1708.01065",
      "section": "Data Properties"
    }
  ]
}
```

## 5. Inspect the frozen Full-System quality outcome

Truth class: `offline_real_model`; source: `evaluation/reports/n05_multi_agent_ablation_v1/case_scores.jsonl`.

```json
{
  "claim_support": 0.5,
  "negative_result_visible": true,
  "omission_rate": 0.5,
  "task_success": false
}
```

## 6. Close with measured Token and latency

Truth class: `offline_real_model`; source: `evaluation/reports/n05_multi_agent_ablation_v1/case_scores.jsonl`.

```json
{
  "latency_ms": 39779,
  "report": "evaluation/reports/p04_final_v1/report.json",
  "system_id": "full_system",
  "total_tokens": 9401
}
```
