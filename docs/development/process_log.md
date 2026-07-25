# 项目流程日志

## 2026-06-19

### 完成阶段 A：项目治理和架构契约

**执行工作包**: A01-A07

#### A01: 清理入口并建立项目元数据
- **完成内容**:
  - 创建 24 个顶级目录（apps, core, agent_runtime, tasks, memory, skills, tools 等）
  - 创建 .env.example：包含所有必需的环境变量（PostgreSQL, Redis, MinIO, LLM 等）
  - 创建 .gitignore：忽略模型权重、数据集、密钥、缓存和临时文件
  - 创建 pyproject.toml：Python 3.12 项目配置，定义依赖和工具设置
  - 创建 package.json：Next.js + TypeScript 前端项目配置
  - 创建 tsconfig.json：TypeScript 严格模式配置
  - 创建 .editorconfig：统一代码风格配置
  - 更新 README.md：完整的项目介绍、目录说明和开发指引
  - 保留原有试验文件（main.py, test.py）至 scratch 目录
- **验收**: 
  - ✅ 目录骨架完整
  - ✅ README 解释项目目标和文档入口
  - ✅ 配置文件齐全可用
  - ✅ 无故删除用户文件

#### A02: 建立 ADR 和模块依赖规则
- **完成内容**:
  - 创建 9 个 ADR 文件（docs/adr/）：
    - 0001: 自定义 Agent 状态机
    - 0002: PostgreSQL + pgvector
    - 0003: SSE 事件流推送
    - 0004: Port-Adapter 边界
    - 0005: Model Profile Registry
    - 0006: Memory 摘要与来源追踪
    - 0007: Conversation、Task、Workspace
    - 0008: Sandbox 边界
    - 0009: 系统与训练解耦
  - 创建 MODULE_DEPENDENCIES.md：依赖方向规则和分层示例
- **验收**:
  - ✅ 9 个 ADR 完整
  - ✅ 依赖方向可通过规则检查
  - ✅ Domain 层不依赖框架库

#### A03: 定义全局 ID、枚举和错误模型
- **完成内容**:
  - core/domain/ids.py: 定义 31 个强类型 ID 类（UserId, ConversationId, TaskId 等）
  - core/domain/enums.py: 定义 13 个枚举（TaskStatus, MessageRole, WorkspaceEntryKind 等）
  - core/errors.py: 定义统一错误模型（ProjectError, ErrorCode, 特定错误类）
  - core/__init__.py: 导出模块
- **验收**:
  - ✅ 全局类型可导入
  - ✅ 无循环依赖
  - ✅ 所有类型通过基础单元测试

#### A04: 定义核心 Domain 实体
- **完成内容**:
  - core/domain/user.py: User 和 Workspace 实体
  - core/domain/conversation.py: Conversation、Message、ConversationFile 实体
  - core/domain/task.py: Task、Plan、Step、ToolCall 实体（含状态转换逻辑）
  - core/domain/file.py: File 实体
  - core/domain/requirement.py: RequirementBrief、ClarificationQuestion、ClarificationRound 实体
  - core/domain/__init__.py: 导出所有实体
- **验收**:
  - ✅ 所有实体定义完整
  - ✅ 实体不包含 ORM 装饰器
  - ✅ 状态转换有校验保护

#### A05: 定义所有 Port
- **完成内容**:
  - core/ports/repositories.py: 6 个 Repository Port（Conversation, Message, Task, File, User, Workspace）
  - core/ports/llm_client.py: 3 个 LLM Port（LLMClient, EmbeddingClient, RerankerClient）
  - core/ports/storage.py: 3 个存储 Port（ObjectStore, TaskQueue, EventPublisher）
  - core/ports/registry.py: 4 个注册 Port（ToolRegistry, SkillRegistry, ModelRegistry）
  - core/ports/processing.py: 4 个处理 Port（DocumentParser, Retriever, ClaimVerifier, SandboxExecutor）
  - core/ports/observability.py: 3 个观测 Port（TraceWriter, Clock, IdGenerator）
  - core/ports/__init__.py: 导出所有 Port
- **验收**:
  - ✅ 23 个 Port 全部定义
  - ✅ Port 不泄漏实现类型
  - ✅ 所有 Port 有明确的输入/输出类型

#### A06: 定义 Agent Schema 和状态机
- **完成内容**:
  - agent_runtime/schema.py: 15+ 个 Schema 数据类（AgentState, Plan, ToolCallRequest, etc.）
  - agent_runtime/state_machine.py: StateMachine 类，定义完整的状态转换规则
  - agent_runtime/__init__.py: 导出所有 Schema 和工具
  - 状态转换规则：完整定义所有 13 个状态和允许的转换路径
- **验收**:
  - ✅ 所有 Schema 可序列化
  - ✅ 状态转换规则完整
  - ✅ 禁止非法转换

#### A07: 定义 REST API 和 SSE 契约
- **完成内容**:
  - core/api/schemas.py: 12 个 API Schema（Conversation, Message, Task, File, Artifact, Memory, Error, Health）
  - core/api/events.py: 20+ 个 SSE 事件类型和 EventSender 工具
  - core/api/__init__.py: 导出所有 API Schema 和事件
  - 事件格式：包含 event_id、sequence、timestamp、trace_id 等完整追踪信息
- **验收**:
  - ✅ API 契约完整
  - ✅ 事件顺序和去重可保证
  - ✅ 前端无需读取内部 Model

### 总结

**阶段 A 工作成果**:
- ✅ 完整的目录骨架和配置
- ✅ 9 个关键 ADR 和依赖规则
- ✅ 核心类型系统（31 个 ID + 13 个枚举 + 统一错误）
- ✅ 6 个 Domain 实体
- ✅ 23 个 Port 接口
- ✅ 完整的 Agent Schema 和状态机
- ✅ API 和 SSE 事件契约

**代码统计**:
- Python 文件: ~20 个
- TypeScript 配置: 已准备
- 文档: 9 个 ADR + 3 个说明文档
- 核心类型定义: ~50+ 个类

**未来步骤**:
- 建议下一步开始阶段 B：完整代码骨架
- 实现 Fake Adapter 用于端到端测试
- 搭建贯通 E2E 流程验证

**风险与改进**:
- 无重大阻碍
- 所有架构决策已冻结
- 可以放心实现具体业务逻辑
- Time: `2026-06-20 01:39 UTC`
  - Step: Complete every work package in Stage B (B01-B07).
  - Completed Work: Added the FastAPI and Worker composition roots, deterministic FakeQueue and complete Fake adapter bundle, a buildable Next.js Mock UI, a Port-only Agent Runtime stub, eleven capability Skill manifests, the scoped paper_reader_agent, and nine API-driven Fake end-to-end scenarios. Reconciled Repository Ports with mandatory Workspace isolation and aligned Fake LLM/Event/Parser contracts.
  - Verification: Python `pytest` 107 passed; frontend Vitest 18 passed; TypeScript type-check passed; Next.js production build passed; focused Ruff passed; focused Mypy passed for Stage B contracts and new runtime/API/Skill code.
  - Open Issues: Full-repository Ruff still reports legacy Stage A/old-stub formatting debt; Python has three `datetime.utcnow()` deprecation warnings in the pre-existing Conversation domain; npm audit reports 7 dependency vulnerabilities (4 moderate, 2 high, 1 critical); real infrastructure adapters remain Stage C work.
- Time: `2026-06-20 03:35 UTC`
  - Step: Start Stage C / C01 PostgreSQL and Alembic adapters.
  - Completed Work: Installed Stage C Python dependencies and Docker Desktop; added SQLAlchemy 2 models for core persistence entities, Workspace-filtered repository adapters, Unit of Work, soft deletion/reference counting, optimistic locking, Alembic configuration and initial pgvector-aware migration; added local contract/migration tests and a PostgreSQL Testcontainers integration test entry.
  - Verification: C01 local repository, Workspace isolation, soft-delete/reference-count, optimistic-lock and Alembic upgrade/downgrade tests pass (4 passed). PostgreSQL Testcontainers test is present but cannot run because Docker backend is unavailable.
  - Open Issues: C01 is blocked. Windows WSL and VirtualMachinePlatform features are disabled; enabling them requires an elevated Administrator terminal and a Windows restart. C02-C04 were not started because C01 has not passed its mandatory PostgreSQL container acceptance.
- Time: `2026-06-20 15:44 -04:00`
  - Step: Complete Stage C infrastructure adapters (C01-C04).
  - Completed Work: Revalidated and completed PostgreSQL/pgvector SQLAlchemy repositories and Alembic migrations; implemented Redis-backed durable task queues, Celery routing, cancellation, locks, retry/dead-letter and crash recovery; implemented MinIO object storage with Workspace isolation, SHA-256 deduplication, MIME/signature checks, reference counting and streaming uploads; implemented database-backed ordered task events and reliable SSE resume using Redis notifications.
  - Verification: Python full suite 120 passed including PostgreSQL, Redis and MinIO Testcontainers; frontend Vitest 18 passed; TypeScript check and Next.js production build passed; Stage C Ruff and Mypy passed.
  - Open Issues: Existing Domain factory methods still emit `datetime.utcnow()` deprecation warnings; Testcontainers Redis/MinIO waiting helper APIs emit upstream deprecation warnings; npm audit findings from Stage B remain unresolved.
- Time: `2026-06-20 16:31 -04:00`
  - Step: Complete Stage D conversation, workspace and memory work packages (D01-D05).
  - Completed Work: Added complete conversation/message history services; isolated conversation/task workspace views with manifests, promotion, recovery and security controls; searchable WorkspaceEntry indexes with source traceability; short-term MemorySegments with source-message replay and invalidation; long-term ConversationSummary and explicit MemoryPreference storage with cross-conversation/file retrieval and forgetting. Added Alembic migration 0002 for all Stage D tables and converted Domain timestamps to timezone-aware UTC.
  - Verification: Python full suite 133 passed; Stage D focused tests 13 passed; frontend Vitest 18 passed; TypeScript check and Next.js build passed; Stage D Ruff and Mypy passed. Workspace location, short-memory Recall@5/fact preservation, cross-conversation Recall@5 and historical-file location all achieved 100% on deterministic evaluation sets.
  - Open Issues: Testcontainers Redis/MinIO and Alembic emit upstream deprecation warnings; current deterministic embeddings are test adapters and will be replaced/evaluated in later model/RAG work packages.
- Time: `2026-06-20 20:40 -04:00`
  - Step: Complete Stage E real Agent Runtime work packages (E01-E07).
  - Completed Work: Added configuration-backed logical Model Profiles and ModelVersion manifests, an OpenAI-compatible client with explicit fallback and version Trace; implemented retrieval-first bounded requirement clarification, two-stage lazy Skill selection, structured DAG planning and bounded replanning, budgeted/cancellable/idempotent Tool and sub Agent execution with per-step persistence, source-aware context construction with Profile token limits, and deterministic Schema/claim/number/citation/invariant verification.
  - Verification: Python full suite 164 passed (Stage E focused suite 31 passed); frontend Vitest 18 passed; TypeScript type-check and Next.js production build passed; Ruff passed for all Stage E files; Mypy passed for all Stage E source modules. Deterministic evaluations achieved the required clarification, Skill Top-1/Top-3 and plan executability/dependency thresholds.
  - Open Issues: Stage F still owns full Tool permission/schema enforcement and real sub Agent lifecycle management; Stage G still owns production paper parsing/RAG evidence; the bundled model registry contains logical service names only and requires a configured inference endpoint for real calls.
