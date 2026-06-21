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
