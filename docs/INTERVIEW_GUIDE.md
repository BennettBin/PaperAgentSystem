# Interview Guide

## Planner and Replan

Plan V2 is a versioned Pydantic contract with DAG dependencies, permissions, budgets, evidence requirements and completion predicates. Completion is evaluated from structured Observations. Replan is bounded to two revisions, uses immutable patches and prevents repeated strategy/input fingerprints. Mechanism gates passed; M06 effect gates did not. Since 2026-07-25, the bounded Dynamic Planner is default-on for document tasks as a public plan/state layer; the existing Safe RAG path still performs the actual product execution and remains the fallback.

## Memory

Short-term Memory uses recent messages plus traceable segments; long-term Memory uses conversation summaries and explicit preferences. Retrieval can return from a summary to source message IDs. Deletion invalidates derived Memory and indexes.

## Multi-Agent

Six role contracts communicate by references through an append-only Blackboard. Coordinator depth is one with budgeted concurrency and partial-failure handling. N05 showed a Claim Support gain but unacceptable Token/latency and no Task Success gain, so Single Agent remains default.

## SFT and Cascade

Stage O was skipped by explicit instruction. There is no trained project Adapter and no Cascade benefit claim. Runtime reports `unavailable_o_skipped`; this is preferable to presenting an unverified model upgrade.

## Evaluation, cost and safety

The fixed 300-case set has provenance, authorization, group split and Gold evidence. Reports use seeded/paired bootstrap 95% CI. All calls record profile/version/usage/latency. Tool Registry, Workspace isolation, prompt-injection tests, citation verification, admin separation and offline-only HITL promotion form the main safety boundary.

## Good closing answer

“我实现的不只是 Agent 功能，还建立了决定它是否应该上线的证据链。真实消融没有通过 Planner 与多 Agent 的效果/成本门槛，所以我没有伪造效果晋级：多 Agent 继续双开关关闭；Dynamic Planner 后来按产品策略作为文档任务默认的公开计划/状态层启用，但实际执行仍受 Safe RAG、预算、权限和核验约束，失败时可回退。这体现了机制可用、产品策略与实验结论三者分开管理。”
