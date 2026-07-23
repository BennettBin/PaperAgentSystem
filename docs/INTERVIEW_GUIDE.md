# Interview Guide

## Planner and Replan

Plan V2 is a versioned Pydantic contract with DAG dependencies, permissions, budgets, evidence requirements and completion predicates. Completion is evaluated from structured Observations. Replan is bounded to two revisions, uses immutable patches and prevents repeated strategy/input fingerprints. Mechanism gates passed; M06 effect gates did not.

## Memory

Short-term Memory uses recent messages plus traceable segments; long-term Memory uses conversation summaries and explicit preferences. Retrieval can return from a summary to source message IDs. Deletion invalidates derived Memory and indexes.

## Multi-Agent

Six role contracts communicate by references through an append-only Blackboard. Coordinator depth is one with budgeted concurrency and partial-failure handling. N05 showed a Claim Support gain but unacceptable Token/latency and no Task Success gain, so Single Agent remains default.

## SFT and Cascade

Stage O was skipped by explicit instruction. There is no trained project Adapter and no Cascade benefit claim. Runtime reports `unavailable_o_skipped`; this is preferable to presenting an unverified model upgrade.

## Evaluation, cost and safety

The fixed 300-case set has provenance, authorization, group split and Gold evidence. Reports use seeded/paired bootstrap 95% CI. All calls record profile/version/usage/latency. Tool Registry, Workspace isolation, prompt-injection tests, citation verification, admin separation and offline-only HITL promotion form the main safety boundary.

## Good closing answer

“我实现的不只是 Agent 功能，还建立了决定它是否应该上线的证据链。Planner 和多 Agent 的机制是完整的，但真实消融没有通过效果/成本门槛，所以生产默认保持简单可靠路径。这一负结果反而证明系统具备可评测、可回滚和不自欺的工程闭环。”
