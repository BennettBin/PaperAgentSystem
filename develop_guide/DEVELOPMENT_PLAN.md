# PaperAgentSystem 详细开发计划

> 本文档直接提供给 Codex 执行。  
> 开发策略：自顶而下；先契约和完整骨架，再逐模块替换真实实现。  
> 项目根目录：`D:\vscode\Projects\PaperAgentSystem`  
> 长期规则见：[AGENTS.md](./AGENTS.md)

---

## 1. Codex 使用方法

每次开始开发任务时，Codex 必须依次读取：

1. `AGENTS.md`
2. `01-技术栈文档.md`
3. `02-产品架构文档.md`
4. `03-执行计划文档.md`
5. 本文档当前工作包
6. 当前工作包涉及目录中的局部 `AGENTS.md`，如果后续创建

执行规则：

- 每次只完成一个工作包，除非用户明确要求合并。
- 开始工作包前检查它的前置条件。
- 先检查现有代码和未提交修改，不覆盖用户工作。
- 先更新实施计划，再修改代码。
- 完成实现后运行该工作包要求的测试。
- 只有验收标准全部满足，才能将工作包标记为完成。
- 工作包完成后更新本文档“进度记录”，并报告改动、测试及剩余风险。
- 如果需要改变 Port、Domain、状态机或跨模块契约，必须先更新相应 ADR 和契约测试。
- 不因为真实依赖暂时不可用而绕开架构；使用 Fake 实现继续。

---

## 2. 全局完成标准

任何工作包均应满足：

- 代码通过格式检查和类型检查。
- 新增行为具有自动测试。
- 不引入未经定义的跨模块字典。
- 不绕过 Workspace、权限、Model Profile 或 Tool Registry。
- 错误使用项目统一错误类型。
- 公开接口有类型与简短说明。
- 配置来自环境或配置文件，不硬编码密钥和本地绝对路径。
- 修改同步到相关文档。
- 无关文件不被修改。

---

## 3. 开发命令约定

在项目骨架建立后，应逐步提供以下统一命令：

```text
make/bootstrap       安装或检查开发依赖
make/dev             启动开发服务
make/format          格式化
make/lint            静态检查
make/typecheck       类型检查
make/test-unit       单元测试
make/test-contract   契约测试
make/test-integration 集成测试
make/test-e2e        端到端测试
make/test-security   安全测试
make/eval            质量评测
make/check           本地完整检查
```

Windows 环境可以用 PowerShell 脚本或 `just`/Python 任务入口提供等价命令，但 README 中只能有一套主命令。

---

# 阶段 A：项目治理和架构契约

## A01：清理入口并建立项目元数据

### 目标

将当前小型目录转为可持续开发的 Monorepo 根目录，不实现业务功能。

### 前置条件

- 三份基线文档存在。
- 已读取现有 `main.py`、`test.py` 和 README。

### 实现内容

1. 创建根目录：
   - `apps/`
   - `packages/`
   - `core/`
   - `agent_runtime/`
   - `conversations/`
   - `tasks/`
   - `workspace/`
   - `memory/`
   - `skills/`
   - `tools/`
   - `subagents/`
   - `documents/`
   - `retrieval/`
   - `writing/`
   - `verification/`
   - `models/`
   - `storage/`
   - `observability/`
   - `security/`
   - `evaluation/`
   - `training/`
   - `tests/`
   - `infra/`
   - `scripts/`
   - `docs/adr/`
2. 创建 Python、Node、Git 和编辑器基础配置。
3. 创建 `.env.example`，只放变量名和安全示例。
4. 创建 `.gitignore`：
   - 模型权重。
   - 数据集原文。
   - 上传文件。
   - TaskWorkspace 临时目录。
   - 密钥。
   - Python/Node 构建缓存。
5. 将根 README 改为项目入口，链接五份核心文档。
6. 保留或迁移现有试验文件，不无故删除。

### 测试

- 检查仓库中不存在真实密钥。
- 检查 Markdown 链接。
- 检查 Python 和 Node 配置可以被工具读取。

### 验收标准

- 目录骨架完整。
- README 能解释项目目标、文档入口和开发顺序。
- `.env.example`、`.gitignore` 和基础配置存在。
- 现有用户文件未被错误删除。

---

## A02：建立 ADR 和模块依赖规则

### 目标

将重要架构决策写成代码开发必须遵守的规则。

### 实现内容

在 `docs/adr/` 创建：

- `0001-custom-agent-state-machine.md`
- `0002-postgres-pgvector.md`
- `0003-sse-events.md`
- `0004-port-adapter-boundaries.md`
- `0005-model-profile-registry.md`
- `0006-memory-summary-source-trace.md`
- `0007-conversation-task-workspace.md`
- `0008-sandbox-boundary.md`
- `0009-system-training-decoupling.md`

每份 ADR 包含：

- Context
- Decision
- Alternatives
- Consequences
- Invariants

定义依赖方向：

```text
apps → application service → core ports/domain
infrastructure adapters → core ports
agent_runtime → core ports
domain 不依赖 FastAPI、SQLAlchemy、Celery、MinIO、vLLM
```