- Time: `2026-06-20 22:20 -04:00`
  - Step: Complete Stage F Tool, Skill and sub Agent work packages (F01-F05).
  - Completed Work: Added a typed Tool Runtime with Registry/Skill whitelist, permission and confirmation gates, timeout/retry, task-scoped idempotency, bounded output/data_ref and Trace; implemented six Workspace Tools with Workspace/Task isolation, object storage and promotion audit; completed and strictly validated eleven capability Skill packages with version Trace; implemented the single-file paper_reader_agent with Paper Card evidence/missing fields and independent budget/Profile; added persistent parent-child sub Agent runs, Celery Group scheduling, concurrency/depth limits, partial-failure aggregation and cancellation propagation.
  - Verification: Python full suite 198 passed; frontend Vitest 18 passed; TypeScript type-check and Next.js production build passed; Ruff and Mypy passed for Stage F sources; Alembic upgrade/downgrade includes the new subagent_runs table.
  - Open Issues: Production paper parsing, document sections, hybrid retrieval and evidence generation remain Stage G; the current paper reader backend is a Port-driven implementation tested with deterministic backends until Stage G adapters replace them.
- Time: `2026-06-20 23:20 -04:00`
  - Step: Complete Stage G paper parsing and RAG work packages (G01-G05).
  - Completed Work: Added PyMuPDF layout parsing with pages/bbox/header-footer/column order/sections/quality; traceable PaddleOCR and Tesseract fallback adapters; parent-child traceable chunks with idempotent Embedding and deletion; PostgreSQL vector(1024), HNSW and FTS indexes; query rewrite, vector/keyword Top-30, RRF and reranker Top-8; program-assigned Claim-Citation answers with page targets, evidence checks and refusal. Integrated parse_document, search_document and get_document_section through the secured Tool Runtime.
  - Verification: Python full suite 215 passed; frontend Vitest 18 passed; TypeScript type-check and Next.js production build passed; Stage G focused tests include PostgreSQL Testcontainers real vector/FTS retrieval and a versioned 10-paper single/double-column structure truth set; Ruff and Mypy passed. Fixed evaluations achieved all character/page/column/section, retrieval Recall@5/10 and MRR, and citation correctness/support/refusal/hallucination gates.
  - Open Issues: OCR package/model installation remains deployment-configurable and ordinary CI uses a deterministic OCR Adapter; real-world quality still needs the planned curated 10-paper corpus before production claims. Stage H owns domain Paper Card, comparison and academic writing quality.
- Time: `2026-06-21 00:20 -04:00`
  - Step: Complete Stage H academic domain work packages (H01-H06).
  - Completed Work: Added evidence-bound Paper Card extraction; partial-failure-safe parallel Paper Card comparison with normalized matrices, numeric verification and supported conclusions; Writing Brief and Evidence Map with fact/opinion/inference classification; seven-section paragraph planning and review-required drafting; invariant-preserving compression/expansion/polish/restructure with regression checks; evidence-matrix-first literature reviews and draft Claim citation verification. Exposed all domain services through the secured Tool Runtime.
  - Verification: Python full suite 235 passed; frontend Vitest 18 passed; TypeScript type-check and Next.js production build passed; H-focused unit, metric and Tool integration tests passed; Ruff and Mypy passed. Fixed evaluations achieved Paper Card F1, comparison coverage/numeric/support, user-point recall, drafting coverage/structure/coherence/unsupported-fact, rewrite invariant/semantic/style, and 100% review fact traceability gates.
  - Open Issues: The deterministic fixtures prove domain rules and evidence boundaries, not human preference quality. Real 4B drafting/rewriting quality, latency and safety require separate Stage J model evaluation before production claims.
- Time: `2026-06-21 00:25 -04:00`
  - Step: Complete Stage I security, observability, evaluation and delivery work packages (I01-I06).
  - Completed Work: Added persistent redacted Trace Spans with task-chain reconstruction; Prompt Injection and malicious-file guards; a formal disabled SandboxExecutor with no ordinary Worker fallback; seven-level versioned evaluation reports; a ten-service Docker Compose deployment with health checks and explicit model-unavailable degradation; and executable final acceptance across ten user scenarios. Added deployment, evaluation, security and demo documentation.
  - Verification: Python full suite 254 passed with 6 upstream deprecation warnings; frontend Vitest 18 passed, TypeScript and Next.js production build passed; Stage I Ruff and Mypy passed. Docker built all images and ran web/api/worker/postgres/redis/minio/model-router/1.7B/4B/observability healthy. Final acceptance achieved 100% task completion, 0% dead loops, 100% citation support, deletion unavailability and adapter-free operation.
  - Open Issues: Model containers are explicit unavailable/degradation services until real weights and inference commands are configured; deterministic evaluation does not replace Stage J real-model/human evaluation. `npm ci` reports 7 dependency vulnerabilities (4 moderate, 2 high, 1 critical) that require a compatibility-reviewed Next.js dependency upgrade rather than an automatic breaking `--force` fix. The repository contains a demo script but no recorded demo video.
- Time: `2026-06-21 00:35 -04:00`
  - Step: Complete Stage J / J01 independent training project and data contracts.
  - Completed Work: Added a standalone `training` package with versioned Pydantic JSONL contracts, content-addressed exported Agent/Tool/TrainingSample schemas, dataset manifests, privacy/consent enforcement, paper/conversation split leakage detection, profile scale/gate catalog, a service-independent validation CLI and committed synthetic contract fixtures.
  - Verification: J01 focused suite 6 passed; standalone CLI validated the exported bundle and three-way fixture without API/database/Worker; Ruff and Mypy passed for all training sources.
  - Open Issues: The fixture contains only three synthetic contract examples and is not a trainable dataset. Real J02/J03 training requires the documented 2K–80K reviewed datasets, base weights and separate training dependencies.
- Time: `2026-06-21 00:40 -04:00`
  - Step: Audit and attempt Stage J / J02 1.7B SFT/RL prerequisites.
  - Completed Work: Added typed per-task training profiles for router, skill_selector, query_rewriter and tool_caller; added a fail-closed preflight checking dataset validity/minimum size, base model manifest, training modules and GPU VRAM; generated four machine-readable J02 preflight reports.
  - Verification: J02 profile/preflight suite 3 passed; training Ruff and Mypy passed. Hardware check detected 8.0 GiB VRAM. Every real task preflight exited with blocked status as designed.
  - Open Issues: No reviewed 2K–5K+ starting datasets exist at the required paths; `models/base/qwen3-1.7b/config.json` is absent; torch, transformers, datasets, peft, trl and accelerate are not installed. J02 is blocked, so J03 and J04 remain pending by work-package order. No Adapter or effectiveness claim was produced.
- Time: `2026-06-21 00:50 -04:00`
  - Step: Re-audit every Stage J work package and retry J02 prerequisites.
  - Completed Work: Re-read Stage J and repository policy, re-scanned training data/base/adapter directories, training modules and GPU capacity, refreshed all four 1.7B preflight reports, and confirmed J01 remains complete while J02 remains fail-closed.
  - Verification: Stage J focused tests 9 passed; Ruff and Mypy passed. Router, skill_selector, query_rewriter and tool_caller preflights each returned blocked exit code 2. GPU detection still passes at 8.0 GiB.
  - Open Issues: The required licensed/reviewed datasets, Qwen3-1.7B base model and training environment are still absent. J03 cannot start before J02 produces evaluated adapters; J04 cannot promote or roll back versions that do not exist.
- Time: `2026-06-21 01:00 -04:00`
  - Step: Add Windows one-click startup and browser shortcuts.
  - Completed Work: Added double-clickable start/stop CMD launchers and PowerShell orchestration scripts that start Docker Desktop when needed, create `.env`, run Docker Compose, wait for API/Web health, open the frontend and API documentation, and preserve named-volume data on shutdown.
  - Verification: PowerShell scripts pass parser validation and Compose configuration validation. The start script was run end to end, created `.env`, brought API/Web and dependencies to healthy status, and the stop script removed containers/network while preserving named volumes.
  - Open Issues: The first startup still needs network access to pull/build container images and may take several minutes.
- Time: `2026-06-21 12:05 -04:00`
  - Step: Fix one-click Compose startup after local `.env` creation.
  - Completed Work: Diagnosed the API restart loop as a local `.env` leaking into the Python image and being parsed by strict `ApiSettings`; excluded `.env` and environment variants from Docker build contexts while retaining `.env.example`, and added a deployment regression test.
  - Verification: API logs identified 31 forbidden extra settings; deployment regression and rebuilt Compose startup were run after the fix.
  - Open Issues: None.
- Time: `2026-06-21 12:20 -04:00`
  - Step: Replace the developer mock dashboard with a clean end-user chat home.
  - Completed Work: Removed all test fixtures, task diagnostics, clarification demos, Workspace/debug widgets and model-profile controls from the rendered home; added a restrained two-column PaperAgent shell with conversation navigation, central welcome state, integrated upload/message composer, user-facing quick actions and responsive mobile layout.
  - Verification: Frontend component tests cover absence of development panels and message submission; TypeScript and production build pass; local browser visual verification completed.
  - Open Issues: Navigation items and assistant responses remain UI-level placeholders until the corresponding production API routes are wired to the web client.
- Time: `2026-06-22 00:00`
  - Step: Complete K01 product-entry integration for conversations, uploads, PDF processing, retrieval, and model invocation.
  - Completed Work: Replaced the homepage Mock state with real Conversation/File/Task APIs; implemented new-conversation persistence, recent-conversation search and history restoration, Workspace file library, Composer-integrated PDF upload display, Redis-backed parse and main-agent tasks, a real Worker runtime, PyMuPDF parsing, document indexing, hybrid retrieval, evidence-grounded model prompts, task polling, CORS, Compose real-adapter wiring, and environment-driven OpenAI-compatible model configuration.
  - Verification: 265 Python tests passed; 22 Vitest tests passed; TypeScript type-check, Ruff on changed files, mypy on the API/Worker integration, Next.js production build, Docker Compose config/build/start, API/Web health checks, and live HTTP flow all passed. Live PDF upload reached `parsed`; the answer task reached the configured model boundary and failed explicitly because no model weights are mounted.
  - Open Issues: A real OpenAI-compatible Qwen 1.7B/4B endpoint or mounted model weights are still required for live answer generation. The in-app browser connector was unavailable because of a desktop sandbox metadata error, so UI behavior was verified by Vitest/build and live HTTP rather than interactive browser clicks.
- Time: `2026-06-22 01:30`
  - Step: Complete K02 model settings and real local model runtime.
  - Completed Work: Added the sidebar model-configuration page with independent small/large Base, SFT and RL selection; persisted selections in PostgreSQL; added Ollama catalog, availability checks, downloads and inference probes; routed every Worker model call through the current database selection; registered Qwen3 1.7B and Qwen3.5 4B as the default Base services.
  - Verification: Model runtime/API/Worker tests, Ruff, Mypy and frontend TypeScript checks passed. Ollama downloaded `qwen3:1.7b`; both `qwen3:1.7b` and `qwen3.5:4b` returned valid OpenAI-compatible chat completions on the local RTX 4070 Laptop GPU.
  - Open Issues: No trained SFT/RL artifacts have passed J02/J03/J04, so those groups correctly remain empty. Download time and disk usage for user-selected Base models depend on the selected Ollama model.
