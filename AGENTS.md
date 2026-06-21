# PaperAgentSystem Codex 开发指令

本文件适用于整个仓库。Codex 每次开始工作前必须先读取本文件。

## 1. 必读文档顺序

1. `AGENTS.md`
2. `01-技术栈文档.md`
3. `02-产品架构文档.md`
4. `03-执行计划文档.md`
5. `DEVELOPMENT_PLAN.md`
6. 当前目录下更具体的 `AGENTS.md`，如果存在

若文档冲突：

1. 用户当前明确指令优先。
2. `AGENTS.md` 的工程规则优先于一般计划描述。
3. 产品行为以 `02-产品架构文档.md` 为准。
4. 技术选型以 `01-技术栈文档.md` 为准。
5. 开发顺序和工作包以 `DEVELOPMENT_PLAN.md` 为准。

发现冲突时不要静默选择；应指出冲突并更新相关文档。

## 2. 工作包执行规则

- 默认一次只执行 `DEVELOPMENT_PLAN.md` 中一个工作包。
- 开始前确认前置工作包已完成。
- 将该工作包状态改为 `in_progress`。
- 检查 Git 状态和现有代码，不覆盖用户未提交修改。
- 先写或更新测试，再完成实现。
- 运行工作包要求的全部检查。
- 验收全部通过后，将状态改为 `completed`。
- 最终回复必须列出：
  - 完成的工作包。
  - 主要改动。
  - 执行的测试及结果。
  - 未解决风险。
  - 建议的下一个工作包。
- 如果无法完成，保持 `in_progress` 或标记 `blocked`，明确阻塞原因。
- 不得为了看起来有进展而跳过测试或降低验收标准。

## 3. 自顶而下架构原则

- 先 Domain、Schema、Port 和契约，后真实 Adapter。
- 所有外部系统必须通过 Port 访问。
- Application/Domain 不直接依赖 FastAPI、SQLAlchemy、Celery、Redis、MinIO、vLLM。
- Fake 与真实实现必须通过相同契约测试。
- 不允许临时从上层直接调用基础设施绕过 Service/Port。
- 真实实现要求修改多个调用方时，先审查 Port 是否设计错误。
- 不提前实现后续工作包中的真实模块，除非当前工作包必须。

## 4. 代码结构规则

- Python 使用 3.12、类型标注、Pydantic 2、SQLAlchemy 2 风格。
- 前端使用 TypeScript 严格模式。
- API Route 只做协议转换、鉴权和应用服务调用。
- Worker Handler 不包含核心业务逻辑。
- Domain Entity 不包含 ORM、HTTP 或队列对象。
- 配置通过环境和类型化 Settings 注入。
- 时间统一使用 UTC。
- ID 使用强类型，不在模块间传裸字符串。
- 错误使用统一 ProjectError/ErrorCode。
- 不创建无意义的 `utils.py`；辅助代码按职责归属模块。
- 不提交模型权重、用户论文、上传文件、密钥和真实私有数据。

## 5. Agent Runtime 不变量

- 显式状态机是任务状态真值。
- 每个动作前检查取消、权限和预算。
- 每个动作后持久化状态和 Trace。
- Skill 选择和规划前执行 Requirement Check。
- 信息不足时一次提出 1～5 个关键问题。
- 默认最多两轮澄清。
- 用户回答后恢复原 Task，不创建无关 Task。
- 简单任务不得过度规划。
- Plan 默认最多 8 步。
- 重规划最多 2 次。
- 子 Agent 最大嵌套深度为 1。
- Agent 不得无限反思或循环。
- 不向用户展示隐藏推理，只展示可理解的进度摘要。

## 6. Tool 和 Skill 规则

- Tool 必须原子化、结构化、可独立测试。
- 所有 Tool 输入输出使用 Pydantic Schema。
- Tool 只能从 Registry 调用。
- Skill 必须限制 Tool 白名单。
- Tool 不接受任意绝对路径。
- workspace_id、user_id 和权限字段由系统注入，模型不能提供或覆盖。
- 写操作只能写当前 TaskWorkspace 允许区域。
- 删除、外部发送和其他高风险副作用需要明确确认策略。
- Skill 必须包含 Manifest、说明、输出 Schema、示例和验收规则。
- Skill 只引用 `model_profile`，不引用物理模型路径。

## 7. Workspace 和沙箱规则

- 每个 Conversation 有持久工作空间。
- 每个 Task 有隔离子目录。
- 文件访问使用 `file_id` 或 `workspace_entry_id`。
- 禁止绝对路径、`..`、符号链接逃逸和跨任务目录访问。
- 本地任务目录只是执行视图；MinIO/S3 和 PostgreSQL 是持久化真值。
- `scratch` 可清理；`shared` 和 `artifacts` 由用户管理。
- Agent 可以生成和保存脚本，但默认不得执行。
- Python、Shell、LaTeX、安装依赖或论文附带代码必须使用 SandboxExecutor。
- 未实现真实沙箱前，应返回明确的不可执行错误，不得用普通 Worker 代替。

## 8. Memory 规则