### 测试

- 增加依赖边界检查脚本或静态规则。
- 创建一个故意违规的 Fixture，证明检查能失败；Fixture 不进入正常源码。

### 验收标准

- 九份 ADR 完整。
- 依赖方向可通过自动检查验证。
- Domain 层不导入基础设施框架。

---

## A03：定义全局 ID、枚举和错误模型

### 目标

建立全系统共同语言。

### 实现内容

在 `core/domain/` 和 `core/errors/` 定义：

- 强类型 ID：UserId、WorkspaceId、ConversationId、MessageId、TaskId、FileId、EntryId 等。
- TaskStatus。
- StepStatus。
- MessageRole/MessageType。
- WorkspaceEntryKind/Retention。
- ToolPermission。
- ModelProfileStatus。
- ErrorCode。
- ProjectError 基类和可序列化 ErrorDetail。

规则：

- ID 不使用无类型裸字符串在模块间传递。
- 时间统一保存 UTC。
- 状态值一旦持久化不能随意改名。
- 错误区分可重试、需用户处理、权限、安全和内部错误。

### 测试

- ID 解析和序列化。
- 枚举稳定性快照。
- 错误到 API 响应的映射。

### 验收标准

- 全局类型可导入。
- 无循环依赖。
- 所有类型通过单元测试。

---

## A04：定义核心 Domain 实体

### 目标

完整定义产品架构中的实体，暂不实现数据库。

### 实现内容

定义：

- User、Workspace
- Conversation、Message
- File、ConversationFile
- Task、Plan、Step
- ClarificationRound、RequirementBrief
- SkillDefinition、ToolDefinition、ToolCall
- SubAgentRun
- Document、Chunk
- MemorySegment、ConversationSummary、MemoryPreference
- ConversationWorkspace、TaskWorkspace、WorkspaceEntry
- Artifact、Citation
- ModelProfile、ModelVersion
- TaskEvent、TraceRecord、EvaluationRun

每个实体明确：

- 创建约束。
- 状态变化方法。
- Workspace 所属关系。
- 删除/失效语义。
- 版本字段。

### 测试

- 合法创建。
- 非法状态转换。
- Workspace 归属检查。
- 删除和失效状态。

### 验收标准

- 产品架构文档中的实体全部覆盖。
- Entity 不包含 ORM 装饰器。
- 不变量由方法或构造校验保护。

---

## A05：定义所有 Port

### 目标

冻结模块边界，使后续 Fake 和真实实现可互换。

### 实现内容

定义异步 Port：

- ConversationRepository
- MessageRepository
- TaskRepository
- FileRepository
- WorkspaceRepository
- MemoryRepository
- DocumentRepository
- SkillRegistry
- ToolRegistry
- ModelRegistry
- LLMClient
- EmbeddingClient
- RerankerClient
- ObjectStore
- TaskQueue
- EventPublisher
- DocumentParser
- Retriever
- ClaimVerifier
- SandboxExecutor
- TraceWriter
- Clock
- IdGenerator

每个 Port 明确：

- 输入/输出类型。
- 可能错误。
- 幂等语义。
- 权限上下文。
- 分页方式。

### 测试

- 使用 Protocol/ABC 检查 Fake 实现接口。
- 契约测试基类可被不同 Adapter 复用。

### 验收标准

- 上述 Port 全部存在。
- Port 不泄漏 SQLAlchemy Session、Celery Task、MinIO Client 等实现类型。
- 所有 Port 有契约测试入口。

---

## A06：定义 Agent Schema 和状态机

### 目标

冻结 Agent Runtime 的状态和决策协议。

### 实现内容

定义：

- AgentState
- AgentDecision
- RequirementCheckResult
- ClarificationQuestion
- RequirementBrief
- PlanSchema、PlanStepSchema
- ToolCallRequest、ToolCallResult
- SubAgentRequest、SubAgentResult
- VerificationResult
- FinalResponse

实现状态：

```text
RECEIVED → UNDERSTANDING → REQUIREMENT_CHECK
REQUIREMENT_CHECK → CLARIFYING/WAITING_USER
WAITING_USER → REQUIREMENT_CHECK/EXECUTING
REQUIREMENT_CHECK → SKILL_SELECTED
SKILL_SELECTED → PLANNED → EXECUTING → VERIFYING
VERIFYING → COMPLETED/REPLANNING/FAILED
REPLANNING → EXECUTING
任意可取消状态 → CANCELLED
```

### 测试

- 所有合法迁移。
- 所有非法迁移。
- AgentState JSON 往返。
- 决策 Schema 拒绝额外字段和非法 Tool。

### 验收标准

- 状态迁移测试完整。
- 状态可以安全持久化和恢复。
- Planner、Executor、API 共用同一 Schema。

---

## A07：定义 REST API 和 SSE 契约

### 目标

在实现 Route 前冻结前后端通信协议。

### 实现内容

定义产品架构文档中的：

- Conversation API
- Message/Task API
- File API
- Workspace API
- Artifact API
- Memory API
- Model Registry 管理 API

定义 SSE 事件：