- Time: `2026-06-22 14:48 -04:00`
  - Step: Complete K03 clickable citations, bounded ReAct Self-RAG, retrieval repair, section context and token accounting.
  - Completed Work: Rendered message evidence as clickable `[E#]` controls; connected the product queue to a same-task `waiting_user`/resume loop; added 1.7B structured clarify/retrieve/answer decisions; replaced production Fake retrieval clients with multilingual hashing embeddings and lexical reranking; added section-title filtering and contiguous section expansion; persisted real prompt/completion token usage by conversation and model role; added a collapsible right-side live usage panel.
  - Verification: 270 non-container Python tests passed and the 9 previously blocked Testcontainers integration tests passed after Docker started; 24 Vitest tests, TypeScript, Next.js build, Ruff and Mypy passed. Fixed 15-query bilingual retrieval evaluation achieved Pass@5 1.00, Recall@10 1.00 and MRR@10 1.00. A real multi-section PDF run used Qwen3 1.7B for Self-RAG and Qwen3.5 4B for the answer, retrieved only `3 Experiments`, exposed the evidence quote, and recorded 179 small-model plus 544 large-model tokens.
  - Open Issues: The deterministic Pass@5 set validates the repaired component and bilingual ranking behavior but is not a substitute for a larger manually labeled real-paper benchmark. Frontend tests still emit non-failing React `act(...)` warnings from asynchronous initial fetches.
- Time: `2026-06-22 15:05 -04:00`
  - Step: Review and rewrite the section-aware RAG implementation plan for Codex handoff.
  - Completed Work: Replaced the generic parallel `self_rag/` design with a repository-specific K04 plan that reuses the current layout parser, DocumentSection schema, parent/child chunker, PostgreSQL index, HybridRetriever and ReAct Self-RAG. Added section-tree persistence, deterministic reference parsing, ambiguity handling, separate section-QA/section-summary retrieval, automatic legacy reindexing, privacy-safe traces, four bounded subpackages and measurable real-paper acceptance gates.
  - Verification: Cross-checked every planned integration point against the current repository files and preserved the existing page/bbox/block citation truth. No business code was changed.
  - Open Issues: K04 implementation and its manually labeled 10-paper/100-query section benchmark have not started.
- Time: `2026-06-22 16:10 -04:00`
  - Step: Complete K04.1 section schema, parsing tree, persistence and migration.
  - Completed Work: Extended parsed sections with numbering, normalized titles, parent links, section paths, heading/direct/descendant block identities and ordinal order; added TOC and citation false-positive rejection; persisted a document section catalog and section-aware chunk metadata; invalidated the idempotent shortcut for legacy indexes without the current section schema.
  - Verification: 281 Python tests passed, including synthetic multi-level PDF section parsing, chunk/catalog persistence, SQLite migration upgrade/downgrade and PostgreSQL container migration upgrade/downgrade. Ruff and Mypy passed on changed source.
  - Open Issues: K04.2 reference parsing/resolution and the manually labeled real-paper section benchmark remain pending.
- Time: `2026-06-22 16:24 -04:00`
  - Step: Complete K04.2 deterministic section reference parsing and resolution.
  - Completed Work: Added Pydantic section-reference, context, candidate and resolution contracts; deterministic Chinese/English/number/Roman/appendix/deictic parsing; versioned bilingual aliases; exact, alias and calibrated fuzzy resolution; fail-closed missing-number behavior; ambiguity candidates and clarification questions.
  - Verification: 294 Python tests passed. The fixed 100-query benchmark achieved Top-1 1.00, number exact 1.00, alias Top-1 1.00, fuzzy Top-1 1.00, false forced match 0.00, unresolved rejection 1.00 and ambiguity clarification 1.00. Ruff and Mypy passed.
  - Open Issues: The benchmark is deterministic and catalog-level; K04.3 scoped retrieval and K04.4 real-paper/Self-RAG E2E remain pending.
- Time: `2026-06-23 00:00 -04:00`
  - Step: Start K04.3 product-entry reliability and multi-retriever Self-RAG repairs.
  - Completed Work: Added startup Alembic migration for real API/Worker so old Docker volumes gain new `document_chunks` section columns; refactored `HybridRetriever` into ExactMatch, Section scope, Vector, BM25, RRF merger and Reranker stages; fixed local retrieval token punctuation handling; made production fail closed for Fake adapter/demo usage; changed Windows startup to reuse images/volumes by default and documented explicit `-Build`/`-RemoveVolumes`.
  - Verification: Focused regression suite passed: `tests/test_postgres_adapter.py`, `tests/test_hybrid_retrieval.py`, `tests/test_product_workflow.py`, `tests/test_model_configuration.py` (17 passed, Alembic deprecation warnings only).
  - Open Issues: K04.3 full section-summary retrieval, long-section compression, broader RAG regression and K04.4 real-paper/Self-RAG E2E remain pending.
- Time: `2026-06-23 00:30 -04:00`
  - Step: Fix ultra-short Qwen/Ollama answers in product QA.
  - Completed Work: Moved `/no_think` control into the user prompt for runtime-selected Ollama calls; stripped `<think>...</think>` blocks from OpenAI-compatible chat responses; added product-level short-answer detection with one automatic retry before saving the assistant message.
  - Verification: `tests/test_model_runtime.py` and `tests/test_product_workflow.py` passed (15 passed). Ruff passed on changed Python files.
  - Open Issues: The live browser flow should be retried against the running Ollama model to confirm the specific uploaded paper now receives a substantive answer.

- Time: `2026-06-23 01:15 -04:00`
  - Step: Fix disappearing composer layout and add destructive conversation cleanup.
  - Completed Work: Reverted the previous busy-state composer change; diagnosed the missing input as CSS grid overflow from the asynchronously loaded recent-conversation list; constrained the sidebar, chat surface and usage panel to viewport-height scrolling; added `DELETE /api/v1/conversations/{conversation_id}`; added a recent-conversation delete button with confirmation; deletion now clears the conversation, messages, conversation-file/message-file links, associated files, object-store objects, parsed documents, section catalogs, chunks, workspace indexes, memory summaries and usage rows.
  - Verification: `tests/test_product_workflow.py` passed (6 passed); `npm.cmd test -- --run src/components/__tests__/components.test.tsx` passed (25 passed); `npm.cmd run build` passed; Docker `web` image rebuild and browser geometry check confirmed the Composer stays inside the 720px viewport; Ruff passed on changed backend files.
  - Open Issues: Existing non-failing React `act(...)` warnings remain in the component test output.

- Time: `2026-06-23 15:30 -04:00`
  - Step: Verify conversation deletion in the running system and remove old demo/mock code.
  - Completed Work: Traced failed UI deletes to the running API container still serving the old image, where `DELETE /api/v1/conversations/{id}` returned 405; rebuilt and restarted API/Web; verified temporary conversations are removed from the live list and return 404 after deletion. Removed unused frontend mock/demo components and mock data files, removed the old `/api/v1/demo/{scenario}` route and `FakeScenarioRunner`, and updated docs so future work targets the real product entry.
  - Verification: Live API deletion check passed (`before_contains=1`, `after_contains=0`); old demo route returns 404; `tests/test_api_app.py tests/test_product_workflow.py` passed (12 passed); frontend component suite passed (18 passed); Next.js production build passed; Ruff passed on changed backend files.
  - Open Issues: Frontend Vitest still emits existing non-failing React `act(...)` warnings in several AppLayout tests.

- Time: `2026-06-23 16:45 -04:00`
  - Step: Fix main-page upload `Failed to fetch` after frontend API client cleanup.
  - Completed Work: Restored the product API client as a tracked frontend source by unignoring `apps/web/src/lib/`; changed the default frontend API base to same-origin `/api/v1`; added a Next.js rewrite proxy to FastAPI; configured Docker Compose Web with `API_INTERNAL_URL=http://api:8000`; improved network-error wording; updated the upload/delete frontend test expectation and documentation.
  - Verification: Frontend component suite passed (18 passed) with existing non-failing React `act(...)` warnings; TypeScript passed; `tests/test_api_app.py tests/test_product_workflow.py` passed (12 passed). `npm.cmd run build` started but timed out twice after printing the Next.js version and no error stack.
  - Open Issues: Production build timeout still needs a separate environment check if it reproduces outside this sandbox; pytest emitted a cache write warning because the sandbox user cannot write `.pytest_cache`.

- Time: `2026-06-23 17:20 -04:00`
  - Step: Fix duplicate PDF upload after conversation/file deletion.
  - Completed Work: Diagnosed upload `Failed to fetch` as a backend `uq_file_workspace_checksum` violation when re-uploading a PDF whose checksum already existed in a soft-deleted File row. Updated product upload logic to reuse active files, restore soft-deleted files, refresh object storage when needed, and restore deleted conversation-file links instead of inserting a duplicate File row.
  - Verification: `tests/test_product_workflow.py` passed (7 passed); Ruff passed on changed upload code and tests; rebuilt and restarted API container; live API duplicate-upload check returned HTTP 200 twice with the same file id.
  - Open Issues: None.

- Time: `2026-06-24 00:50 -04:00`
  - Step: Add parse and retrieval diagnostics for RAG debugging.
  - Completed Work: Added `GET /api/v1/debug/files/{file_id}/parse` and `POST /api/v1/debug/retrieval/preview`; exposed parsed section trees, chunks, ExactMatch, Section, Vector, BM25, merged, reranked and final-context hits; added a main-page debug panel beside uploaded file tags; mounted `rag_diagnostics/` so API exports JSON/MD diagnostics to the project directory.
  - Verification: `tests/test_product_workflow.py` passed (9 passed); Ruff passed on changed backend files; frontend component suite passed (18 passed); `npm.cmd run build` passed.
  - Open Issues: The diagnostic endpoint mirrors the current deterministic local retriever stages and is intended for debugging; broader real-paper retrieval quality still belongs to the remaining K04.3/K04.4 evaluation work.

- Time: `2026-07-21 14:13 -04:00`
  - Step: Define the post-K04 Agent-system deepening roadmap for interview-oriented implementation.
  - Completed Work: Added `develop_guide/Agent系统四方向深化实施计划.md` with 27 bounded work packages across trustworthy evaluation baselines, dynamic Plan-and-Execute/Replan, role-based multi-agent collaboration, real 1.7B QLoRA training and confidence-aware 1.7B/4B model cascading, plus unified delivery; documented dependencies, objectives, implementation scope, artifacts, quantitative acceptance gates, test matrix, risks, status tracking and resume evidence rules. Linked the roadmap from README and recorded its product-architecture direction without claiming planned capabilities as completed.
  - Verification: Confirmed the UTF-8 Markdown file exists, contains 1,018 lines, includes all L00–P05 work-package headings, and has intact beginning/end content.
  - Open Issues: K04.3/K04.4 remain prerequisites; real training remains blocked until audited datasets, the 1.7B base model, training dependencies and GPU resources pass O00 preflight.