- 原始消息和文件是事实来源，摘要只用于定位。
- 短期 Memory：最近消息 + 当前会话 MemorySegment。
- 长期 Memory：ConversationSummary、明确保存的偏好和历史文件。
- 检索摘要后必须可回读原始消息。
- 只有用户引用历史或任务需要时才扩大跨会话检索。
- 不把临时表达自动保存为长期偏好。
- 删除消息、会话或文件后，相关摘要、Embedding 和缓存必须失效。
- 已删除内容再次被检索的比例必须为 0。

## 9. 模型和训练解耦规则

- Agent Runtime 只调用 Model Profile。
- 不在 Skill、子 Agent 或业务代码中硬编码权重路径。
- 系统必须在没有 SFT/RL Adapter 时使用基础 1.7B/4B 运行。
- 所有模型文件统一位于 `models/` 逻辑目录。
- 大权重不提交 Git；提交 Manifest、Profile 和评测报告。
- 训练代码独立位于 `training/`。
- 用户私有会话默认不得进入训练数据。
- Adapter 未通过专项、端到端、安全和性能评测不得晋级。
- 每次调用 Trace 记录 Base、SFT Adapter、RL Adapter 和 Profile 版本。

## 10. 论文事实与写作规则

- 事实性回答必须尽可能绑定证据。
- Citation ID 由程序生成，不由模型自由伪造。
- 证据不足时明确拒答或标记缺失。
- 章节撰写必须先构建 Writing Brief 和 Evidence Map。
- 方法、实验和结果不得补造用户未提供的信息。
- 草稿必须标记为需要用户审阅。
- 改写前提取数字、公式、术语、实体和引用等不可变项。
- 改写后必须执行语义和不可变项回归检查。
- 不提供伪造数据、伪造引用、规避查重或规避 AI 检测能力。

## 11. 测试要求

按变更范围运行最小充分测试，并在工作包结束前运行相关组合：

- Contract：所有 Port、Schema 和 Fake/Real 一致性。
- Unit：纯逻辑、状态机、策略和转换。
- Integration：PostgreSQL、Redis、MinIO、模型 Mock。
- E2E：用户场景和任务状态。
- Evaluation：检索、引用、Memory 和领域质量。
- Security：越权、路径逃逸、Prompt Injection、恶意文件。

规则：

- 普通 CI 不调用真实大模型，使用 FakeLLM。
- 真实模型评测单独运行并记录 Profile。
- Bug 修复必须增加回归测试。
- 不允许删除或弱化失败测试来使 CI 通过。
- 不能运行测试时，最终报告必须说明原因和未验证范围。

## 12. 数据与安全

- 所有查询强制 Workspace 隔离。
- 文件同时检查 MIME 和签名。
- 日志不得记录密钥和不必要的完整论文正文。
- Prompt、论文和外部文件均视为不可信输入。
- 文档内容不能改变 System Policy、Tool 权限或 Model Profile。
- 数据删除必须覆盖原始对象、派生索引、Embedding 和缓存。
- 训练/验证/测试按论文和会话隔离。

## 13. Git 和文件编辑

- 修改前查看 `git status` 和相关 diff。
- 保留用户已有修改。
- 不使用 `git reset --hard`、强制 checkout 或其他破坏性命令。
- 文件编辑应小而聚焦。
- 不顺手重构无关模块。
- 不提交生成缓存、模型权重和本地环境目录。
- 除非用户要求，不主动创建 Commit 或推送。

## 14. 文档同步

以下变化必须同步文档：

- 新增或修改 Domain/Port/API/SSE。
- 状态机变化。
- Tool、Skill、子 Agent 或 Model Profile 变化。
- Workspace、Memory、删除和安全语义变化。
- 技术选型变化。
- 验收指标变化。

更新优先级：

- 技术实现：`01-技术栈文档.md`
- 产品行为：`02-产品架构文档.md`
- 阶段策略：`03-执行计划文档.md`
- 具体工作包和状态：`DEVELOPMENT_PLAN.md`

## 15. 禁止事项

- 禁止绕过 Port 直接耦合基础设施。
- 禁止让模型获得任意文件系统路径。
- 禁止普通 Worker 执行生成脚本。
- 禁止把全部历史消息无限塞入上下文。
- 禁止让子 Agent 递归创建子 Agent。
- 禁止将一个万能 Prompt 代替 Skill 和 Tool 设计。
- 禁止在系统尚未有固定评测集时宣称训练有效。
- 禁止将计划中的功能写成已经完成。
- 禁止用占位实现冒充工作包验收通过。


## 16. 过程记录

- 每次完成一次任务后，都必须在“D:\vscode\Projects\PaperAgentSystem\develop_guide\process_log.md”按照如下格式记录本次更新的事项：
  示例：
  “- Time: `2026-05-18 10:12`
    - Step: Add system default PPT rebuild utility script.
    - Completed Work: Added `main/backend/app/templates/ppt/system_default/rebuild_template_ppt.py` to rebuild `template.pptx` with byte-level copy for exact fidelity; added optional embedded asset extraction (`ppt/media`, `ppt/theme`) into local directory.
    - Verification: Script path exists and matches target directory; architecture document updated to include the new script.
    - Open Issues: None.”

- 每次更新后，都必须同步更新“D:\vscode\Projects\PaperAgentSystem\develop_guide\02-产品架构文档.md”中发生修改的部分。
- 每次完成任务后，都必须更新“README.md”中对应的部分。如果是收低完成，则按照Github上高收藏项目写一份这个项目的介绍。