- task_queued
- task_started
- requirement_clarification_requested
- requirement_clarification_received
- skill_selected
- plan_created
- step_started/completed
- tool_started/completed/failed
- subagent_started/completed/failed
- verification_failed
- artifact_created
- task_completed/failed/cancelled

建立 Python Schema 与 TypeScript 类型生成或同步机制。

### 测试

- OpenAPI 快照。
- SSE Event Union 序列化。
- Python 与 TypeScript 类型一致性。
- 错误响应快照。

### 验收标准

- API 契约完整。
- 前端无需读取后端内部 Model。
- 事件有 sequence、event_id、task_id 和时间。

---

# 阶段 B：完整代码骨架

## B01：创建后端应用骨架

### 目标

建立 FastAPI、配置、依赖注入和健康检查。

### 实现内容

- `apps/api` 启动入口。
- 配置模型和环境分层。
- 依赖注入容器。
- `/health/live`、`/health/ready`。
- Route 空实现。
- 统一错误处理中间件。
- request_id/trace_id 中间件。

### 测试

- 应用启动。
- 健康检查。
- 错误格式。
- 配置缺失提示。

### 验收标准

- API 可使用 Fake Adapter 启动。
- Route 不直接调用基础设施。
- 无真实数据库也能运行单元测试。

---

## B02：创建 Worker 和任务队列骨架

### 目标

建立后台任务入口，但先使用内存 FakeQueue。

### 实现内容

- `apps/worker` 入口。
- MainTask、SubAgentTask、ParseTask、MemorySummaryTask 类型。
- 取消令牌。
- 重试策略配置。
- FakeTaskQueue。
- Task Handler Registry。

### 测试

- 任务注册。
- FakeQueue 投递和执行。
- 取消。
- 重复 idempotency_key。

### 验收标准

- API 创建任务后可由 FakeQueue 执行。
- Task Handler 不依赖 HTTP Request。

---

## B03：创建前端完整页面骨架

### 目标

一次性创建所有主要界面组件，不等待后端真实实现。

### 实现内容

- 会话列表和搜索。
- MessageList。
- MessageComposer。
- AttachmentPicker。
- ClarificationCard。
- TaskProgress。
- CitationCard。
- ArtifactCard。
- WorkspacePanel。
- FilePreview。
- Memory 来源提示。
- 设置/数据管理占位页。
- Model Profile 管理页仅开发环境可见。

使用 Mock Service Worker 或本地 Mock API。

### 测试

- 组件渲染。
- 会话切换。
- 文件上传状态。
- 澄清问题提交。
- Task 进度事件渲染。
- Workspace 文件提升和删除确认。

### 验收标准

- 所有用户操作均有可见入口。
- 不展示隐藏推理。
- UI 可完全连接 Mock API 演示。

---

## B04：创建全部 Fake Adapter

### 目标

为所有 Port 提供确定性 Fake。

### 实现内容

- Fake repositories。
- FakeObjectStore。
- FakeTaskQueue/EventPublisher。
- FakeLLMClient。
- FakeEmbedding/Reranker。
- FakeDocumentParser/Retriever。
- FakeMemoryRepository。
- FakeWorkspaceRepository。
- FakeSkill/Tool Registry。
- FakeClaimVerifier。
- FakeSandboxExecutor。
- FakeTraceWriter。

Fake 必须可配置成功、失败、超时和部分失败。

### 测试

- 每个 Fake 通过对应契约测试。
- 确定性输出。
- 故障注入。

### 验收标准

- 所有 Port 都有 Fake。
- 测试不需要网络、模型或容器。

---

## B05：创建 Agent Runtime Stub

### 目标

实现节点接口和 Orchestrator 结构，节点先返回 Fake 决策。

### 实现内容

- Orchestrator。
- StateMachine。
- ContextBuilder。
- RequirementClarifier。
- SkillSelector。
- Planner/Replanner。
- Executor。
- Verifier。
- Termination。
- Policy/Budget。

### 测试

- 节点调用顺序。
- 状态持久化调用。
- 取消检查。
- 预算终止。

### 验收标准

- Runtime 可用 Fake 运行。
- 所有节点只依赖 Port。

---

## B06：创建 Skill、Tool、Sub-agent 骨架

### 目标

建立完整注册和配置格式。

### 实现内容

- Tool 基类和 Registry。
- Skill Manifest Loader。
- 十一个初始 Skill 目录。
- paper_reader_agent 定义。
- Model Profile 引用。
- Tool 白名单和输出 Schema。

### 测试

- Manifest 加载。
- 未注册 Tool 拒绝。
- Profile 缺失时 fallback。
- 子 Agent 文件范围。

### 验收标准

- 所有 Skill 可被发现和加载。
- Skill 中无物理模型路径。

---

## B07：贯通 Fake 端到端

### 目标

在真实基础设施前完成系统控制流。

### 场景

1. 信息充分直接执行。
2. 需求不足，提出问题，用户回答后恢复原 Task。
3. 多子 Agent 并发和部分失败。
4. 核验失败后重规划。
5. 用户取消和重试。
6. Memory 找到早期消息。
7. Workspace 找到早期脚本。
8. 删除内容后检索为空。
9. 章节撰写生成 Fake Artifact。