- Time: `2026-07-21 15:20 -04:00`
  - Step: Complete K04.3 exact section QA and summary retrieval without replacing the existing RAG architecture.
  - Completed Work: Added a backward-compatible `HybridRetriever.search_section` path that resolves deterministic section references against the workspace/file-scoped section catalog, applies SQL `section_id` filtering with parent/descendant expansion, reranks section QA and adds adjacent chunks, and preserves document order for section summaries with deterministic head/middle/tail and per-descendant coverage under context pressure. Integrated the result into the existing Self-RAG product path so missing or ambiguous sections ask for clarification instead of falling back to the whole paper, and persisted retrieval mode, selected section, scope, match kind and truncation metadata while retaining original page/bbox evidence.
  - Verification: Added failing-first regression tests for parent scope, exact child scope, adjacent QA context, long-section coverage compression, cross-file ambiguity, missing-section clarification and persisted summary metadata. K04.1–K04.3 related suite passed (39 tests); Ruff passed on changed files; mypy passed for `rag/retrieval.py`. A broader pre-existing mypy check still reports the unrelated `MessageFileModel`/`ConversationFileModel` assignment at `apps/api/product_service.py:251`.
  - Open Issues: K04.4 still requires old-index version rebuild verification, privacy-safe Trace integration, citation validation and real multi-section PDF E2E/full regression before K04 as a whole can be marked completed.

- Time: `2026-07-21 16:30 -04:00`
  - Step: Complete K04.4 old-index rebuilding, privacy-safe tracing, citation validation and multi-section PDF E2E.
  - Completed Work: Added explicit index/schema version metadata and `DocumentIndexer.is_current` checks for checksum, catalog, chunk section identity and embedding model; the existing parse/index pipeline now automatically rebuilds stale derived indexes before answering. Injected the existing `SqlAlchemyTraceWriter` into the production Worker and recorded structured `document.index`, `agent.react`, `rag.retrieve`, `verification.complete` and `task.completed` spans without questions, paper text or hidden reasoning. Reused the deterministic Verifier to reject unknown `[E#]` references before message persistence. Added a real three-page PDF-format E2E that seeds a stale index and proves automatic replacement, exact section 2/Methods scope, page-2 evidence and stale-evidence removal. Renamed two local ORM loop variables to resolve an existing mypy type collision without behavior change.
  - Verification: K04/citation/trace/security suite passed (63 tests); MinIO/Redis/SSE integration suite passed (8 tests); full Docker-enabled project suite passed (303 tests). Ruff passed on changed files; mypy passed for indexing, retrieval, product service and Worker; diff formatting check pending final handoff.
  - Open Issues: No K04 implementation blocker remains. Real external Ollama generation was not rerun in this work package; K02/K03 already retain its separate acceptance, while this K04 E2E uses a deterministic LLM test double with real PDF parsing, storage, indexing, retrieval, verification and persistence.

- Time: `2026-07-21 17:45 -04:00`
  - Step: Complete L00 current-state audit and freeze trustworthy comparison baselines.
  - Completed Work: Added strict Pydantic/YAML configurations for Vanilla RAG, fixed Workflow, bounded ReAct and full-4B baselines, all executed through the existing evaluation CLI/Runner with stable configuration hashes. Evaluation metadata now records Commit and dirty-worktree state. Added truth classes and fail-closed gates so Fake/fixture runs cannot be reported as real effect metrics. Recorded the hardware/software environment, audited actual Planner/ReAct/multi-agent/training boundaries, and added ADR 0010 to preserve the custom state machine while allowing future framework capabilities only through Ports/Adapters.
  - Verification: `tests/test_evaluation_baselines.py tests/test_evaluation_framework.py tests/test_final_acceptance.py` passed (6 tests); Ruff passed on all L00 Python files; mypy passed for the three changed evaluation modules.
  - Open Issues: L00 establishes comparability and honesty gates but does not claim a quality improvement. L01 must freeze provenance-aware datasets and case contracts before any real-model baseline score is published.

- Time: `2026-07-21 18:30 -04:00`
  - Step: Complete L01 evaluation task taxonomy and provenance-aware dataset contracts.
  - Completed Work: Added strict L1-L6 EvaluationCase, ExpectedTrajectory, ReferenceAnswer, EvidenceGold and JudgeResult schemas with source authorization, resource budgets, unacceptable behaviors and evaluation-only test semantics. Added a JSONL loader and fail-closed audit that rejects duplicate IDs, unauthorized or unconsented private sources, missing gold evidence, and cross-split leakage by paper, conversation, source cluster, text fingerprint or versioned embedding cluster. Added contract-only dataset/split manifests and a dataset card documenting intended use, bias, privacy and the prohibition on using the test set for few-shot, SFT, DPO or threshold tuning.
  - Verification: Failing-first import test was observed before implementation. `tests/test_evaluation_dataset_contracts.py` passed (9 tests); Ruff passed for the dataset package and tests; mypy passed for all three dataset source modules.
  - Open Issues: L01 intentionally contains no claimed real evaluation cases or quality scores. L02 must construct, double-annotate and audit the fixed 300-case real test set.

- Time: `2026-07-21 20:15 -04:00`
  - Step: Complete L02 fixed real-public evaluation dataset release.
  - Completed Work: Downloaded and hash-pinned official QASPER v0.3 and CSL Benchmark test sources into a Git-ignored scratch cache; added a deterministic builder that emits exactly 300 evaluation-only cases with L1-L6 distribution 60/60/60/45/45/30, 240 English and 60 Chinese cases, 476 source-document records, provenance/license/resource/trajectory metadata and slice dimensions. The release contains 218 evidence tasks and 657 Gold spans whose rendered page, section and claim relationship are verified against canonical logical pages. Added deterministic single-column, double-column and grayscale degraded-scan PDF rendering with three checked-in samples. Preserved 30 stratified QASPER dual-annotator labels (10% of release) under a disclosed consensus-gold policy; Cohen's kappa is 1.0. Added missing-section, citation-ambiguity, prompt-injection, tool-failure, partial-failure, cancellation and clarification cases without claiming derived prompts were original human annotations.
  - Verification: Failing-first L02 import was observed. L02 tests passed (7); L00-L02 combined regression passed (21); all 657 evidence spans were located on their declared pages; Ruff and mypy passed for the full dataset package. A second independent build matched SHA-256 for cases, documents, annotation/split/dataset manifests and all PDF samples.
  - Open Issues: L02 contains no model outputs or quality claims. English full-text coverage is NLP-heavy; Chinese cases are metadata/abstract-level; fluent L5 review quality still requires the L03 human/LLM Judge path and L04/L05 real-model execution.

- Time: `2026-07-21 21:30 -04:00`
  - Step: Complete L03 unified metrics, statistical comparison and rule-first Judge system.
  - Completed Work: Added an executable catalog for 33 effect, routing, trajectory, efficiency, cost and robustness metrics, each with direction, unit, formula, denominator, applicability and outlier policy, plus a reproducible Markdown export. Added strict per-case metric records, metric aggregation that keeps schema validity separate from task correctness, seeded percentile-bootstrap 95% confidence intervals and paired-bootstrap candidate-vs-baseline deltas. Added a structured Judge system that uses deterministic rules first, invokes an injected LLM Judge Port only for semantic abstentions, rejects unknown Evidence IDs, records public reason/evidence/Profile/version fields and escalates unstable three-run decisions to a human Port. Generated a deterministic 50-case calibration report from L02 QASPER human-reference Gold: 25 exact-reference positives and 25 controlled missing-evidence negatives.
  - Verification: Failing-first L03 import was observed. L03 tests passed (8); L00-L03 combined regression passed (29); all 33 metric definitions contain required documentation; 50-case agreement and three-run consistency were both 1.0; calibration report hash reproduced exactly; Ruff and mypy passed for eight L03 source modules.
  - Open Issues: The calibration run is `integration_real` with `human_review` Gold provenance and validates clear programmatic rules; it does not establish real LLM semantic-Judge accuracy. L04 must add resumable real execution, Trace replay and version-complete reports before L05 can publish baseline effects.

- Time: `2026-07-21 17:03 -04:00`
  - Step: Complete L04 resumable experiment Runner, Trace replay and deterministic reporting.
  - Completed Work: Added an evaluation-only ExperimentExecutor/Runner without changing the production Agent Runtime; implemented deterministic per-case seeds, bounded retry, thread concurrency, case/model-call/token budget reservation, configuration-checked resume and atomic per-case checkpoints. Added closed routing/planning/retrieval/tool-parameter/generation/verification/system/data error taxonomy; replay by case_id or task_id for decisions, Plan versions, actions, observations, model calls, Tool results and budget deltas; enforced model/profile/version/usage on every reported model call; emitted stable JSON, Markdown and Dashboard bundles with B0/B1/B2/B3/candidate comparison ordering. Added separate smoke and explicitly gated real-model commands.
  - Verification: L04 unit suite passed (16 tests); the fixed L02 300-case contract smoke completed with 0 unclassified exceptions and 0.0% system exceptions; its report is explicitly `unit_fake`. Ruff and mypy passed for the L04 modules and tests; combined L00-L04 regression passed.
  - Open Issues: L04 proves execution/recovery/reporting mechanics only. L05 must run all four Baselines with real Model Profiles and frozen retriever/prompt versions before any effect, token, latency or cost comparison is published.

- Time: `2026-07-21 18:47 -04:00`
  - Step: Complete L05 real-model baseline measurement and freeze Go/No-Go gates.
  - Completed Work: Added a version-pinned offline Baseline Executor that reuses the frozen L02 cases/documents and production-equivalent exact/vector/BM25/RRF/lexical reranking without exposing Gold to retrieval or generation. Ran B0 Vanilla RAG, B1 fixed Workflow, B2 bounded 1.7B ReAct and B3 full-4B on all 300 cases each with local qwen3:1.7b/qwen3.5:4b. Added post-generation scoring, difficulty/task-family slices, closed actionable error attribution, seeded 95% CI, paired B0 deltas, Token/latency/4B-call summaries, replay indexes, Dashboard data and a SHA-256 frozen artifact Manifest.
  - Verification: 1,200 unique system/case results and 1,800 real model calls completed; 100% calls contain model/profile/version/input/output/latency usage, zero calls have empty usage, all attempts completed on attempt 1, and system exception rate is 0%. Task Success B0/B1/B2/B3 is 8.0%/6.33%/6.33%/7.0%; all paired success deltas versus B0 have 95% CI crossing zero. Highest actionable failure classes are verification, generation and routing. L05 unit tests, L00-L05 combined regression, Ruff, mypy and diff checks passed.
  - Open Issues: Baseline quality is low and no system is statistically better than B0. The offline retriever is production-equivalent deterministic local retrieval rather than PostgreSQL service deployment; the report supports offline model/retrieval comparison, not production-load claims. M01 should improve structured planning while preserving this frozen test/report boundary.

- Time: `2026-07-21 19:39 -04:00`
  - Step: Complete M01 Planner/Trajectory Schema V2.
  - Completed Work: Extended the existing Pydantic Planner contract without replacing the explicit Agent state machine. Added versioned Plan identity/parentage, assumptions, global and per-step budgets, step type/input refs/output schema/evidence/risk/fallback/completion predicates, structured Observation usage and quality signals, immutable add/remove/update Plan Patch with optimistic base-version checks, version-diff Trace, permission-aware Registry validation and explicit V1 migration.
  - Verification: 100 valid/invalid fixtures were classified with 100% accuracy; M01 plus legacy Planner/Executor regression passed (14 tests); Ruff and mypy passed.
  - Open Issues: M01 defines and validates plans but does not yet generate them with a model. M02 must add bounded 4B structured generation, repair, fast path and safe fixed-workflow fallback.

