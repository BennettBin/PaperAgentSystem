# Interview Guide

## Planner and Replan

Plan V2 is a versioned Pydantic contract with DAG dependencies, permissions, budgets, evidence requirements and completion predicates. Completion is evaluated from structured Observations. Replan is bounded to two revisions, uses immutable patches and prevents repeated strategy/input fingerprints. Dynamic Planner is default for single-paper and ordinary document tasks; Safe RAG performs the actual execution and remains the fallback.

## Memory

Short-term Memory uses recent messages plus traceable segments; long-term Memory uses conversation summaries and explicit preferences. Retrieval can return from a summary to source message IDs. Deletion invalidates derived Memory and indexes.

## Multi-Agent

Six role contracts communicate by references through an append-only Blackboard. Coordinator depth is one with budgeted concurrency and partial-failure handling. Eligible multi-paper comparison/review/synthesis tasks use this DAG by default; single-paper and ordinary tasks do not.

## SFT and Cascade

Stage O was skipped by explicit instruction. There is no trained project Adapter and no Cascade benefit claim. Runtime reports `unavailable_o_skipped`; this is preferable to presenting an unverified model upgrade.

## Evaluation, cost and safety

The fixed 300-case set has provenance, authorization, group split and Gold evidence. Reports use seeded/paired bootstrap 95% CI. All calls record profile/version/usage/latency. Tool Registry, Workspace isolation, prompt-injection tests, citation verification, admin separation and offline-only HITL promotion form the main safety boundary.

## Good closing answer

“我实现的不只是 Agent 功能，还把路由、角色、证据、权限、预算和失败语义做成了可验证链路。当前单论文默认使用 Dynamic Planner + Safe RAG，合格多论文任务默认使用有界 Multi-Agent。旧代码评测已经失效，所以我只陈述当前机制测试，不引用旧效果数字；新的质量、成本和延迟会绑定当前版本重新评测。”