### 测试

- API + FakeQueue + Runtime + Mock UI E2E。
- 所有事件顺序。
- Trace 完整性。

### 验收标准

- 九个场景全部通过。
- 后续真实模块可以逐个替换 Fake。
- 这是开始真实基础设施开发的硬门槛。

---

# 阶段 C：基础设施 Adapter

## C01：PostgreSQL 与 Alembic

### 目标

实现所有 Repository 的持久化 Adapter。

### 实现内容

- SQLAlchemy 2 Models。
- 全部实体表和索引。
- pgvector 扩展迁移。
- Alembic。
- Unit of Work。
- Workspace 过滤。
- 软删除、硬删除和引用计数。
- 乐观锁。

### 测试

- Testcontainers PostgreSQL。
- 每个 Repository 契约测试。
- Migration upgrade/downgrade。
- 跨 Workspace 越权。
- 并发版本冲突。

### 验收标准

- 所有 Repository Contract 通过。
- 越权读取为 0。
- Migration 可在空库完整执行。

---

## C02：Redis、Celery 和事件发布

### 目标

将 FakeQueue 替换为真实后台任务。

### 实现内容

- Celery Broker/Backend 配置。
- 主任务、子 Agent、解析、Memory 摘要队列。
- 取消标记。
- 分布式锁。
- 指数退避。
- 死信或失败记录。
- Redis EventPublisher。

### 测试

- Testcontainers Redis。
- 投递、执行、重试、取消。
- Worker 崩溃模拟。
- 重复投递。

### 验收标准

- 任务状态以 PostgreSQL 为真值。
- Redis 丢失不丢历史任务。
- 取消可在约 2 秒内被观察。

---

## C03：MinIO 对象存储

### 目标

持久化上传文件、WorkspaceEntry 和 Artifact。

### 实现内容

- Bucket 规划。
- Object Key 规则。
- 上传、下载、删除、临时 URL。
- SHA-256。
- MIME 和文件签名。
- 引用计数。
- 大文件流式处理。

### 测试

- Testcontainers MinIO。
- 重复上传。
- 权限隔离。
- 共享文件删除。
- 中断上传清理。

### 验收标准

- ObjectStore 契约测试通过。
- 数据库和对象存储无悬空记录。

---

## C04：SSE 真实实现

### 目标

将任务事件可靠推送给前端。

### 实现内容

- 数据库 TaskEvent。
- Redis 临时通知。
- sequence。
- Last-Event-ID。
- 断线续传。
- 最终事件关闭。

### 测试

- 断线重连。
- 事件去重。
- 页面刷新。
- Redis 重启。

### 验收标准

- 不丢失最终状态。
- 事件顺序稳定。

---

# 阶段 D：会话、工作空间和记忆

## D01：Conversation 与 Message

### 目标

实现完整历史会话能力。

### 功能

- 创建、重命名、搜索、分页和删除会话。
- 消息分页。
- 消息与文件关联。
- 删除单条/范围消息。
- 会话列表排序。

### 测试

- CRUD。
- 分页稳定性。
- 删除级联。
- Workspace 隔离。

### 验收标准

- 历史聊天可查看。
- 删除消息不再由 API 返回。

---

## D02：ConversationWorkspace 和 TaskWorkspace

### 目标

实现会话持久空间和任务隔离执行视图。

### 功能

- 创建 uploads/shared/tasks/artifacts。
- Task 的 inputs/scratch/scripts/outputs/logs。
- WorkspaceEntry。
- Manifest。
- 本地挂载与 MinIO 同步。
- Promote。
- 清理策略。
- 来源追踪。

### 安全测试

- `..`。
- 绝对路径。
- 符号链接逃逸。
- 跨 Task/会话读取。
- 非法文件类型。

### 验收标准

- 路径逃逸阻断率 100%。
- 并行任务目录隔离。
- Worker 重启可恢复。
- 脚本默认不可执行。

---

## D03：Workspace 搜索

### 目标

让后续对话找到此前任务产生的内容。

### 功能

- 元数据索引。
- 文本提取。
- 内容摘要。
- Embedding。
- 按当前 Task、当前 Conversation、历史 Conversation 分级检索。
- 返回 entry_id、来源 Task/Tool/Message。

### 测试

- 查找旧脚本。
- 查找旧输出。
- 删除后失效。
- 同名文件区分。

### 验收标准

- 历史文件定位成功率 ≥ 95%。
- 来源可追溯率 100%。

---

## D04：短期 Memory

### 目标

实现当前会话长对话记忆。

### 功能

- 最近消息窗口。
- 8～12 条或 Token 阈值触发摘要。
- MemorySegment。
- 摘要 Embedding。
- 先检索摘要，再回读原消息。
- 删除后摘要失效和重建。

### 测试数据

- 20 个长会话。
- 每个会话 10 个历史问题。

### 验收标准

- 摘要事实保持率 ≥ 90%。
- 原消息追溯 100%。
- Recall@5 ≥ 90%。