- Time: `2026-07-21 20:57 -04:00`
  - Step: Complete M02 constrained LLM Planner and real-model acceptance.
  - Completed Work: Added a bounded qwen3.5:4b Planner through the existing schema-generation Port without replacing the state machine. Context is limited to the Requirement Brief, Top-K permitted Skills, permitted Tool/Sub-agent schemas, Memory/RAG summaries and budget. Added L1/L2 Fast Path, Plan V2 validation across Schema/Registry/permissions/DAG/budget, generic academic workflow contracts, one structured repair attempt and Registry-constrained safe workflows including explicit missing-section clarification. Trace records model/profile/version/prompt version, usage, latency, repair and fallback reason without persisting hidden reasoning. Evaluation checkpoints now preserve public Plan-step summaries for audit and support per-difficulty partial runs.
  - Verification: M02 plus adjacent M01/legacy Planner/Executor regression passed (19 tests); M02 unit suite passed (6 tests); Ruff and mypy passed. A fresh 270-case `offline_real_model` run produced 100% final Plan schema validity, zero illegal Registry/permission calls, 3.0 average L1/L2 steps and 100% safe outcomes. L3-L5 Required Step Recall was 96.84% versus B1 36.0%, a +60.84pp paired-bootstrap improvement with 95% CI [55.82pp, 65.25pp].
  - Open Issues: Only 46.67% of model-backed plans passed directly and 53.33% used the safe fallback, so the result demonstrates a robust constrained planning system rather than high native 4B planning reliability. M03 must evaluate completion from observations/evidence before M04 can replan strategically.

- Time: `2026-07-21 21:18 -04:00`
  - Step: Complete M03 programmatic completion and evidence-sufficiency evaluation.
  - Completed Work: Added a strict CompletionEvaluator as an independent Runtime component that consumes existing PlanStep completion predicates and emits existing structured Observations. It checks non-empty/schema-complete outputs, factual claim-to-evidence linkage, trusted source and positive page provenance, minimum evidence, comparison target-paper coverage, numeric verification, writing Evidence Map coverage, immutable terms, pending-review flags and minimum quality. It selects complete, repair, replan, ask_user or fail based on actionable quality state and bounded repairs, and records evidence references, seven coverage/quality signals and specific missing items for M04.
  - Verification: Failing-first import was observed. All 50 manually labelled fixtures in which the Tool transport succeeded but the result was inadequate were rejected as incomplete (0% miss rate); decision agreement was 50/50 (100%), above the 90% gate. M03 plus adjacent Verifier, M01/M02 Planner and Executor regression passed (24 tests); Ruff and mypy passed after the public Runtime export was checked.
  - Open Issues: M03 returns actionable Observations but intentionally does not mutate a Plan or integrate execution control. M04 must map these signals to bounded repair/replan strategies; M05 will integrate both into the dynamic Executor.

- Time: `2026-07-21 21:42 -04:00`
  - Step: Complete M04 failure-aware strategy Replanner.
  - Completed Work: Added an independent StrategyReplanner that classifies empty retrieval, ambiguous section, Tool timeout, invalid arguments, insufficient evidence, budget pressure, Sub-agent partial failure and verification failure. Each class has an ordered, bounded strategy set spanning query rewrite, scope expansion, alternate permitted Tool, argument repair, model escalation, evidence acquisition, partial aggregation, ask-user, context compression, candidate reduction and explicit degraded output. Replans emit immutable PlanPatch and public reasons. A stable Observation fingerprint plus StrategyAttempt history prevents the same strategy on the same input from repeating; cancellation and the existing two-replan limit fail closed. Step budgets may only be reduced against remaining resources, and alternate Tools must pass Registry and permission checks.
  - Verification: Failing-first import was observed. Eight failure classes and 16 deterministic fault injections produced observable non-retry strategy changes; strategy outcomes applied successfully in 16/16 versus 2/16 scenarios labelled recoverable by the legacy retry baseline, a +87.5pp fixture improvement. Loop rate was zero, third replans were rejected, and budget/permission/cancellation gates remained effective. M01-M04 plus legacy Planner/Executor regression passed (37 tests); Ruff and mypy passed.
  - Open Issues: This is `unit_fixture` mechanism evidence, not a real-model Task Success claim. M05 must integrate Planner, CompletionEvaluator and StrategyReplanner into resumable dynamic execution before M06 can run frozen baseline comparisons.

- Time: `2026-07-21 22:14 -04:00`
  - Step: Complete M05 dynamic Plan-and-Execute Runtime and recovery semantics.
  - Completed Work: Added a compatibility DynamicPlanExecutor above the legacy PlanExecutor. It claims ready steps by Plan version and DAG dependencies, runs only dependency-free and side-effect-compatible batches, injects dependency outputs identically in serial/parallel execution, and connects successful results to the M03 CompletionEvaluator and inadequate observations to the M04 StrategyReplanner. Added a revision-CAS DynamicExecutionStore Port/checkpoint containing Plan, outputs, Observations, Strategy history, stable inflight idempotency keys, usage, remaining budget and public Trace. Action Runner calls use stable task/Plan/version/step keys; crash recovery reuses the same key, while budget is deducted only with the atomic result/Observation commit. Cancellation propagates through asyncio tasks and terminal checkpoints never claim new work.
  - Verification: Failing-first import was observed. A process-crash-after-side-effect fixture resumed with two Runner calls but one Artifact write, one committed step and one budget deduction. Parallel and serial dependency outputs matched; independent reads reached concurrency two while identical side-effect groups stayed at one. Twenty running-action cancellation injections had empirical P95 below two seconds. A bad evidence result produced repair Observation, Plan version 2 and a consistent successful second Observation/Trace. M01-M05 plus legacy Planner/Executor regression passed (42 tests); Ruff and mypy passed.
  - Open Issues: The checked implementation provides the durable Store/Runner Ports and an in-memory CAS Adapter for deterministic acceptance; production PostgreSQL/queue wiring remains a P-stage integration concern. M06 must measure Planner/replan contributions against frozen L05 baselines before M is claimed complete.

- Time: `2026-07-21 23:32 -04:00`
  - Step: Complete M06 five-group real-model Planner ablation and record a No-Go decision.
  - Completed Work: Added a resumable M06 executor/CLI that holds qwen3.5:4b, the production-equivalent hybrid retriever, answer prompt, frozen L02 cases and maximum per-case budget constant while progressively enabling Plan V2, Completion and Completion+Strategy Replan. Reused frozen B1 fixed Workflow and B3 full-4B ReAct scores rather than spending duplicate compute. Control prompts never receive reference answers or required Gold evidence. Added post-run case scoring, invalid Tool/recovery/loop/unauthorized/cost gates, paired-bootstrap 95% Task Success delta, Markdown summary and SHA-256 artifact Manifest.
  - Verification: Three candidates each completed all 180 L3-L6 cases (540 candidate results) with 1,497 real qwen3.5:4b calls, complete model/profile/version/usage metadata, zero system errors and zero Runner retries. The five-group matrix is complete. The full candidate achieved 6.67% L3-L5 Task Success versus 5.33% for the best old baseline: +1.33pp with paired 95% CI [-3.33pp, 6.00pp]. Old and candidate actual invalid Tool Call rates were both zero, recovery-rate delta was zero, 28 replans yielded no successful recovery, and Token per successful task increased 78.55%. Zero-loop/zero-severe-unauthorized and matrix-completeness gates passed; four promotion gates failed. M06 tests, Ruff and mypy passed.
  - Open Issues: M is a mechanism-complete but effect No-Go stage. The dynamic Planner path must remain opt-in/non-default; the frozen test set must not be used for prompt or threshold tuning. N01 may proceed because it depends on M01, but N claims must use their own evidence and must not assume M06 proved a benefit.

- Time: `2026-07-21 23:55 -04:00`
  - Step: Complete N01 role manifests and reference-only collaboration protocol.
  - Completed Work: Added strict Pydantic contracts for six role manifests, budgets, failure policies, ArtifactRef/DataRef and cross-role MessageEnvelope; added independent YAML manifests and JSON input/output Schemas for Coordinator, Paper Reader, Evidence, Critic, Writer and Verifier. Tool authorization fails closed, child roles cannot message users or spawn agents, and Coordinator explicitly degrades an unavailable optional Critic or fails for unavailable required roles. Documented data ownership, conflict preservation, timeout, bounded retry and cancellation semantics without replacing the existing Agent Runtime.
  - Verification: N01 protocol tests passed (5); combined N01 and existing SubAgent regression passed (14); Ruff and mypy passed. All six example inputs/outputs validate independently and all six roles reject an out-of-whitelist Tool.
  - Open Issues: N01 defines contracts and policy only; it does not yet provide persistent shared evidence state or production orchestration. N02 must implement an auditable Evidence Blackboard using existing workspace isolation and persistence boundaries.

- Time: `2026-07-21 23:59 -04:00`
  - Step: Complete N02 persistent Evidence Blackboard.
  - Completed Work: Added eight typed Blackboard entity kinds with producer, source, citation/page or inference marker, immutable version, confidence and payload; added an append-only Blackboard Repository Port with deterministic rebuild. Implemented matching in-memory and SQLAlchemy Adapters, expected-version optimistic locking, workspace/task isolation, source-file/message invalidation, current-state and immutable event tables, and Alembic migration 0009. Existing runtime and repository interfaces were not replaced.
  - Verification: N02 contract tests passed against both Fake and SQLite-backed SQLAlchemy Adapters (5); N01/N02 plus existing PostgreSQL/SubAgent regression passed (20); Ruff and mypy passed. Stale writes fail with FAILED_PRECONDITION, previous versions remain in the event stream, deleted-source evidence is excluded from active retrieval, and rebuilt state equals stored current state.
  - Open Issues: N02 exposes persistence and invalidation operations but does not yet wire file deletion orchestration or production role scheduling; those integration concerns remain for P01. N03 now provides bounded Coordinator execution over this Port.

- Time: `2026-07-22 00:08 -04:00`
  - Step: Complete N03 budgeted Coordinator and role-task DAG dispatch.
  - Completed Work: Added a compatibility Coordinator that expands a Plan V2 spawn_subagents step into one Reader per unique paper followed by Evidence, Critic, Writer and Verifier dependencies. Added assignment/token/worker/concurrency budgets, stable idempotency keys, depth-one enforcement, role output Schema and minimum-evidence checks before optional Blackboard writes, bounded timeout, cancellation and explicit partial-failure summaries. Existing DynamicPlanExecutor and SubAgentManager were preserved.
  - Verification: N03 tests passed for 2/5/10 papers, depth one, duplicate elimination, bounded timeout/cancellation and partial Reader failure. Five-paper measured wall-clock was at least 30% below serial in the deterministic delayed-runner fixture; fivefold duplicate requests reduced Reader calls by 80%. N01-N03 plus M05/legacy SubAgent regression passed (27); Ruff and mypy passed.
  - Open Issues: The latency result is a deterministic component measurement, not a production Worker/GPU benchmark. P01 must wire the Coordinator to durable queue/runtime infrastructure and measure production latency. N04 now adds the bounded review loop.

- Time: `2026-07-22 00:18 -04:00`
  - Step: Complete N04 bounded Critic—Writer—Verifier review loop.
  - Completed Work: Added strict Evidence Matrix, Critic issue, Writer resolution/draft and Verifier finding contracts plus a bounded collaboration state machine. It runs exactly one Critic pass, requires every issue to receive a non-open resolution, performs independent per-Claim Matrix/citation/inference checks, permits at most one Verifier-driven Writer revision, re-verifies once, and preserves unresolved conflicts for final disclosure. Internal traceability checks cannot be bypassed by a permissive role Adapter.
  - Verification: N04 tests passed (2). A 100-claim deterministic fixture ended with 0% severe unsupported claims, 90% conflict Recall and 90% Precision; one Critic pass and one Verifier revision were enforced. N01-N04 plus Dynamic Executor, legacy SubAgent and existing Verifier regression passed (33); Ruff and mypy passed.
  - Open Issues: These are component-fixture quality metrics, not real 4B effect claims. N05 must run the fixed-model, fixed-paper, fixed-budget ablation before role promotion decisions.