---

## D05：长期 Memory

### 目标

实现跨会话历史和偏好。

### 功能

- ConversationSummary。
- MemoryPreference。
- 两级跨会话检索。
- 历史 File/WorkspaceEntry 联动。
- 用户显式保存偏好。
- 删除和遗忘。

### 验收标准

- 跨会话 Recall@5 ≥ 85%。
- 历史文件定位 ≥ 95%。
- 删除内容再次检索率为 0。

---

# 阶段 E：真实 Agent Runtime

## E01：Model Registry 和基础客户端

### 目标

系统通过 Profile 调用基础 1.7B/4B，不绑定物理路径。

### 功能

- development/evaluation/production Profile。
- ModelVersion Manifest。
- OpenAI-compatible LLMClient。
- Fake/Real 切换。
- fallback。
- Trace 中记录模型版本。

### 验收标准

- 无 Adapter 时可运行。
- Profile 切换不改业务代码。
- 模型不可用时明确失败或 fallback。

---

## E02：Requirement Clarifier

### 目标

实现需求完整性判断和反问循环。

### 功能

- 检索 Memory/Workspace 后再判断。
- 一次 1～5 个问题。
- 最多两轮。
- WAITING_USER。
- 按现有信息继续。
- RequirementBrief。

### 验收标准

- Macro-F1 ≥ 90%。
- 缺失字段 Recall ≥ 95%。
- 不必要追问率 ≤ 10%。
- 用户回答后继续原 Task。

---

## E03：Skill Selector

### 功能

- 1.7B/规则粗筛。
- Top-3。
- 4B 或规则最终选择。
- Skill 正文按需加载。
- fallback。

### 验收标准

- Top-1 ≥ 90%。
- Top-3 Recall ≥ 98%。

---

## E04：Planner 和 Replanner

### 功能

- 结构化 Plan。
- DAG 依赖检查。
- 完成条件。
- Tool/Skill 存在检查。
- 最大 8 步。
- 最多两次重规划。

### 验收标准

- 可执行率 ≥ 90%。
- 依赖正确率 ≥ 95%。
- 未注册 Tool 调用为 0。

---

## E05：Executor、Budget 和 Termination

### 功能

- Tool 和子 Agent 调用。
- Token、步骤、时间和并发预算。
- 超时、取消和幂等。
- 状态持久化。
- 完成判断。

### 验收标准

- 死循环率为 0。
- Tool 参数合法率 ≥ 98%。
- 每次失败定位到具体 Step。

---

## E06：ContextBuilder

### 功能

- System Policy。
- Requirement Brief。
- Skill。
- Tool Schema。
- Plan。
- 最近消息。
- Memory。
- Workspace。
- RAG Evidence。
- Token 裁剪。

### 验收标准

- 不越权。
- 不超过 Profile 上下文预算。
- 来源信息可追踪。

---

## E07：Verifier

### 功能

- Schema 检查。
- 任务覆盖度。
- Claim-Evidence。
- 数字。
- 引用。
- 不可变项。
- 修复或失败建议。

### 验收标准

- 无证据严重结论能被识别。
- 规则检查不依赖生成模型。
- 最多触发两次修复。

---

# 阶段 F：Tool、Skill 和子 Agent

## F01：Tool Runtime

### 目标

完成 Tool 的注册、权限和执行框架。

### 功能

- Pydantic 参数。
- 白名单。
- 超时。
- 重试。
- 权限。
- idempotency_key。
- 输出截断和 data_ref。
- Trace。

### 验收标准

- 参数非法不执行。
- 越权字段被拒绝。
- 所有 Tool 可独立测试。

---

## F02：文件与 Workspace Tools

实现：

- list_workspace_files
- search_workspace_files
- read_workspace_entry
- write_workspace_entry
- promote_workspace_entry
- save_artifact

验收：

- 只能访问当前权限范围。
- 大结果写对象存储。
- Promote 有审计记录。

---

## F03：Skill Registry 和十一项 Skill

### 目标

逐个完善初始 Skill。

每个 Skill 必须有：

- manifest.yaml
- SKILL.md
- output.schema.json
- examples.json
- Tool 白名单
- Model Profile
- 终止和追问条件
- 单元测试

验收：

- 全部加载成功。
- 错误 Manifest 明确失败。
- Skill 版本进入 Trace。

---

## F04：paper_reader_agent

### 功能

- 单文件范围。
- Paper Card Schema。
- 证据列表。
- 缺失字段。
- 独立预算和 Profile。
- 不直接向用户发消息。

### 验收标准

- 文件越权为 0。
- Schema 合法率 ≥ 98%。
- 单个失败不影响其他子任务。

---

## F05：Sub-agent Manager

### 功能

- 父子 Task。
- Celery Group。
- 并发限制。
- 最大嵌套 1。
- 部分失败汇总。
- 取消传播。

### 验收标准

- 多论文任务可并发。
- 取消主任务可取消未开始子任务。

---

# 阶段 G：论文解析和 RAG

## G01：PDF 基础解析

### 功能