- Time: `2026-07-22 00:45 -04:00`
  - Step: Complete N05 six-group real-model multi-Agent ablation and record a No-Go decision.
  - Completed Work: Added a resumable five-call progressive role executor and CLI over the frozen L4/L5 set, reusing L05 B3 as Single Agent and emitting Reader Parallel, Evidence, Critic, Verifier and Full stage scores. Added paired Task Success CI, Claim Support/omission, Token/latency, role marginal contribution, fail-closed missing-denominator gates, Markdown/JSON/case-score reports and SHA-256 Manifest. Added a promotion policy that keeps Single Agent as production default, limits Critic to experiments, merges Verifier with the deterministic evidence gate and disables the extra LLM verification/full revision path.
  - Verification: Six systems each contain 90 cases. The 90 candidate pipelines produced 450 qwen3.5:4b calls; 450/450 have model/profile/version/usage metadata, zero have empty usage, and all cases completed on attempt one. Full versus Single: Claim Support +5.63pp, Task Success -1.11pp with paired 95% CI [-3.33pp, 0], mean total Token +398.03%. Critic-to-Verifier added 886.6 Token and 6.61s with zero Task Success/Claim Support gain; Full revision reduced Claim Support 2.07pp. N01-N05 final regression passed (40), Ruff and mypy passed. The non-Docker full suite passed 395 tests; the unrestricted suite reached the same 395 passes and one skip but reported eight setup errors because the local Docker Engine pipe was unavailable for MinIO/Redis/SSE testcontainers.
  - Open Issues: N05 is effect No-Go: only the six-group completeness gate passed. Frozen L4/L5 lacks conflict Gold and the old Single-Agent report lacks claim-level severe-unsupported annotations, so those gates are unavailable and fail closed. Multi-Agent must remain non-default until a new development set and independently labelled conflict/unsupported-fact evaluation demonstrate benefit; the frozen test set must not be tuned against.

- Time: `2026-07-22`
  - Step: Complete P01 unified Agent Runtime integration under the user-directed Stage O scope override.
  - Completed Work: Added a compatibility runtime router and Port that keep simple tasks on Fast Path, evidence tasks on Safe RAG, and M06/N05 No-Go paths behind explicit experimental flags. Wired API/Worker through the runtime without replacing the existing processor, emitted public SSE summaries without hidden reasoning, persisted runtime mode in answer metadata, and added an idempotent legacy metadata migration. Stage O-dependent Cascade fails closed as `unavailable_o_skipped`.
  - Verification: Python P01/product/worker/API regression passed 36 tests; frontend passed 18 component tests, TypeScript checking and a production Next.js build; Ruff and mypy passed. Final-acceptance/runtime regression passed 4 tests. An isolated fresh Compose project built and started eight healthy services, API reported `adapter_mode=real`, and Web returned HTTP 200; its containers, network and volumes were removed afterward.
  - Open Issues: M06 and N05 remain effect No-Go and therefore non-default. The user explicitly skipped Stage O, so model-upgrade E2E is recorded as a tested fail-closed unavailable state and no SFT/Cascade effect is claimed. Next work package is P02.

- Time: `2026-07-22`
  - Step: Complete P02 failure clustering and Human-in-the-Loop data governance.
  - Completed Work: Added an evaluation-only failure clusterer over the closed L04 taxonomy; provenance/authorization/consent/anonymization-aware staging candidates; public-context allowlisting; administrator-token-protected list/review endpoints; immutable candidate identity; human approval; mandatory offline regression and safety Gate Runner invocation; versioned promotion reports; current-version pointer and audited rollback. The workflow never mutates production prompts or weights.
  - Verification: P02/API/L04/dataset-contract combined regression passed 36 tests; Ruff and mypy passed. Unauthorized sources and private data without consent/anonymization fail before staging, unreviewed candidates cannot promote, failed gates cannot promote, and passing gates require report paths.
  - Open Issues: Evidence truth class is `unit_fixture`; P02 proves governance and rollback mechanics, not a quality improvement. Stage O remains skipped and no Adapter training is claimed. Next work package is P03.

- Time: `2026-07-22`
  - Step: Complete P03 administrator-only Evaluation Dashboard.
  - Completed Work: Added strict public Dashboard case, filter, metric, comparison and drill-down contracts; six effect/efficiency/cost metrics with seeded 95% CI and contributing case IDs; paired Baseline/Candidate comparison; admin-token-protected metrics/compare/case APIs; and a separate `/admin/evaluation` Next.js page with no ordinary conversation entrypoint. Built a 480-row read model from frozen L05 B3 (300) and N05 Single/Full (90 each) artifacts.
  - Verification: Python/API suite passed 15 tests; frozen L05 Task Success/Token/4B/P95 metrics and N05 Claim Support/paired delta match their source JSON reports; repeated 300-row load/filter/drilldown P95 is below two seconds. Ruff, mypy, TypeScript and Next.js production build passed.
  - Open Issues: L05 did not measure Claim Support, so it remains N/A there; N05 is the real Claim Support source. Public L05 replay contains result summaries, not hidden reasoning or full paper text. Next work package is P04.

- Time: `2026-07-22`
  - Step: Complete P04 frozen final comparison and statistical report.
  - Completed Work: Added a deterministic report builder over frozen L05/M06/N05 artifacts. The report covers B0–B3 plus the production-safe policy mapped to unchanged B1 behavior, overall and difficulty/task-family/language slices, numerator/denominator/N/value/95% CI for every available public metric, paired B0 comparisons, failure frequencies, hardware/model/data/commit provenance and reproduction commands. Planner and Multi-Agent remain NO-GO; SFT and Cascade are unavailable because O was skipped.
  - Verification: P04 report tests passed; Ruff and mypy passed; JSON and Markdown artifacts were regenerated and hashed. Frozen L05 Task Success/Citation/P95 values reproduce exactly. The existing 30/300 two-annotator Gold audit is recorded as 10% human evidence with κ=1.0.
  - Open Issues: Production-safe is a policy-equivalent reuse of frozen B1, not an additional 300-call run. The 10% human audit covers dataset answer-type Gold, not final generated outputs. Local monetary cost excludes electricity and hardware amortization. Next work package is P05.

- Time: `2026-07-22`
  - Step: Complete P05 portfolio and interview delivery.
  - Completed Work: Reworked the README hero around the problem, architecture, measured outcomes and a one-command offline demo. Added a provenance-first six-step demo plus timed 3–5 minute recording runbook, evidence-gated promotion ADR, Model Card, links to the existing Dataset Card and P04 Evaluation Report, three failure postmortems, interview guide and resume-ready project description. The separate admin Dashboard remains unlinked from ordinary conversations.
  - Verification: P01–P05 targeted regression passed 54 tests. Full pytest, including Docker MinIO/Redis/PostgreSQL integration, passed 425 tests with seven third-party deprecation warnings. Ruff and mypy passed; frontend passed 18 tests, TypeScript and Next.js production build. Public P03 rows contain zero prompt/quote/private-text/hidden-reasoning fields.
  - Open Issues: No prerecorded human-narrated video binary is committed; the deterministic demo output and recording runbook are the recording source. Planner/Multi-Agent remain NO-GO, and SFT/Cascade remain unavailable because Stage O was skipped.

- Time: `2026-07-22 11:55`
  - Step: Repair PDF layout parsing, visual evidence extraction, screenshot-backed answers, and multi-turn conversation context.
  - Completed Work: Added per-page single/double-column detection with mutually exclusive column ordering; extracted figure/table/algorithm regions as 2x PNG artifacts with section/page/bbox/block provenance; excluded visual-body text from normal chunks while retaining captions; added controlled visual image API and answer gallery; and connected the product answer path to bounded, relevance-gated prior user/assistant messages with source IDs.
  - Verification: PDF visual crops were rendered and visually inspected; the full backend suite passed 431 tests with seven third-party deprecation warnings; frontend passed 19 tests and the Next.js production build; Ruff and mypy passed. A rebuilt Compose deployment kept API/Web/Worker healthy. A temporary PDF completed real upload/parse, produced one page/section-bound table PNG served as `image/png` with HTTP 200, kept artifact-body text out of chunks, and was deleted with its stored artifact. Browser reload showed no alert or console error.
  - Open Issues: Region extraction is deterministic and strongest for PDFs with native image/table/vector geometry and captions. Borderless tables or raster-only scanned layouts still depend on OCR/layout quality and may require a future specialized detector.

- Time: `2026-07-22 12:35`
  - Step: Repair dataset-intent routing and elliptical multi-turn retrieval.
  - Completed Work: Removed the unsafe promotion of model-generated section hints into mandatory section scope; fixed the Chinese substring boundary where “文章” was treated as containing an explicit “章” marker; expanded follow-up detection for “列举/举例/逐一/分别说明”等省略表达; and contextualized the actual RAG query with the most recent relevant user question while preserving bounded history and source message IDs.
  - Verification: Two failing-first product regressions reproduced the original `waiting_user` response. The repaired dataset query and elliptical follow-up both complete through ordinary RAG; section/parser/product/hybrid-retrieval regression passed 40 tests; the full backend suite passed 433 tests with seven third-party deprecation warnings; Ruff and mypy passed. Rebuilt API/Worker containers completed a real two-turn temporary conversation: both tasks completed, the follow-up stored `history_used=true`, used `ordinary_rag`, contextualized its query with the prior dataset question, and answered from PaperBench evidence; temporary conversation/PDF/index data were deleted afterward.
  - Open Issues: Follow-up resolution remains bounded and deterministic rather than a full coreference model. Very long topic jumps with no lexical or deictic signal intentionally do not inherit history and may require the user to restate the target.

- Time: `2026-07-22 15:20`
  - Step: Add per-task Agent progress monitoring and safe file-access audit logs.
  - Completed Work: Reused the persisted TaskEvent/SSE path; added public small-model routing, Skill, retrieval, large-model generation and Verifier stages; added a product monitor history endpoint and a composer-adjacent floating timeline. Introduced a `TaskAuditLogWriter` Port and per-task JSONL adapter with allow-listed metadata, object download/upload and index access records. Mounted `./agent_logs` into the Worker and exposed the relative file address in the UI.
  - Verification: Failing-first tests were added. The full backend suite passed 436 tests; frontend passed 20 tests and the Next.js production build; Ruff, mypy and TypeScript checks passed. A rebuilt local deployment stayed healthy. Real browser verification showed the monitoring button beside task status, persisted small-model/runtime stages after a fast task completed, and displayed the exact JSONL address. The host log contained safe action metadata and was mounted from the Worker as configured.
  - Open Issues: Logs are local operational artifacts and are not downloadable through the API. Rotation/retention and administrator-only log download can be added later if production deployment requires them.