- PyMuPDF。
- 页码、文本和坐标。
- 页眉页脚。
- 阅读顺序。
- 章节。
- 质量评分。

### 验收标准

- 普通 PDF 字符提取率 ≥ 98%。
- 双栏顺序 ≥ 95%。
- 章节 F1 ≥ 90%。
- 页码映射 ≥ 98%。

---

## G02：OCR 和解析回退

### 功能

- 扫描检测。
- PaddleOCR/Tesseract Adapter。
- OCR 置信度。
- 回退策略。
- 低质量提示。

### 验收标准

- 扫描 PDF 不静默产生空索引。
- 回退过程可追踪。

---

## G03：结构化分块和索引

### 功能

- 父子分块。
- Section path。
- 页码/bbox。
- 前后关系。
- Embedding。
- pgvector HNSW。
- FTS。
- 幂等索引。

### 验收标准

- Chunk 100% 可追踪原文。
- 重复文件不重复 Embedding。

---

## G04：混合检索和 Reranker

### 功能

- 查询改写。
- Vector Top-30。
- Keyword Top-30。
- RRF。
- Reranker Top-8。
- Workspace/File 过滤。

### 验收标准

- Recall@5 ≥ 80%。
- Recall@10 ≥ 90%。
- MRR@10 ≥ 0.75。

---

## G05：引用回答

### 功能

- Claim-Citation。
- 程序分配 Citation ID。
- 证据页面打开。
- 不可回答。
- Claim-Evidence 检查。

### 验收标准

- 正确率 ≥ 80%。
- 引用支持率 ≥ 90%。
- 拒答率 ≥ 85%。
- 严重幻觉 < 3%。

---

# 阶段 H：论文领域功能

## H01：单论文分析

实现 Paper Card 和证据绑定。

验收：字段 F1 ≥ 85%。

---

## H02：多论文比较

实现并行阅读、字段标准化、比较矩阵和数字核验。

验收：

- 覆盖率 ≥ 90%。
- 数字正确率 ≥ 95%。
- 结论引用支持率 ≥ 90%。

---

## H03：Writing Brief 和 Evidence Map

### 目标

为撰写能力建立事实边界。

### 功能

- 章节类型。
- 目标语言/长度/风格。
- 用户要点。
- 用户事实。
- 证据 ID。
- 不可变项。
- 缺失信息。
- 事实/观点/推测分类。

### 验收标准

- 用户材料要点抽取 Recall ≥ 95%。
- 所有允许事实都有来源。

---

## H04：章节和段落初次撰写

### 功能

- 引言、相关工作、方法、实验、结果、讨论、结论。
- 段落计划。
- 草稿。
- 来源和缺失项。
- 标记为待用户审阅。

### 验收标准

- 要点覆盖率 ≥ 90%。
- 结构和连贯性 ≥ 4/5。
- 严重无依据事实 < 3%。

---

## H05：章节和段落改写

### 功能

- 命题提取。
- 不可变项。
- 结构重组。
- 压缩/扩写/润色。
- 修改说明。
- 回归检查。

### 验收标准

- 数字、公式和引用保留 ≥ 99%。
- 语义保持 ≥ 4.5/5。
- 学术风格 ≥ 4/5。

---

## H06：文献综述和引用核验

实现证据矩阵优先的综述和草稿 Claim 核验。

验收：事实 100% 可回溯到 Evidence Map 或明确标记为推断。

---

# 阶段 I：安全、观测、评测和交付

## I01：OpenTelemetry 和 Trace

覆盖 API、Task、Agent Step、Tool、Sub-agent、Model、Memory、Workspace、RAG。

验收：任一 task_id 可重建关键执行链。

---

## I02：安全加固

### 测试

- Workspace 越权。
- 路径穿越。
- 符号链接。
- Prompt Injection。
- 恶意文件。
- Tool 参数注入。
- 未授权脚本执行。

### 验收标准

- 越权和路径逃逸成功率为 0。
- Prompt Injection 阻断率 ≥ 95%。
- 普通 Worker 不执行生成脚本。

---

## I03：SandboxExecutor

如果产品启用代码或 LaTeX 执行，完成一次性沙箱；否则只保留 Fake 和明确的“不可执行”错误。

验收：

- inputs 只读。
- 默认无网络。
- 资源限制有效。
- 结束后销毁。
- 输出扫描后写回。

---

## I04：自动评测框架

实现 Contract、Component、Trajectory、Domain、E2E、Security、Performance 报告。

验收：

- 一条命令运行选定评测。
- 报告记录 Commit、配置、Profile、Skill 和数据集版本。

---

## I05：Docker Compose 和部署

服务：

- web
- api
- worker
- postgres
- redis
- minio
- model-router
- model servers
- observability

验收：

- 全新环境按 README 启动。
- 健康检查有效。
- 模型不可用时有明确降级。

---

## I06：最终端到端验收

运行：

1. 单论文问答。
2. 需求澄清。
3. 多论文比较。
4. 历史 Memory。
5. Workspace 脚本检索。
6. 章节撰写。
7. 章节改写。
8. 失败重规划。
9. 取消和恢复。
10. 删除和遗忘。