- Time: `2026-07-22 15:52`
  - Step: Correct the false `paper_qa Skill` progress event and audit the production Skill chain.
  - Completed Work: Reclassified the product's built-in paper QA RAG stage from `skill_selected / paper_qa` to `step_started / paper_qa_rag`, with the public title `执行论文问答 RAG 流程`. The monitor API also normalizes legacy stored events at read time while preserving immutable database audit rows. Updated monitoring documentation so only real manifest selection and registry activation may be described as Skill use. Per user direction, the Skill execution chain itself was not changed.
  - Verification: A failing-first workflow test reproduced the false Skill label, then passed after the minimal event correction. The backend monitoring tests passed 3/3 and the frontend component tests passed 20/20.
  - Open Issues: The production Worker does not construct or inject `SkillSelector`/manifest `SkillRegistry`; `PaperAgentProcessor` directly composes parser, retriever, LLM and Verifier. `document_parser` has the same monitoring-versus-activation mismatch. Multiple incompatible Skill registry abstractions and a placeholder legacy selector node remain; integration requires a separately approved design.

- Time: `2026-07-22`
  - Step: Unify and production-wire the Skill lifecycle.
  - Completed Work: Replaced parallel legacy Skill abstractions with one manifest-first `SkillManifestLoader -> SkillRegistry -> SkillSelector -> SkillRuntime` path. Added manifest-declared structured input/output contracts and validation, activation/completion identity checks and traces; wired the Worker and existing Processor so PDF parsing and evidence QA emit `skill_selected` only after real Registry activation. Enriched all 11 SKILL.md files with metadata, activation/non-activation rules, workflow, structured templates, acceptance criteria and anti-patterns. Removed obsolete Python Skill wrappers, fake Registry, placeholder state-machine/stub runtime and their obsolete tests while preserving the existing parser/RAG/Verifier architecture.
  - Verification: Full backend regression passed 390 tests with seven third-party deprecation warnings. Frontend passed 20 component tests, TypeScript checking and the Next.js production build. Focused Ruff and Mypy checks passed. Production monitoring regression confirms both `document_parser` and the selected answer Skill emit real activation/completion traces.
  - Open Issues: Routing remains deterministic keyword selection with a safe `paper_reader` fallback; a learned selector can replace scoring later without changing the structured-contract/Registry lifecycle.

- Time: `2026-07-22`
  - Step: Correct Skill contracts, bind real Tools locally and make Tool parameter validity auditable.
  - Completed Work: Replaced the forced JSON-in/JSON-out convention with per-Skill `object`, `markdown` or `markdown_table` contracts. Added `tools/tools.yaml` to all 11 Skills with Tool purpose, use timing, shared implementation path and valid input example; the loader imports the real `tool_runtime` Pydantic models, validates examples, and the runtime validates each Tool call and result before tracing it. Production parsing and RAG retrieval now pass through these bindings without replacing the existing Processor implementation. Removed the empty root `tools/` directory and obsolete `core/ports/tools.py`; removed nonexistent `verify_claim`/`verify_citations` bindings. Added a reproducible `valid_calls/total_calls` metric with N/A for zero calls.
  - Verification: Focused Skill/Tool/production-monitoring regression passed 65/65 tests; full backend regression passed 395/395 tests with seven third-party deprecation warnings. Ruff and Mypy passed. Frontend passed 20/20 component tests, TypeScript checking and the Next.js production build. All 11 Skill packages load, all 19 local Tool binding examples validate against real Pydantic input models, invalid Tool arguments are rejected and traced.
  - Open Issues: `Tool 参数合法率 ≥98%` remains an acceptance target until a versioned real-model evaluation set supplies valid and total call counts; the 19/19 binding examples verify contracts only and must not be reported as the product KPI.

- Time: `2026-07-22 22:10 -04:00`
  - Step: Consolidate the repository into explicit product, infrastructure and runtime boundaries.
  - Completed Work: Moved all Python product code under `backend/`, the Next.js application and Node configuration under `frontend/`, Compose/Docker/OTEL assets under `infrastructure/docker/`, and the Alembic entry configuration under `infrastructure/database/`. Consolidated operational output under `runtime/logs`, `runtime/diagnostics` and `runtime/scratch`; retained short- and long-term memory together under `backend/memory/` and documented the boundary between conversation memory, Agent working state and Redis coordination. Updated every Python import, command, Docker build context, volume, migration path, test path and evaluation metadata path. Updated README, architecture, technology, execution-plan and module-dependency documentation. Removed obsolete root code trees, superseded deployment locations, an empty frontend Pages directory, temporary test output and generated caches without deleting user data, evaluation evidence, `.venv` or `node_modules`.
  - Verification: Full backend and integration regression passed 398/398 tests, including PostgreSQL, Redis and MinIO containers. Ruff passed with zero findings; core Agent/model/Tool Runtime Mypy passed for 15 source files. Frontend passed 20/20 tests, TypeScript checking and the Next.js production build. Compose configuration validated and API, Worker and Web images all built successfully. Repository-structure regression enforces the new boundaries and rejects the removed legacy roots.
  - Open Issues: A whole-backend Mypy scan now reaches previously untyped legacy Fake Adapter, API schema and Alembic migration code and reports 43 pre-existing type-annotation issues outside this structural change; runtime behavior is covered by the complete passing test suite. Third-party Testcontainers/Vite deprecation and React test `act(...)` warnings remain non-blocking cleanup items.

- Time: `2026-07-23`
  - Step: Rewrite the repository README as a finished-product introduction.
  - Completed Work: Replaced the development diary, stage checklist, next-step plan, work-package links and contributor workflow with a user-facing project overview. The README now presents the product value, supported academic workflows, architecture, Docker/Ollama quick start, usage flow, PDF/RAG/visual-evidence behavior, Skill/Tool contracts, memory boundaries, monitoring, configuration, code navigation, reproducible quality evidence, security and troubleshooting. Kept limitations as operational product boundaries rather than roadmap language.
  - Verification: Confirmed there are no development-stage, next-stage, work-package, placeholder repository or pending-implementation phrases. All referenced local files and entry scripts exist; all Markdown code fences are balanced; Compose environment overrides and exposed service addresses match the documented startup flow. Repository-structure and deployment documentation regression passed 8/8 tests.
  - Open Issues: Repository hosting URL and screenshots are not available in the local project, so the README intentionally avoids fake clone URLs, CI badges and fabricated UI images.

- Time: `2026-07-23`
  - Step: Repair the Windows double-click startup chain.
  - Completed Work: Replaced the terminating PowerShell 5.1 `docker info` probe with a locally suppressed `Test-DockerEngine` check so a stopped Engine can trigger Docker Desktop startup. Made Compose explicitly load the repository-root `.env`; added a data-preserving PostgreSQL role-password synchronization for reused named volumes; changed the default launcher to rebuild through Docker cache so stale images cannot survive source layout changes; restored an explicit top-level `infrastructure` Python package for the deployment runtime; and added model-router, API and Web readiness gates. Updated stop and README Compose commands to use the same environment file.
  - Verification: Reproduced the original terminating native-command error and the subsequent PostgreSQL authentication mismatch before repair. Deployment and repository-structure regression passed 11/11 tests; focused Ruff passed. The final launcher completed successfully twice. API, Web, Worker, PostgreSQL, Redis, MinIO, model-router and observability are healthy; model-router, API and Web return HTTP 200. Existing PostgreSQL, Redis and MinIO volumes were preserved.
  - Open Issues: Optional `model-1-7b` and `model-4b` Compose profile services are not started by the default launcher; normal inference continues through the configured host Ollama endpoint.

- Time: `2026-07-23`
  - Step: Create the comprehensive project interview introduction.
  - Completed Work: Added `docs/项目面试完整介绍.md` as a code-grounded interview handbook. It covers concise and extended project pitches, architecture and end-to-end execution, PDF layout/visual parsing, hybrid RAG, citations, multi-turn memory, all 11 Skills and their Tool contracts, every supported academic task, Agent Runtime and optional multi-agent paths, model routing, persistence, APIs, complete repository navigation, evaluation methodology, engineering trade-offs, representative incident repairs, high-frequency interview questions, overclaim boundaries and a five-minute demonstration script.
  - Verification: Confirmed the document contains 24 top-level topic groups, 172 Markdown headings and 14 balanced code fences. Cross-checked the current refactored backend, frontend, infrastructure, evaluation and documentation locations; verified the named core files and directories exist. Explicitly distinguished the default Safe RAG product path from No-Go experimental Planner/multi-agent capabilities, and separated the early 30-session acceptance metrics from the stricter frozen 300-case evaluation.
  - Open Issues: This is a snapshot of the codebase on `2026-07-23`; material architecture or evaluation changes should update the handbook together with the product documentation.

- Time: `2026-07-23 15:42 -04:00`
  - Step: Repair stale follow-up file IDs, bounded recent-turn memory and anchored evidence previews.
  - Completed Work: Made active `ConversationFile -> File` rows the authoritative per-turn file scope, filtered stale/deleted client IDs before persisting a user message and repeated the check in the Worker. Corrected shared-file deletion so a conversation removes the original object, parsed document and index only after all active conversation references reach zero; upload now recalculates the reference count. Extended the bounded context selector to always expose the immediately previous exchange and recognize short elliptical prompts such as “准确率呢？”, while only contextualizing the retrieval query for an actual follow-up. Replaced below-message citation cards and full visual galleries with mouse-hover, keyboard-focus and click-pinned popovers anchored beside evidence IDs and figure/table/algorithm labels.
  - Verification: The reported file ID was inspected in the live database and confirmed soft-deleted despite two still-active conversation links, reproducing the shared-reference defect. Added three backend regressions and expanded the frontend interaction regression. The final backend suite passed 404/404; frontend passed 20/20, TypeScript and Next.js production build passed; Ruff and focused Mypy passed. Restored the README portfolio contract's required reproducibility and No-Go disclosures. Rebuilt API/Worker/Web images and confirmed all three containers healthy, Web HTTP 200 and API readiness HTTP 200.
  - Open Issues: The already-deleted `第五章.pdf` object and its derived index cannot be reconstructed from metadata alone and must be uploaded once more. Test output still includes existing third-party Testcontainers/Vite deprecation and React `act(...)` warnings.

- Time: `2026-07-23`
  - Step: Repair multi-document comparison evidence scope and Skill output validation.
  - Completed Work: Inspected the latest failed task `3fd5398b7642430294a9a50f900bae30` and confirmed both PDFs were parsed and passed into retrieval. Replaced comparison tasks' cross-file global Top-8 with per-file balanced retrieval under the same eight-hit budget; added filename plus file-ID evidence labels and persisted comparison scope metadata. Corrected `comparison_analyzer` so only the universal “论文” column is fixed while task-specific dimensions remain dynamic. Added a side-effect-free Skill output validation step and one bounded format-repair generation before completion, preventing deterministic Markdown contract failures from retrying the complete RAG pipeline.
  - Verification: A failing-first product regression reproduced `Skill output is invalid: missing table columns: ['方法']`. The repaired integration test uses 12 high-ranking Alpha chunks and one Beta chunk, verifies both papers remain in evidence, both filenames reach the model, a prose first answer is repaired once, and the task completes as `comparison_balanced_rag`. Product/Skill/monitoring regression passed 41 tests; the full backend and Docker integration suite passed 406 tests. Ruff and focused Mypy passed. Rebuilt API, Worker and Web images; all services are healthy, API readiness returned HTTP 200 in real-adapter mode and Web returned HTTP 200.
  - Open Issues: Balanced comparison retrieval uses the existing total eight-hit context budget. Very large comparison sets may require a future configurable context budget or staged Paper Card aggregation; the current repair intentionally does not introduce a new execution architecture.

- Time: `2026-07-23`
  - Step: Integrate short-term and long-term Memory into the default conversation Worker.
  - Completed Work: Added `ConversationMemoryCoordinator`; injected short/long Memory services and the production queue into `PaperAgentProcessor`; registered a real `memory_summary` Handler in the Docker Worker; and idempotently schedules summary updates after every saved assistant answer. Current-conversation Memory retrieval now searches `MemorySegment`, then rereads relevant undeleted source messages; explicit historical intent additionally searches other conversations' `ConversationSummary` while excluding the current conversation. Answer metadata records Memory level usage, Segment IDs, source Conversation IDs and source Message IDs. Deleted the unused Fake-only `backend/apps/worker/main.py` and `handler_registry.py`, replacing their placeholder tests with production Worker wiring coverage.
  - Verification: Failing-first tests established that the coordinator and Processor integration were unavailable. New regressions prove a fact older than the 24-message recent window is recovered through short-term Memory, an explicit historical question recovers original text from another conversation, both Memory levels persist, the answer schedules `memory_summary`, and the default Worker registers a functional Handler. Memory/product/Worker/Redis regression passed 44 tests. A first real Worker replay exposed PostgreSQL `json = json` incompatibility in MemorySegment deduplication; the query now scopes rows in SQL and compares source ID lists in Python, with a pgvector/PostgreSQL Testcontainers regression. Final Ruff and focused Mypy passed; the full suite passed 407 tests. Rebuilt API/Worker are healthy. A disposable real-adapter task completed and persisted exactly one MemorySegment plus one ConversationSummary; all temporary conversations, messages and queue jobs were then removed. API and Web returned HTTP 200.
  - Open Issues: Summaries remain deterministic and traceable rather than LLM-authored semantic compression. This preserves offline operation and source fidelity but may be less concise for extremely long conversations; any future learned summarizer must retain the same source-message traceability and deletion semantics.

- Time: `2026-07-24 10:16 -04:00`
  - Step: Define the minimal implementation plan for feature-gated production multi-Agent execution.
  - Completed Work: Added `docs/多Agent生产链启用实施计划.md`. The plan audits the existing Unified Runtime, six role contracts, Coordinator, PaperReaderAgent, Blackboard, ReviewLoop and Worker wiring; defines the missing production `AdvancedRuntimePort` Adapter and bounded RoleRunner; and divides implementation into stages A–P with per-stage goals, file scopes, outputs, acceptance criteria, failure semantics, tests, Docker wiring, observability, evaluation and rollback. The plan explicitly preserves Safe RAG when either experimental flag is disabled and forbids treating planned functionality as already implemented.
  - Verification: Confirmed the plan targets the current refactored paths, contains the requested Coordinator → parallel Paper Readers → Evidence → Critic → Writer → Verifier → at-most-one Writer revision flow, and records that the current Worker still lacks an injected advanced runtime. No product code or runtime behavior was changed, so implementation tests were not run.
  - Open Issues: The plan remains unimplemented. Opening `MULTI_AGENT_ENABLED` and `ALLOW_EXPERIMENTAL_NO_GO` will not execute multiple Agents until stages B–N are completed and verified; default promotion additionally depends on the stage O frozen evaluation gate.

- Time: `2026-07-24`
  - Step: Implement the feature-gated multi-Agent production chain from stages A through P.
  - Completed Work: Added the production `MultiAgentRuntimeAdapter` and `ProductionRoleRunner`; connected the existing Coordinator and PaperReaderAgent to file-scoped Tool Runtime retrieval, structured Evidence/Critic/Writer/Verifier model calls, PostgreSQL Blackboard and one bounded Writer/Verifier revision. Injected the Adapter, Manifest model resolver, Tool Runtime, managed Blackboard sessions, cancellation checks, Trace/Event/Audit sinks into the default Worker and removed polling of the unhandled `sub_agent` queue. The Processor now consumes a verified Advanced result exactly once and reuses normal evidence, visual artifact and Memory persistence. Added dual-gate environment/Compose wiring, role-level frontend events, idempotent verified-result replay, required/optional role failure semantics, task-scoped Blackboard primary keys through migration 0010, and source-deletion cascade invalidation. Updated all delivery documents and generated `evaluation/reports/n05_multi_agent_production_v2/` from the frozen offline-real-model checkpoint.
  - Verification: The complete backend suite passed 426 tests, including nine Docker-backed Redis/MinIO/SSE integration tests and SQLite/PostgreSQL-compatible Alembic upgrade/downgrade coverage. Ruff and focused Mypy passed; TypeScript checking and the production Next.js build passed. An isolated Compose validation stack built from the modified source and reported API, Worker, Web, PostgreSQL, Redis, MinIO, model-router and observability healthy (the isolated model-router used host port 18080 because the normal project already occupied 8080). The frozen qwen3.5:4b N05 report reproduced a NO-GO decision: 90 eligible L4/L5 paired cases from the frozen 300-case asset, Task Success delta -1.11pp, Claim Support +5.63pp, candidate P95 55,139 ms and total Token +398.03%; missing annotations remain explicitly unavailable rather than inferred.
  - Open Issues: Multi-Agent is mechanism-complete and explicitly runnable, but its effect gate remains NO-GO, so both experimental flags stay false by default. The frozen N05 artifact does not contain paper-identity, full-coverage or Tool-validity annotations; these are covered by acceptance/security tests but are not presented as real-model effect estimates.

- Time: `2026-07-25`
  - Step: Scope repeated citation previews per occurrence and render comparison results as real tables.
  - Completed Work: Replaced evidence/visual popover keys shared by ID with occurrence-scoped keys and limited display to one active hover or pinned instance. Added a bounded parser for the validated pipe-table output of `comparison_analyzer`, semantic `table`/`thead`/`tbody` rendering, responsive horizontal scrolling and continued inline evidence interactions inside table cells. No backend contract or Agent execution path changed.
  - Verification: Added failing-first component regressions for duplicate `[E1]` occurrences and Markdown comparison tables. The repaired frontend component suite passed 22/22 tests; TypeScript checking and the Next.js production build passed. Rebuilt the Web service and confirmed the Web container healthy, Web HTTP 200 and API readiness HTTP 200.
  - Open Issues: The renderer intentionally handles the system's validated pipe-table contract rather than arbitrary Markdown or model-supplied HTML, keeping the rendering and injection surface bounded.

- Time: `2026-07-25`
  - Step: Rebuild the complete AI application interview guide against the current system.
  - Completed Work: Replaced `docs/项目面试完整介绍.md` in full with a current, interview-oriented explanation of the product boundary, upload and answer workflows, layout-aware PDF parsing, section-aware parent/child chunking, actual Hash Embedding and lexical reranking path, hybrid RAG, citations, Runtime modes, eleven Skills, Tool policy, Memory, the feature-gated multi-Agent production chain, storage, API, security, observability and evaluation. Added the guide to the README related-materials list. The guide explicitly separates default, experimental, unavailable and evaluated capabilities and records the latest N05 No-Go result without presenting missing annotations as measured effects.
  - Verification: Cross-checked the guide against the current Worker wiring, Product Service, PDF/RAG, Skill/Tool/Memory implementations, role manifests, N05 production report, P04 final report, Model Card, Dataset Card and failure postmortems. The non-Docker Python suite passed 417 tests. A full run produced the same 417 passes plus one skip; eight Redis/MinIO/SSE integration fixtures could not start because the local Docker daemon was not running, with no business assertion failure.
  - Open Issues: README still describes BGE-M3 as the default embedding model although the current Worker constructs `MultilingualHashEmbeddingClient`; the interview guide calls out this implementation/configuration discrepancy explicitly. Docker-backed integration tests were not rerun in this environment.

- Time: `2026-07-25`
  - Step: Enable the bounded dynamic Planner by default and expose its Plan as live product state.
  - Completed Work: Added `DynamicPlannerRuntimeAdapter`, a public Plan schema and a dedicated Planner Port; injected the constrained small-model Planner into the production Worker; changed paper tasks to default `dynamic_plan`; changed `.env.example` and Compose defaults to enable the Planner while leaving multi-Agent disabled. Persisted only public plan IDs, goals, termination conditions, step titles/types/dependencies and lifecycle states through TaskEvent/SSE. Advanced those steps alongside the real ProductService decision, retrieval, generation and verification stages. Added a dedicated frontend plan panel with pending, active, completed and skipped states. Updated README, Model Card, architecture, execution plan, development plan and interview documentation without rewriting the historical M06 NO-GO effect result.
  - Verification: Dynamic Planner/Worker/Product regressions passed 41 tests; the complete non-Docker Python suite passed 419 tests; frontend passed 22 component tests, TypeScript checking and the Next.js production build; Ruff passed; focused Mypy passed after tightening the optional StepType conversion.
  - Open Issues: Default enablement is an explicit product decision, not a new effect promotion. The product executor remains the bounded Safe RAG implementation underneath the public Plan, and no new frozen Task Success or cost estimate was generated in this change. Docker-backed integration remains to be rerun.

- Time: `2026-07-25`
  - Step: Clarify ownership and section purpose throughout the complete interview guide.
  - Completed Work: Updated `docs/项目面试完整介绍.md` so every second-level heading begins with a one-sentence purpose statement. Replaced the two key workflow summaries with step-by-step ownership tables: the upload path explicitly distinguishes the frontend, API, Document Ingestion Worker, `document_parser` Skill, Tool Runtime and deterministic parsing/indexing adapters; the answer path distinguishes the Main Agent, Dynamic Planner, Memory coordinator, Skill/Tool Runtime, Safe RAG, deterministic Verifier and the feature-gated multi-Agent DAG. Synchronized the architecture document and README interview-material description.
  - Verification: Programmatically checked that every `##` heading is followed by a non-empty purpose sentence; manually cross-checked both ownership tables against the current Worker, ProductService, Unified Runtime, Planner Adapter, Memory, Skill/Tool and multi-Agent wiring. Documentation-only change; no runtime code or tests changed.
  - Open Issues: None.

- Time: `2026-07-25 15:32 -04:00`
  - Step: Enable bounded Multi-Agent by default for eligible multi-paper tasks and refresh the interview guide.
  - Completed Work: Changed `RuntimeCapabilities`, Worker environment defaults, `.env`, `.env.example`, Docker Compose and the multi-Agent product policy so both runtime gates default to true. Preserved route eligibility: only at least two distinct papers plus comparison/review/synthesis intent enters `Coordinator -> Paper Reader x N -> Evidence -> Critic -> Writer -> Verifier`; single-paper and ordinary document tasks continue through Dynamic Planner + Safe RAG, and either gate can opt out. Reviewed the Adapter, Coordinator, RoleRunner, Blackboard, one-revision, ProductService evidence/persistence and Memory handoff path. Invalidated old-code effect/cost conclusions in current product documentation and marked the current version pending re-evaluation. Expanded both interview-guide workflows so every step includes its responsible Agent/component, source folder and concrete class/method; also added M1-M9 code navigation for the internal multi-Agent branch.
  - Verification: Focused role/DAG/Blackboard/Review Loop regression passed 43 tests; default routing plus ProductService evidence/message/Memory integration passed 16 tests; the full non-Docker suite passed 421 tests with 9 Docker integration tests deselected. Ruff passed for all modified Python/test files and focused Mypy passed for the modified runtime sources. Programmatic documentation checks verify all 27 second-level headings retain purpose sentences and every workflow row contains a code-location column.
  - Open Issues: Current quality, Token and P95 results are pending a fresh version-bound evaluation. Docker-backed Redis/MinIO/SSE integration was not rerun in this change.