系统验收：

- 核心任务完成率 ≥ 80%。
- 死循环率 0。
- 引用支持率 ≥ 90%。
- 删除内容不可检索。
- 无 SFT/RL Adapter 也能运行。

---

# 阶段 J：独立模型训练

## J01：训练工程与数据契约

建立独立 `training/`，只读取导出的数据、Schema 和 Tool 定义。

验收：训练代码不依赖 API、数据库或 Worker 运行。

---

## J02：1.7B SFT/RL

分别训练：

- router/skill_selector
- query_rewriter
- tool_caller

按技术栈文档中的数据规模、指标和晋级标准执行。

---

## J03：4B SFT/RL

分别训练：

- requirement_clarifier
- planner/replanner
- paper_reader/paper_qa
- academic_drafting/academic_writer
- verifier

禁止将所有任务混成一个无差别 Adapter 后直接发布。

---

## J04：Model Profile 晋级

流程：

```text
训练 → 专项评测 → 历史任务重放 → 安全/性能回归
→ evaluation profile → production profile
```

验收：

- Trace 可定位 Base、SFT 和 RL Adapter。
- 可回滚到上一版本和基础模型。

---

## 4. 工作包状态记录

Codex 每完成一个工作包，在此更新状态：

| 工作包 | 状态 | 完成日期 | Commit/说明 |
|---|---|---|---|
| A01 | completed | 2026-06-19 | 创建项目目录结构、配置文件和 README |
| A02 | completed | 2026-06-19 | 创建 9 个 ADR 文件和模块依赖规则文档 |
| A03 | completed | 2026-06-19 | 定义 31 个强类型 ID、13 个枚举、错误模型 |
| A04 | completed | 2026-06-19 | 定义 6 个核心 Domain 实体 |
| A05 | completed | 2026-06-19 | 定义 23 个 Port 接口 |
| A06 | completed | 2026-06-19 | 定义 Agent Schema 和完整状态机 |
| A07 | completed | 2026-06-19 | 定义 API Schema 和 SSE 事件契约 |
| B01 | completed | 2026-06-20 | FastAPI、类型化配置、DI 容器、健康检查、统一错误与关联 ID 中间件 |
| B02 | completed | 2026-06-20 | Worker 入口、四类任务、取消令牌、重试策略、FakeQueue、Handler Registry 与 API 投递链路 |
| B03 | completed | 2026-06-20 | Next.js 页面骨架、完整交互入口、本地 Mock API、18 项组件/交互测试与生产构建 |
| B04 | completed | 2026-06-20 | 全 Port Fake 组合根、确定性输出、故障注入及 Workspace 隔离契约修复 |
| B05 | completed | 2026-06-20 | Port-only Runtime Stub、节点顺序、逐步持久化、取消与预算策略 |
| B06 | completed | 2026-06-20 | Tool/Skill 注册格式、11 个能力型 Skill 契约、paper_reader_agent 与逻辑 Model Profile |
| B07 | completed | 2026-06-20 | API + FakeQueue + Runtime 九场景控制流、事件顺序与 Trace 门禁 |
| C01 | completed | 2026-06-20 | SQLAlchemy 2 Models/Repositories/UoW、Workspace 隔离、软删除/引用计数、乐观锁、Alembic 与 pgvector Testcontainers 验收 |
| C02 | completed | 2026-06-20 | Redis 真实队列/取消/锁/EventPublisher、Celery 四队列路由、数据库任务真值、重试/死信/崩溃恢复 Testcontainers 验收 |
| C03 | completed | 2026-06-20 | MinIO Bucket/Key、Workspace 隔离、SHA-256/MIME/签名、引用计数、流式上传与 Testcontainers 验收 |
| C04 | completed | 2026-06-20 | 数据库 TaskEvent、Redis 通知、稳定 sequence、Last-Event-ID、断线续传、最终事件关闭与 Redis 重启恢复 |
| D01 | completed | 2026-06-20 | Conversation/Message CRUD、搜索排序分页、附件关联、范围删除、级联与 Workspace 隔离 |
| D02 | completed | 2026-06-20 | Conversation/Task Workspace、Manifest、MinIO 同步、Promote、恢复/清理与路径安全 |
| D03 | completed | 2026-06-20 | Workspace 元数据/文本/摘要/Embedding、分级检索、删除失效与 100% 来源追溯 |
| D04 | completed | 2026-06-20 | 最近窗口、阈值摘要、MemorySegment、Embedding、原消息回读、删除失效重建与 200 问题评测 |
| D05 | completed | 2026-06-20 | ConversationSummary、显式 Preference、跨会话/历史文件两级检索、删除与遗忘，Recall@5/文件定位 100% |
| E01 | completed | 2026-06-20 | development/evaluation/production Profile、ModelVersion Manifest、OpenAI 兼容客户端、Fake/Real 路由、fallback 与版本 Trace |
| E02 | completed | 2026-06-20 | Memory/Workspace 检索优先、RequirementBrief、1–5 问题、两轮上限、等待/恢复原 Task 与 204 样例评测 |
| E03 | completed | 2026-06-20 | manifest 规则粗筛、Top-3、规则终选、Skill 正文按需加载、fallback 与 220 样例评测 |
| E04 | completed | 2026-06-20 | 结构化 Plan、最多 8 步、DAG/完成条件/注册项校验、两次 Replan 上限与 100 计划评测 |
| E05 | completed | 2026-06-20 | 有限 DAG Executor、步骤/工具预算、取消、超时、幂等重入、逐步持久化与 step_id 失败定位 |
| E06 | completed | 2026-06-20 | Policy/Brief/Skill/Tools/Plan/消息/Memory/Workspace/RAG 组装、来源标记与 Profile Token 裁剪 |
| E07 | completed | 2026-06-20 | Schema/任务覆盖、Claim-Evidence、数字、引用、不可变项规则检查与最多两次修复 |
| F01 | completed | 2026-06-20 | Pydantic 输入输出、Registry/Skill 白名单、权限、超时重试、幂等、data_ref 输出与 Trace |
| F02 | completed | 2026-06-20 | list/search/read/write/promote/save_artifact、Workspace/Task 隔离、对象存储与 Promote 审计 |
| F03 | completed | 2026-06-20 | 十一项能力 Skill 四件套、Tool 白名单/Profile、追问/终止/验收条件、Schema 示例校验与版本 Trace |
| F04 | completed | 2026-06-20 | 单文件范围、完整 Paper Card/证据/缺失字段、独立预算/Profile、深度限制与静默结果 |
| F05 | completed | 2026-06-20 | 父子 Task 持久化、Celery Group、并发/深度限制、部分失败汇总与主任务取消传播 |
| G01 | completed | 2026-06-20 | PyMuPDF 页码/文本/bbox、页眉页脚、双栏阅读顺序、章节、质量评分与固定指标评测 |
| G02 | completed | 2026-06-20 | 扫描检测、PaddleOCR/Tesseract 可选 Adapter、置信度、主备回退、低质量提示与 Trace |
| G03 | completed | 2026-06-20 | 父子 Chunk、Section/page/bbox/邻接、Embedding、pgvector HNSW、FTS、幂等与删除失效 |
| G04 | completed | 2026-06-20 | 规则查询改写、Vector/Keyword Top-30、RRF、Reranker Top-8、Workspace/File 过滤与指标评测 |
| G05 | completed | 2026-06-20 | Claim-Citation、程序 Citation ID、PDF 页面/bbox 定位、不可回答、Claim-Evidence 检查与指标评测 |
| H01 | completed | 2026-06-20 | Paper Card 八类字段、Evidence 绑定、缺失字段、防补造与 100 样例字段 F1 评测 |
| H02 | completed | 2026-06-20 | Paper Card 字段标准化、比较矩阵、数字核验、证据支持结论与指标评测 |
| H03 | completed | 2026-06-20 | Writing Brief、Evidence Map、章节约束、用户要点、来源事实、不可变项、缺失信息与分类 |
| H04 | completed | 2026-06-20 | 七类章节/段落计划、Evidence Map 约束草稿、来源/缺失项、待审阅与 100/200 任务评测 |
| H05 | completed | 2026-06-20 | 命题/数字/公式/术语/引用不可变项、四类改写、修改说明、语义/事实回归与 200 样例评测 |
| H06 | completed | 2026-06-20 | Evidence Matrix 优先综述、Claim 引用核验、事实 100% 追溯、推断标记与 Tool Runtime 集成 |
| I01 | completed | 2026-06-20 | 数据库 Trace Span、task_id 全链重建、OpenTelemetry 属性语义、模型/正文/密钥脱敏与迁移 |
| I02 | completed | 2026-06-20 | Workspace/路径/符号链接、Prompt Injection 100% 阻断、恶意文件、Tool 注入与脚本不执行 |
| I03 | completed | 2026-06-20 | 产品禁用代码/LaTeX 执行的正式 SandboxExecutor、统一不可执行错误和无普通 Worker 回退 |
| I04 | completed | 2026-06-20 | Contract/Component/Trajectory/Domain/E2E/Security/Performance 七层评测、单命令选择与版本化报告 |
| I05 | completed | 2026-06-20 | Docker Compose 十服务、全健康检查、全新环境启动说明、Fake 默认链与模型不可用结构化降级 |
| I06 | completed | 2026-06-21 | 十场景最终 E2E 100%、死循环 0、引用支持 100%、删除失效、无 Adapter 运行与全量交付文档 |
| J01 | completed | 2026-06-21 | 独立 training 包、版本化 JSONL/Manifest、Tool/Schema 哈希快照、隐私授权与论文/会话 split 隔离 |
| J02 | blocked | 2026-06-21 | 分任务配方与预检已完成；缺少 2K–5K+ 审核数据、Qwen3-1.7B 基座和 Torch/Transformers/PEFT/TRL 环境，禁止伪训练 |
| J03 | pending |  |  |
| J04 | pending |  |  |

状态只使用：

- `pending`
- `in_progress`
- `blocked`
- `completed`

不得在未通过验收时标记 `completed`。
