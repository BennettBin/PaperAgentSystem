# PaperAgentSystem 四方向深化实施计划

> 文档状态：Draft V1  
> 创建日期：2026-07-21  
> 目标：将现有论文 Agent 从“功能完整的工程系统”深化为“规划可解释、协作可度量、评测可信、模型可优化”的作品级 Agent 系统。  
> 适用范围：动态规划与执行、多智能体协作、统一评测平台、小模型专项训练与模型级联。  
> 前置文档：`AGENTS.md`、`01-技术栈文档.md`、`02-产品架构文档.md`、`03-执行计划文档.md`、`DEVELOPMENT_PLAN.md`。  
> 建议阶段编号：L（评测基线）、M（动态规划）、N（多智能体）、O（专项训练与模型级联）、P（闭环集成与作品交付）。

---

## 1. 总体目标

本计划不以继续增加论文功能数量为主要目标，而是解决以下四个核心问题：

1. 将当前模板式 DAG Planner 升级为能根据任务、Observation、证据充分度和预算动态决策的 Plan-and-Execute Runtime。
2. 将当前单一 `paper_reader_agent` 并行调度升级为具有明确角色、协作协议、共享证据空间和冲突仲裁机制的多智能体系统。
3. 将现有以固定样例和工程检查为主的评测升级为效果、轨迹、效率、成本、安全一体化的可信评测平台。
4. 真正完成 1.7B 专项模型训练、置信度校准和 1.7B/4B Model Cascade，在质量约束下减少大模型调用和 Token 成本。

最终应形成以下可验证能力：

- 复杂任务能够生成结构化、有依赖、有完成条件、有预算的执行计划。
- 工具失败、证据不足、章节歧义、预算紧张或子任务部分失败时能够切换策略，而不是仅重试原步骤。
- 多论文综述任务能够由多个角色型 Agent 协作完成，且可量化 Critic、Verifier 等角色的真实贡献。
- 所有核心结论能够由固定数据集、版本化配置、真实模型 Trace 和可重复命令复现。
- 小模型专项训练不是简历描述或占位配置，而是具有数据、训练产物、评测报告、晋级和回滚记录的真实 Adapter。
- 能清晰回答“相比 Vanilla RAG、固定 Workflow、ReAct 和全 4B 方案提升了什么、付出了什么成本”。

---

## 2. 不变量与实施原则

### 2.1 架构不变量

- 显式状态机仍是 Task 状态真值，不允许以通用 Agent 框架绕过现有 Runtime。
- Planner、Executor、Tool、Sub-agent、Model 和 Evaluation 继续通过 Schema/Port 解耦。
- 每个动作前检查取消、权限和预算；每个动作后持久化状态、Observation 和 Trace。
- Plan 默认最多 8 步，重规划最多 2 次，子 Agent 最大嵌套深度为 1。
- Tool 只能通过 Registry 调用，Skill 必须限制 Tool 白名单。
- 不向用户或评测报告保存模型隐藏推理；只保存结构化 decision、公开 reason summary、action 和 observation。
- 原始消息和文件是事实来源，摘要和共享 Blackboard 只能用于定位。
- 训练、验证和测试必须按论文、会话、任务族隔离，禁止同源样本泄漏。

### 2.2 真实性门禁

- FakeLLM/FakeRetriever 可以用于单元、契约和普通 CI，但不得用于生成“真实模型效果”指标。
- 真实评测报告必须记录模型版本、量化方式、Prompt/Skill 哈希、数据集版本、Commit、硬件和随机种子。
- 训练未实际运行、Adapter 未生成或专项评测未通过时，不得标记为完成，也不得在 README/简历中宣称完成 LoRA/SFT。
- “任务完成率”“引用支持率”等指标必须同时写明分母、样本来源、评审方式和置信区间。
- 所有优化必须与至少一个可复现 Baseline 对比，禁止只报告优化后绝对值。

### 2.3 Codex 工作方式

- Codex 每次只处理一个工作包；开始前检查 `git status`、前置工作包和相关目录 `AGENTS.md`。
- 工作包开始时在主开发计划或本计划状态表中标为 `in_progress`，验收全部通过后才能标为 `completed`。
- 先补契约和失败用例，再实现功能；不得删除或弱化失败测试。
- 每个工作包结束时同步架构文档、README、过程日志和必要 ADR。
- 仓库存在大量未提交修改时，Codex 必须先定位重叠文件；不得覆盖用户修改。
- 涉及真实模型下载、训练、GPU 长任务和外部 Judge API 时，必须在执行前确认资源与费用边界。

---

## 3. 总体阶段与依赖关系

```text
K04.3/K04.4 收尾
        │
        ▼
L：可信评测基线与数据集
        │
        ├──────────────┐
        ▼              ▼
M：动态规划系统     N：多智能体协议与场景
        │              │
        └──────┬───────┘
               ▼
O：1.7B 专项训练与 Model Cascade
               │
               ▼
P：统一集成、在线闭环与作品交付
```

强制依赖：

- K04.3、K04.4 未完成前，不启动需要稳定章节检索语义的真实效果评测。
- L01～L05 未完成前，不以新 Planner、多 Agent 或 SFT 的结果对外宣称提升。
- M 的 Planner/Trajectory Schema 稳定后，N 才能将多 Agent 协作编入统一 Plan。
- O 的训练数据必须来自已冻结的 Schema、真实 Trace 和已去重评测体系。
- P 阶段只做集成和交付，不在该阶段临时修改核心算法以追逐指标。

---

# 阶段 L：可信评测基线与数据闭环

## L00：现状审计与实验冻结

### 目标

建立可重复的实验起点，明确哪些能力是真实实现、哪些指标来自 Fake、哪些模块仍在开发，防止后续对比失真。

### 实施内容

- 记录当前 Git Commit、未提交变更、Docker 服务版本、模型列表、Profile 和硬件信息。
- 审计现有 Planner、Replanner、Executor、Self-RAG、Sub-agent、Evaluation 和 Training 实现。
- 将评测标记为 `unit_fake`、`integration_real`、`offline_real_model`、`human_review` 四类。
- 为当前系统冻结四个 Baseline：
  - B0：Vanilla RAG，一次检索后直接回答。
  - B1：固定 Workflow，规则路由与固定工具序列。
  - B2：当前有限 Self-RAG/ReAct。
  - B3：全 4B 模型执行。
- 形成 `evaluation/baselines/*.yaml`，禁止在实验过程中隐式改变 Prompt、检索参数或模型。
- 新增 ADR，说明为什么核心 Runtime 保持自研状态机，以及与 LangChain/LangGraph/AutoGen 的能力映射。

### 产物

- 现状审计报告。
- 四套版本化 Baseline 配置。
- 实验环境 Manifest。
- Agent 框架选型与映射 ADR。

### 验收标准

- 任意报告均能定位到 Commit、数据集、Profile、模型版本和配置哈希。
- Fake 结果与真实模型结果在报告和 Dashboard 上不可混淆。
- 四个 Baseline 均能通过同一个 Runner 执行。
- 同一 Baseline 连续运行两次时，确定性指标一致；生成指标差异处于预设容差内。
- 文档明确当前 LoRA/SFT 和 1.7B/4B 的真实完成状态。

### 验证

- Baseline 配置 Schema 单元测试。
- Metadata 完整性测试。
- 报告缺少关键字段时 fail-closed 测试。

---

## L01：评测任务分类与数据契约

### 目标

建立覆盖简单工具调用到复杂多论文综述的统一任务数据模型。

### 实施内容

- 定义六级任务难度：
  - L1：意图识别、Skill 选择、单 Tool 参数生成。
  - L2：单论文单步事实问答。
  - L3：单论文跨章节、多步检索与推理。
  - L4：多论文比较和冲突识别。
  - L5：综述写作、Evidence Matrix 和逐 Claim 引用核验。
  - L6：歧义澄清、工具故障、部分失败、Prompt Injection、取消与恢复。
- 定义 `EvaluationCase`、`ExpectedTrajectory`、`ReferenceAnswer`、`EvidenceGold`、`JudgeResult` Schema。
- 每条数据记录 task family、难度、论文集合、期望工具集合、必需证据、不可接受行为和资源预算。
- 数据集按 paper_id、conversation_id 和来源簇做 group split。
- 建立去重：文本指纹、Embedding 近重复和论文来源去重。
- 保留合法公开论文或自有授权材料，不将用户私有会话默认纳入评测或训练。

### 产物

- `evaluation/datasets/schema.py`。
- 数据集 Manifest 和 split Manifest。
- 数据审核与隐私检查脚本。
- 数据卡 `DATASET_CARD.md`。

### 验收标准

- Schema 对非法 case、缺失证据、未知 split 和越权数据拒绝加载。
- train/validation/test 的 paper_id 和 conversation_id 交集为 0。
- 近重复泄漏率为 0。
- 100% case 可追踪到来源、授权状态和构建版本。
- 数据卡说明适用范围、已知偏差和不可用于训练的测试集。

---

## L02：首版真实评测集建设

### 目标

将现有约 30 次会话式评测扩充为足以支持分层分析和置信区间的固定评测集。

### 实施内容

- MVP 至少构建 300 条真实评测任务，建议分布：L1 60、L2 60、L3 60、L4 45、L5 45、L6 30。
- 至少覆盖中英文论文、长短论文、单栏/双栏、章节缺失、扫描质量差和引用歧义情况。
- 为引用类任务标注 gold evidence span、页码、section 和 claim-support 关系。
- 为规划任务标注必需步骤、允许的替代路径和禁止的无效调用，不要求唯一轨迹。
- 为 E2E 任务定义可程序判定和需人工判定的子指标。
- 抽取 10% 双人复标，记录一致性；争议样本由第三方规则仲裁。

### 验收标准

- 固定 test 集不少于 300 条，且每个任务等级达到最低数量。
- 引用/证据任务的 span 和页码标注完整率为 100%。
- 双人标注一致性 Cohen's kappa ≥ 0.80；不足时修订标注指南并复标。
- 任一方法的总体指标可下钻到 task family、难度、语言和论文类型。
- 测试集不得被用于 Prompt few-shot、SFT、DPO 或阈值调优。

---

## L03：统一指标与 Judge 系统

### 目标

同时量化效果、轨迹、效率、成本和鲁棒性，避免只看最终答案。

### 实施内容

- 效果指标：Task Success、Answer Correctness、Citation Precision/Recall、Claim Support Rate、Hallucination Rate。
- 路由指标：Intent/Skill Top-1、Top-3、Tool Selection F1、Argument Exact/Schema Valid Rate。
- 轨迹指标：Plan Validity、Required Step Recall、Invalid Step Rate、Tool Success Rate、Replan Success Rate、Loop Rate。
- 效率指标：模型调用次数、Tool 调用次数、Token 输入/输出、P50/P95 latency。
- 成本指标：单位成功任务 Token、4B 调用比例、GPU 时间；若使用付费模型则记录货币成本。
- 鲁棒性指标：故障恢复率、部分失败可用率、取消响应时间、Prompt Injection 阻断率。
- Judge 采用“程序规则优先、LLM Judge 补充、人工抽检兜底”；LLM Judge 必须结构化输出理由摘要和引用依据。
- 对主指标输出 bootstrap 95% CI；成对方法使用 paired bootstrap 或合适的显著性检验。

### 验收标准

- 所有核心指标有公式、分母、适用范围和异常值处理说明。
- Judge 对 50 条人工金标的判定一致率 ≥ 90%。
- 同一回答重复 Judge 三次的一致率 ≥ 95%，否则改用更强规则或人工判定。
- 报告同时展示绝对值、相对 Baseline 变化和 95% CI。
- 不允许以格式合法率替代任务正确率。

---

## L04：实验 Runner、Trace 回放与报告

### 目标

实现一条命令运行 Baseline、候选系统和消融实验，并能从 Trace 重建轨迹。

### 实施内容

- 扩展 Evaluation Runner 支持并发、断点续跑、随机种子、失败重试和预算限制。
- 真实模型评测单独命令运行，普通 CI 仅跑小规模 smoke 集。
- 从 Trace 重建 decision/action/observation、Plan 版本、模型调用、Tool 结果和预算变化。
- 输出 JSON、Markdown 和可供前端 Dashboard 使用的聚合数据。
- 为失败任务生成 error taxonomy：路由、规划、检索、工具参数、生成、核验、系统和数据错误。
- 对比表至少支持 B0/B1/B2/B3 与一个 candidate。

### 验收标准

- 中断后续跑不会重复计费或污染已完成结果。
- 任意失败 case 能由 case_id/task_id 重建关键轨迹。
- 报告中 100% 模型调用可定位 model/profile/version 和 usage。
- 相同报告输入能生成一致聚合结果。
- 300 条任务全量运行没有未分类异常；系统异常率 < 1%。

---

## L05：基线测量与 Go/No-Go 门槛

### 目标

得到后续所有算法改造的可信比较起点。

### 实施内容

- 对 B0～B3 运行完整测试集。
- 输出总体、分层、错误类型、成本和延迟结果。
- 选定后续主要优化目标，例如 L3/L4 完成率、无效工具调用和 4B 调用比例。
- 冻结 v1 测试集和 Baseline 报告。

### 验收标准

- 四个 Baseline 均完成真实模型全量评测。
- 报告不存在 Fake 结果混入。
- 至少识别三个占比最高且可行动的失败类别。
- 后续 M/N/O 阶段各自具有明确的 success gate。

---

# 阶段 M：动态规划与执行系统

## M01：Planner/Trajectory Schema V2

### 目标

将当前“Skill + 固定工具列表”计划升级为表达目标、依赖、证据、预算、风险和替代路径的结构化 Plan。

### 实施内容

- 扩展 `PlanStep`：step type、input refs、expected output schema、evidence requirement、budget、risk、fallback、completion predicate。
- Plan 记录 `plan_id`、version、parent_plan_id、assumptions、global budget 和 termination condition。
- Observation 统一为结构化 Schema：status、data_ref、evidence refs、error code、retryability、quality signal 和 usage。
- Plan Patch 只描述增删改步骤，不原地覆盖历史 Plan。
- 保持最多 8 步、最多 2 次 Replan 和 DAG 无环约束。
- 为旧 Plan 提供显式迁移或兼容读取策略。

### 验收标准

- 非法依赖、循环、预算超限、未知 Tool/Skill/Sub-agent、缺失完成条件均 fail-closed。
- Plan V1 历史任务可读取或安全迁移。
- 100 个合法/非法 fixture 的 Schema 判定准确率为 100%。
- Trace 可展示 Plan V0→V1→V2 的差异和触发 Observation。

---

## M02：LLM Planner 与受约束生成

### 目标

让 4B Planner 根据 Requirement Brief、候选 Skill、Tool Schema、Memory/RAG 摘要和预算生成任务特定计划。

### 实施内容

- 使用 `generate_with_schema` 输出 Plan V2，不保存隐藏 CoT。
- Context 只加载 Top-K Skill、允许 Tool 的精简 Schema、相关证据摘要和预算。
- 生成后依次执行 Schema、Registry、权限、DAG、预算和可执行性验证。
- 失败时最多一次结构化修复；仍失败则回退到安全固定 Workflow。
- 简单任务走 Fast Path，不进行过度规划。
- 记录 Planner prompt/version/token/latency 和 fallback 原因。

### 验收标准

- Plan Schema Valid Rate ≥ 98%。
- Registry/权限非法调用率为 0。
- L1/L2 简单任务平均规划步骤不超过 3。
- L3～L5 的 Required Step Recall 相比 B1 提升 ≥ 10 个百分点，且 95% CI 不跨 0。
- Planner 失败时 100% 有安全回退或明确失败，不导致 Worker 崩溃。

---

## M03：完成条件与证据充分度判定

### 目标

避免 Agent 仅因 Tool 返回成功就认为任务完成，使计划执行由真实结果质量驱动。

### 实施内容

- 为不同 step type 定义可程序检查的 completion predicate。
- 引用型步骤检查 claim-evidence coverage、页码和证据来源。
- 比较型步骤检查目标论文覆盖、标准字段和数字核验。
- 写作型步骤检查 Evidence Map 覆盖、不可变项和待审阅标记。
- Completion Evaluator 输出 `complete / repair / replan / ask_user / fail`。
- 将质量信号写入 Observation，供 Replanner 使用。

### 验收标准

- 50 个“工具成功但结果不合格”的 fixture 中，漏判率 < 5%。
- 无证据事实不能被判定为完成。
- Completion Evaluator 与人工金标一致率 ≥ 90%。
- 不合格结果能够定位到具体缺失项，而非只返回通用失败。

---

## M04：策略型 Replanner

### 目标

根据失败类型改变执行策略，而不是给原步骤追加 retry 文本。

### 实施内容

- 建立失败分类：empty retrieval、ambiguous section、tool timeout、invalid arguments、insufficient evidence、budget pressure、sub-agent partial failure、verification failure。
- 为每类失败提供受限策略集合，例如 query rewrite、scope expansion、alternate tool、model escalation、evidence acquisition、partial aggregation、ask user。
- Replanner 输出 Plan Patch，并说明公开 reason summary。
- 同一策略对同一输入最多执行一次，防止伪重规划循环。
- 预算不足时优先压缩上下文、减少候选或降级输出，不允许静默突破预算。

### 验收标准

- 至少覆盖 8 类失败和 15 个故障注入场景。
- Replan 后 Plan 必须发生可观察的策略变化。
- Replan Success Rate 相比当前重试式 Replan 提升 ≥ 15 个百分点。
- 死循环率为 0；单任务 Replan 次数不超过 2。
- 预算、权限和取消门禁在 Replan 后仍保持有效。

---

## M05：动态 Executor 与恢复语义

### 目标

让 Executor 正确执行 Plan 版本、并行安全步骤、持久化 Observation，并支持幂等恢复。

### 实施内容

- Executor 按 Plan version 和 dependency graph 领取 ready steps。
- 只并行执行无依赖且副作用兼容的步骤。
- 每步完成后原子持久化结果、usage、Trace 和预算余额。
- Worker 崩溃后从最后稳定步骤恢复，不重复有副作用 Tool。
- 用户取消传播到模型调用、Tool 和子 Agent；终态后不再执行新动作。

### 验收标准

- 崩溃恢复场景不重复写 Artifact、不重复扣减预算。
- 并行步骤结果与串行语义一致。
- 取消响应 P95 ≤ 2 秒（不含不可中断外部调用的自然返回时间）。
- 故障注入下任务状态、Plan 状态和 Trace 一致。

---

## M06：Planner 对比实验与消融

### 目标

证明动态 Planner 的收益来自规划和反馈机制，而不是模型或 Prompt 差异。

### 实施内容

- 对比固定 Workflow、当前 ReAct、Plan-and-Execute V2、V2 + Completion、V2 + Completion + Replan。
- 所有组使用相同模型、检索、数据集和预算。
- 重点分析 L3～L6、故障恢复、无效工具调用和单位成功任务成本。

### 晋级验收标准

- L3～L5 Task Success 相比最佳旧 Baseline 提升 ≥ 8 个百分点。
- Invalid Tool Call Rate 降低 ≥ 25%。
- 故障场景恢复率提升 ≥ 15 个百分点。
- 单位成功任务 Token 增幅不超过 15%；若超过，必须证明质量收益具有统计显著性并记录权衡。
- 死循环率保持 0，严重越权调用为 0。

---

# 阶段 N：多智能体协作系统

## N01：角色与协作协议设计

### 目标

从“多个相同 Reader 并行”升级为职责清晰、输入输出明确、可组合和可评测的角色型 Agent。

### 实施内容

- 定义最小角色集合：
  - Coordinator/Planner Agent：拆解研究问题并分配论文。
  - Paper Reader Agent：提取 Paper Card 和证据。
  - Evidence Agent：合并 Claim–Evidence Matrix。
  - Critic Agent：查找冲突、遗漏、过度归纳和证据缺口。
  - Writer Agent：依据 Evidence Matrix 生成综述。
  - Verifier Agent：逐 Claim 核验支持关系和数字。
- 每个角色定义独立 Manifest、Profile、Tool 白名单、输入/输出 Schema、预算和停止条件。
- 定义消息信封，只允许传递结构化 Artifact/DataRef，不传隐藏推理。
- 子 Agent 不直接向用户发消息，不递归创建子 Agent。

### 验收标准

- 所有角色 Manifest 和 Schema 可独立加载、校验和测试。
- 角色越权 Tool 调用成功率为 0。
- 任一角色缺失或失败时，Coordinator 能按协议降级或明确失败。
- 协作协议文档包含数据所有权、冲突、超时、取消和重试语义。

---

## N02：共享 Evidence Blackboard

### 目标

提供可追踪、可并发更新、非自由文本堆积的共享协作空间。

### 实施内容

- 定义 Blackboard Entity：research question、paper card、claim、evidence、conflict、gap、draft section、verification result。
- 所有实体包含 producer agent、source file/message、citation、version 和 confidence。
- 使用乐观锁或 append-only event 防止并发覆盖。
- 摘要仅用于检索，事实结论必须回指原始 Evidence。
- 共享内容进入 TaskWorkspace/PostgreSQL 真值，不依赖 Worker 内存。
- 父任务结束、取消或删除时按现有 Workspace/Memory 规则清理派生数据。

### 验收标准

- 100% claim/evidence 可追踪到原 PDF 页码或明确标记为推断。
- 并发写入无静默覆盖；冲突被检测并保留双方版本。
- 删除原文件后相关 Blackboard Evidence 不可继续检索。
- Blackboard 重建结果与事件流一致。

---

## N03：Coordinator 与任务分派

### 目标

根据论文数量、任务目标、依赖和预算生成子任务图，并进行受控并发。

### 实施内容

- Coordinator 将主 Plan 中 `spawn_subagents` 步骤展开为子任务 DAG。
- 同一论文默认只创建一个 Reader；相同读取结果可由 Evidence/Writer 复用。
- 根据 GPU/Worker/Token 预算限制并发数。
- 支持 straggler timeout、部分失败汇总、取消传播和必要的单任务补跑。
- 子 Agent 结果必须先通过 Schema 和最小证据检查后才能写入 Blackboard。

### 验收标准

- 2、5、10 篇论文任务均能按预算完成分派。
- 相比串行执行，5 篇论文场景 wall-clock latency 降低 ≥ 30%。
- 重复阅读调用降低 ≥ 80%。
- 单 Reader 失败不导致已完成结果丢失；降级答案明确缺失论文。
- 最大嵌套深度始终为 1。

---

## N04：Critic—Writer—Verifier 协作闭环

### 目标

用明确的审稿和核验闭环减少遗漏、矛盾和无依据结论。

### 实施内容

- Evidence Agent 先构建矩阵，Writer 不直接读取未筛选的所有上下文。
- Critic 在写作前检查研究覆盖、相互矛盾结果、不可比较设置和证据缺口。
- Writer 必须响应 Critic 的结构化 issue，接受、拒绝或标记无法解决。
- Verifier 对草稿逐 Claim 检查引用、数字和推断标记。
- 最多一轮 Critic 修订和一轮 Verifier 修订，避免无限争论。
- 对无法解决的冲突在最终输出中显式披露。

### 验收标准

- 所有 Critic issue 有 resolution status。
- Verifier 后严重无依据事实率 < 3%。
- 冲突识别 Recall ≥ 85%，Precision ≥ 80%。
- 协作轮数有界，死循环率为 0。
- 最终内容 100% claim 可定位到 Evidence Matrix 或推断标签。

---

## N05：多智能体消融实验

### 目标

证明每个角色带来的增益，避免“Agent 越多越高级”的无效复杂化。

### 实施内容

- 对比：单 Agent、Reader 并行、+Evidence、+Critic、+Verifier、完整系统。
- 使用相同 4B 模型、相同论文集、相同最大 Token 预算。
- 衡量完成率、Claim Support、冲突发现率、遗漏率、Token、延迟和单位成功成本。
- 记录角色边际贡献和失败案例。

### 晋级验收标准

- 完整系统相对单 Agent 的 Claim Support Rate 提升 ≥ 8 个百分点。
- 冲突识别 Recall 提升 ≥ 20 个百分点。
- 严重无依据事实率降低 ≥ 50%。
- 总 Token 增幅不超过 40%；超过时应形成按任务复杂度启用多 Agent 的路由策略。
- 若某角色无显著贡献，应删除、合并或限制到特定任务，不得为展示概念而保留。

---

# 阶段 O：1.7B 专项训练与 Model Cascade

## O00：训练资源与合规前置检查

### 目标

解除 J02 的真实 blocker，并在产生训练成本前确认数据、基座、依赖和硬件可用。

### 实施内容

- 明确实际模型组合统一为 1.7B + 4B；如决定使用 8B，必须新增 Profile、硬件预算和完整实验，不得只改简历文字。
- 准备合法的 Qwen 1.7B 基座 Manifest、量化配置和校验哈希。
- 建立独立训练环境，安装 Torch、Transformers、Datasets、PEFT、TRL、Accelerate、bitsandbytes 等锁定版本。
- 记录 GPU 型号、显存、CUDA、预计时长、磁盘和失败恢复策略。
- 训练数据必须有授权、匿名化、去重和 split 审计。

### 验收标准

- J02 preflight 所有 blocker 清零。
- 基座模型、数据、依赖和硬件检查全部通过。
- 随机抽取 100 条训练数据人工审核，严重标签错误率 < 2%。
- 测试集及其近重复样本未进入训练集。
- 能在 100～500 条 smoke 数据上完成一次 QLoRA 前向、保存、加载和推理闭环。

---

## O01：专项任务与数据生成

### 目标

优先训练可客观评测、能显著减少 4B 调用的 1.7B 任务，而不是训练一个无差别万能 Adapter。

### 实施内容

- 第一优先级：Skill/Intent Router。
- 第二优先级：Tool Selector + Argument Generator。
- 第三优先级：Query Rewriter + Self-RAG Retrieval Decision。
- 可选第四优先级：Trajectory Error Classifier。
- 从真实 Trace、人工模板和强模型生成候选数据，再进行规则校验与人工抽样。
- 加入 hard negatives：相似 Skill、无须检索、缺少文件、章节歧义、非法参数和越权请求。
- 每个任务独立 Dataset Manifest，不混入完整论文正文作为不必要输入。

### 数据规模门槛

- Router：训练 ≥ 3,000，验证 ≥ 300，测试 ≥ 500。
- Tool Caller：训练 ≥ 5,000，验证 ≥ 500，测试 ≥ 800。
- Query/Self-RAG：训练 ≥ 3,000，验证 ≥ 300，测试 ≥ 500。
- 若达不到最低规模，工作包保持 blocked，不以少量样本训练结果对外宣称完成。

### 验收标准

- 数据 Schema 合法率 100%。
- train/validation/test 组间论文、会话和来源簇交集为 0。
- hard negative 占比达到 20%～40%。
- 每个样本可追踪构建方式、源数据和审核状态。

---

## O02：QLoRA SFT 实验

### 目标

为每个专项任务训练独立 Adapter，并形成可复现训练报告。

### 实施内容

- 先训练 Router，再按收益决定是否继续 Tool Caller 和 Self-RAG。
- 至少比较 2 组 LoRA rank/learning rate 配置，固定其余变量。
- 保存 training/eval loss、gradient norm、吞吐、显存、checkpoint 和 seed。
- 使用早停和最佳 validation checkpoint，不以 train loss 选择模型。
- Adapter Manifest 记录基座哈希、数据版本、超参数和代码 Commit。

### 验收标准

- 训练可从 checkpoint 恢复。
- 无 NaN/Inf、数据读取异常或测试集污染。
- Router Top-1 ≥ 92%、Top-3 ≥ 98%，且相对 Base 1.7B 提升 ≥ 5 个百分点。
- Tool 参数 Schema Valid Rate ≥ 95%，Exact/semantic accuracy 相比 Base 提升 ≥ 8 个百分点。
- Self-RAG decision macro-F1 ≥ 90%，且对“无文件但需论文证据”场景召回 ≥ 95%。
- 未达到专项门槛的 Adapter 不进入 evaluation Profile。

---

## O03：难例挖掘与可选 DPO

### 目标

针对 SFT 后仍频繁出现的混淆和格式错误做定向优化，而不是盲目扩大训练规模。

### 实施内容

- 从 validation 和真实非测试 Trace 中聚类失败样本。
- 构建 chosen/rejected 对：正确 Skill vs 相似错误 Skill、合法参数 vs 幻造参数、应检索 vs 直接回答。
- 只有 SFT 达到基本门槛且存在明确偏好错误时才运行 DPO。
- 比较 Base、SFT、SFT+DPO，监控通用能力和安全回归。

### 验收标准

- 偏好数据无测试集泄漏，chosen/rejected 差异有明确标注理由。
- DPO 在目标 hard set 上相对 SFT 提升 ≥ 3 个百分点。
- 普通集性能下降不超过 1 个百分点。
- 安全违规率和非法工具调用率不得上升。
- 无显著收益时保留 SFT，不强行发布 DPO Adapter。

---

## O04：置信度校准与升级策略

### 目标

让 1.7B 不只输出决策，还输出可用于升级到 4B 的可靠置信度。

### 实施内容

- 比较 max probability、margin、self-consistency、额外 confidence head 或规则特征。
- 使用 validation 集做 temperature scaling/isotonic 等校准，测试集只做最终报告。
- 定义升级条件：低置信、Schema 修复失败、高风险任务、Verifier 失败、预算允许。
- 按任务族设置阈值，不使用一个全局拍脑袋阈值。
- 记录 calibration curve、ECE、coverage-risk curve。

### 验收标准

- Expected Calibration Error ≤ 0.05。
- 在目标 quality floor 下，能给出可重复的 1.7B coverage 和 4B escalation rate。
- 高风险错误样本升级召回 ≥ 95%。
- 阈值只由 validation 集确定。

---

## O05：1.7B/4B Model Cascade

### 目标

在质量约束下由 1.7B 完成简单路由和工具决策，将低置信或高风险任务升级到 4B。

### 实施内容

- Cascade 流程：1.7B decision → Schema/Policy check → confidence gate → 4B escalation → optional verifier escalation。
- 所有升级原因进入 Trace。
- 保留全 4B、Base 1.7B、SFT 1.7B、SFT Cascade 四个对比组。
- Model Registry 支持 Adapter 晋级、回滚和基础模型 fallback。
- 不同任务族可选择不同 Adapter，不将 Planner、Router、Writer 强行绑定到一个 Adapter。

### 晋级验收标准

- 相比全 4B，Task Success 下降不超过 2 个百分点。
- 4B 调用比例降低 ≥ 35%。
- 单位成功任务 Token 降低 ≥ 25%。
- P95 latency 降低 ≥ 20%。
- 严重无依据事实、安全违规和越权调用不得显著上升。
- Adapter 必须完成专项、E2E、安全和性能评测后才能进入 production Profile。

---

# 阶段 P：统一集成、自进化闭环与作品交付

## P01：统一 Agent Runtime 集成

### 目标

将 Planner V2、多 Agent、Model Cascade、Memory、RAG、Verifier 和 Trace 接入同一产品链路。

### 实施内容

- 确保 API/Worker 只通过 Port 和 Profile 调用新能力。
- 简单任务走 Fast Path；复杂多论文任务才启用 Planner 和多 Agent。
- 所有 Plan、子任务、模型升级和核验事件通过 SSE 提供公开进度摘要。
- 前端不显示隐藏推理，只显示目标、步骤状态、工具/Agent 名称、引用和失败原因。
- 旧任务恢复和旧数据迁移有明确策略。

### 验收标准

- 十个原最终 E2E 场景全部回归通过。
- 新增动态重规划、多 Agent 综述、模型升级三个真实 E2E 场景通过。
- 旧会话、旧任务和旧索引可读取或安全重建。
- Docker Compose 全新启动成功，无 Fake 默认回答链。

---

## P02：失败聚类与 Human-in-the-Loop 数据闭环

### 目标

建立可审计的“评测/线上失败→人工审核→数据候选→训练/Prompt 优化→回归评测”闭环。

### 实施内容

- 从 Trace 自动抽取失败 case，并按错误 taxonomy 聚类。
- 人工审核界面只展示必要上下文、证据和公开决策摘要。
- 用户私有数据默认不进入训练候选；必须显式授权、匿名化和去标识化。
- 候选数据进入 staging，不直接进入训练集。
- 每次数据晋级生成版本和变更报告。
- “自进化”限定为离线、评测门禁后的人审优化，不允许生产环境自动改权重或 Prompt。

### 验收标准

- 100% 训练候选有来源、授权、审核和版本记录。
- 私有未授权数据进入训练集的数量为 0。
- 数据晋级后自动运行历史回归和安全测试。
- 任一模型/Prompt 更新可回滚。

---

## P03：Evaluation Dashboard

### 目标

把效果、轨迹、效率和成本结果做成可演示、可下钻的产品能力。

### 实施内容

- 展示 Baseline/Candidate 对比、置信区间和版本信息。
- 按任务族、难度、语言、模型、错误类型筛选。
- 展示 Task Success、Claim Support、Token、4B 调用率、P95 latency 和单位成功成本。
- 支持从失败样本下钻到 Plan、Action、Observation、Citation 和公开 Trace。
- 严格隔离管理员评测页面与普通用户会话。

### 验收标准

- Dashboard 数值与离线 JSON 报告一致。
- 任一聚合指标可下钻到样本集合。
- 不展示密钥、完整私有论文正文或隐藏推理。
- 300 条报告加载和筛选在目标开发环境下 P95 < 2 秒。

---

## P04：最终对比实验与统计报告

### 目标

形成可用于简历、面试和项目 README 的可信结果。

### 实施内容

- 对最终系统和 B0～B3 跑冻结测试集。
- 运行 Planner、Multi-Agent、SFT、Cascade 四组消融。
- 输出总体与分层指标、95% CI、显著性、失败案例和限制。
- 进行至少 10% 人工抽检。
- 报告明确硬件、模型、数据版本和复现命令。

### 验收标准

- 所有对外指标均可从报告反查样本和 Trace。
- 指标同时包含样本数、分母、均值/比例和 95% CI。
- 不只报告正向结果，明确失败类别和适用边界。
- README 与简历只引用已通过真实评测的结果。

---

## P05：作品集与面试交付

### 目标

把技术实现转化为 HR 能理解、技术面试官能追问、本人能完整讲清的证据链。

### 实施内容

- README 首屏展示问题、架构图、核心指标对比和一键运行方式。
- 录制 3～5 分钟演示：复杂问题→动态 Plan→多 Agent→引用→Verifier→指标。
- 编写 Architecture Decision、Evaluation Report、Model Card、Dataset Card。
- 准备三个失败案例复盘，说明如何通过 Trace 定位并优化。
- 准备简历项目描述，但仅填写最终真实数字。

### 验收标准

- 新环境按 README 能启动或运行离线 Demo。
- 演示过程中能展示真实 Plan 变化、Agent 分工、Citation 和 Token/latency。
- 所有公开数字与版本化评测报告一致。
- 能回答 Planner、Replan、Memory、多 Agent、SFT、成本和安全方面的实现细节。

---

## 4. 推荐执行顺序与时间估算

以下估算以一名开发者借助 Codex、已有项目基础可运行、训练资源可获得为前提；真实模型评测和训练耗时不包含排队时间。

| 周期 | 工作包 | 预计投入 | 关键里程碑 |
|---|---|---:|---|
| 第 0 周 | K04.3、K04.4 收尾 | 2～4 天 | 稳定章节检索与真实 E2E |
| 第 1 周 | L00～L01 | 3～5 天 | Baseline、数据与报告契约冻结 |
| 第 2～3 周 | L02～L05 | 7～10 天 | 300 条固定集和真实基线报告 |
| 第 4～5 周 | M01～M05 | 8～12 天 | Planner V2 与策略型 Replan |
| 第 6 周 | M06 | 3～4 天 | Planner 对比与消融报告 |
| 第 7～8 周 | N01～N04 | 8～12 天 | 多角色综述协作闭环 |
| 第 9 周 | N05 | 3～4 天 | 多 Agent 消融报告 |
| 第 10 周 | O00～O01 | 4～6 天 | 训练资产与数据通过门禁 |
| 第 11～12 周 | O02～O04 | 7～12 天 | SFT Adapter 与置信度校准 |
| 第 13 周 | O05 | 3～5 天 | Cascade 晋级报告 |
| 第 14～15 周 | P01～P05 | 7～10 天 | 统一产品、Dashboard 和作品交付 |

若只有 2～3 周准备面试，执行最小路径：

1. 完成 L00～L05，拿到可信 Baseline。
2. 完成 M01～M04 和小规模 M06，证明动态 Replan。
3. 选择 O01～O02 的 Router 单任务训练，不承诺完整 Cascade。
4. 暂不实现完整多 Agent，只输出 N01 协议和一个可运行的 Critic/Verifier MVP。

---

## 5. 全局测试矩阵

| 层级 | 必测内容 | 是否允许 Fake | 完成门槛 |
|---|---|---|---|
| Contract | Plan/Observation/Blackboard/Dataset/Model Manifest | 是 | 100% 通过 |
| Unit | DAG、预算、completion、replan policy、calibration | 是 | 100% 通过 |
| Component | Planner、Coordinator、Critic、Verifier、Cascade | 可用 Fake 做故障注入 | 100% 通过 |
| Integration | PostgreSQL、Redis、Celery、MinIO、真实 Model Port | 关键链路否 | 100% 通过 |
| Trajectory | 合法计划、必需步骤、无效调用、循环 | 真实指标否 | 达到各阶段门槛 |
| Domain | QA、比较、综述、引用 | 真实指标否 | 达到各阶段门槛 |
| Security | 越权、Prompt Injection、参数注入、数据泄漏 | 可混合 | 严重违规为 0 |
| Performance | Token、P50/P95、GPU 时间、并发 | 否 | 达到各阶段门槛 |
| E2E | 原十场景 + 三个新增场景 | 最终验收否 | 全部通过 |

每个工作包的最小检查：

- 相关 pytest 单元/契约测试。
- Ruff。
- mypy 或项目既定类型检查。
- 涉及前端时运行 Vitest、TypeScript 和 production build。
- 涉及真实服务时运行对应 Docker integration。
- 涉及指标时运行固定 smoke 集；阶段结束运行完整真实评测集。

---

## 6. 核心数据表与 Trace 扩展建议

在具体实现前先审查现有 Port/Model，避免直接创建重复实体。建议概念上支持：

- `evaluation_runs`：数据集、系统配置、Commit、状态、硬件和时间。
- `evaluation_cases/results`：case 输入、输出、指标、Judge 和错误分类。
- `plans/plan_versions/plan_steps`：Plan 历史、Patch 和完成条件。
- `observations`：Tool/Agent/Model 结果摘要、data_ref、usage 和错误。
- `blackboard_entries/events`：共享证据实体及版本事件。
- `model_decisions`：1.7B 决策、置信度、升级原因和最终模型。
- `dataset_manifests/training_runs/model_manifests`：数据与 Adapter 血缘。

所有表必须：

- 强制 workspace/task 隔离。
- 使用 UTC、强类型 ID、版本字段和统一 ErrorCode。
- 不保存无必要的完整 Prompt、论文正文和隐藏推理。
- 支持删除级联、审计和派生索引失效。

---

## 7. 风险与应对

### 风险 1：300 条高质量评测集耗时过长

- 先做 100 条核心集验证 Runner，再扩到 300 条。
- 使用强模型生成候选，但 gold evidence 和高难 case 必须人工审核。
- 优先保证分层覆盖和标注质量，不以大量低质量模板样本充数。

### 风险 2：4B 模型结构化规划能力不足

- 压缩 Tool Schema、提供少量合法示例、使用受约束 JSON 输出。
- Validator + 一次 repair + 固定 Workflow fallback。
- 若 4B Planner 始终不达标，保留规则 Planner，将模型用于候选策略排序。

### 风险 3：多 Agent 增加成本但不提升质量

- 通过 N05 消融决定角色去留。
- 只对 L4/L5 复杂任务启用多 Agent。
- 共享 Paper Card/Evidence，避免重复读取和重复模型调用。

### 风险 4：1.7B SFT 数据不足或训练资源不稳定

- 首先训练 Router，一个任务形成完整闭环后再扩展。
- 未满足数据门槛时保持 blocked，不用小数据结果包装成果。
- 每次训练保存 checkpoint，支持恢复；先做 smoke training。

### 风险 5：优化测试集导致指标虚高

- 测试集冻结并限制访问。
- 阈值和 Prompt 只在 validation 集调整。
- 最终增加一次未见 challenge set 和人工抽检。

### 风险 6：当前工作树修改较多导致冲突

- 每个工作包开始先审计 status/diff。
- 小步提交或至少保存清晰 diff，不混入无关重构。
- K04 与新阶段重叠的章节检索文件必须先收尾再进入 L。

---

## 8. 阶段级最终验收门槛

| 方向 | 核心门槛 |
|---|---|
| 可信评测 | ≥300 条冻结真实测试任务；四类 Baseline；全指标含分母、版本和 95% CI |
| 动态规划 | L3～L5 成功率提升 ≥8 pp；无效 Tool 调用降低 ≥25%；Replan 恢复率提升 ≥15 pp；死循环 0 |
| 多智能体 | Claim Support 提升 ≥8 pp；冲突 Recall 提升 ≥20 pp；严重无依据事实降低 ≥50% |
| 专项训练 | Router Top-1 ≥92%；Schema/安全门禁通过；真实 Adapter 可加载、可回滚 |
| Model Cascade | 质量下降 ≤2 pp；4B 调用降低 ≥35%；单位成功 Token 降低 ≥25%；P95 降低 ≥20% |
| 综合系统 | 原十场景和新增三场景全部通过；越权为 0；所有对外指标可追溯 |

门槛是候选目标，不得在未运行基线前写入简历为既成事实。L05 完成后可根据基线难度调整绝对阈值，但必须保留变更理由和历史版本，不能为使失败实验通过而事后降低标准。

---

## 9. 工作包状态表

状态只允许：`pending`、`in_progress`、`blocked`、`completed`。

| 工作包 | 状态 | 前置 | 完成日期 | 说明/报告 |
|---|---|---|---|---|
| L00 | completed | K04.4 | 2026-07-21 | 四套 Baseline、环境快照、真实性分类、现状审计和框架边界 ADR 已冻结；定向 6 tests、Ruff、mypy 通过 |
| L01 | completed | L00 | 2026-07-21 | L1～L6 严格 Schema、来源授权、Gold Evidence、group split、文本/Embedding/来源去重门禁与数据卡；9 tests、Ruff、mypy 通过 |
| L02 | completed | L01 | 2026-07-21 | QASPER v0.3 + CSL 官方 test 构建 300-case（60/60/60/45/45/30）；240 EN/60 ZH、657 Gold spans、30 双标注 κ=1.0、三类 PDF 渲染与全 release 哈希复现；21 项 L00～L02 回归通过 |
| L03 | completed | L01 | 2026-07-21 | 33 项指标公式/分母/范围/异常处理，seeded 与 paired bootstrap 95% CI，规则→LLM→人工 Judge；50 人工参考 Gold 校准一致率/三次一致率均 100%，L00～L03 组合 29 tests 通过 |
| L04 | completed | L03 | 2026-07-21 | 可恢复并发 Runner、Trace 回放、八类错误与 JSON/Markdown/Dashboard；300-case unit_fake 链路验收 |
| L05 | completed | L02、L04 | 2026-07-21 | B0～B3 各 300 条 offline_real_model；1,800 调用，0 系统异常，报告与门槛冻结 |
| M01 | completed | L01 | 2026-07-21 | Plan/Step/Observation/Patch V2、V1 迁移、100 fixture 100% |
| M02 | completed | M01 | 2026-07-21 | 270-case：最终 Schema 100%、非法调用 0、Required Step Recall 96.84%（较 B1 +60.84pp，95% CI [55.82pp,65.25pp]）；模型直接通过 46.67%、fallback 53.33% |
| M03 | completed | M01 | 2026-07-21 | 50 个 Tool-success 不合格 fixture 漏判 0%、金标一致 100%；具体缺失项与质量信号写入 Observation |
| M04 | completed | M02、M03 | 2026-07-21 | 8 类失败/16 注入：策略 Replan 16/16、retry 基线 2/16（+87.5pp，unit fixture）；0 循环、最多 2 次，预算/权限/取消门禁通过 |
| M05 | completed | M04 | 2026-07-21 | CAS checkpoint、幂等崩溃恢复、DAG/副作用安全并行、原子 usage/预算/Trace、取消传播；20 次取消 P95<2s，42 项组合回归通过 |
| M06 | completed | L05、M05 | 2026-07-21 | NO-GO：540 candidate/1,497 真实 4B 调用，0 系统错误；L3～L5 +1.33pp（95% CI [-3.33pp,6.00pp]）、恢复 +0pp、Token/success +78.55%；仅矩阵完整与零循环/越权通过 |
| N01 | completed | M01 | 2026-07-21 | 六角色 Manifest/Schema、引用式消息、Tool 白名单与降级协议；14 项协议/旧子 Agent 回归通过 |
| N02 | completed | N01 | 2026-07-21 | Blackboard Domain/Port/Fake/SQL/迁移；append-only、乐观锁、删除失效、事件重建，20 项组合回归通过 |
| N03 | completed | N02、M05 | 2026-07-21 | 2/5/10 篇预算 DAG、深度 1、受控并发、80% 重复削减、超时/取消/部分失败；27 项组合回归通过 |
| N04 | completed | N03 | 2026-07-21 | 有界 Critic/Writer/Verifier 状态机；100-claim fixture 无依据率 0%、冲突 P/R 90%，33 项组合回归通过 |
| N05 | completed | L05、N04 | 2026-07-22 | NO-GO：六组×90 case，450 次真实 4B 调用；Claim Support +5.63pp、Task Success -1.11pp、Token +398.03%；默认 single Agent |
| O00 | pending | L01 |  |  |
| O01 | pending | O00、L02 |  |  |
| O02 | pending | O01 |  |  |
| O03 | pending | O02 |  | 可选，按 SFT 失败类型决定 |
| O04 | pending | O02 |  |  |
| O05 | pending | L05、O04 |  |  |
| P01 | completed | M06、N05；O05 用户明确跳过 | 2026-07-22 | 统一 Runtime、公开 SSE、旧数据迁移与隔离 Compose 8 服务验收通过；M/N No-Go 非默认，Cascade=`unavailable_o_skipped`，不声称模型升级效果 |
| P02 | completed | P01 | 2026-07-22 | 闭合 taxonomy 聚类、管理员人审、授权/匿名化门禁、staging、自动回归/安全 Gate Runner、版本报告与回滚；36 tests |
| P03 | completed | L04、P01 | 2026-07-22 | 独立管理员 Dashboard；L05 300 + N05 180 冻结行，六指标/筛选/95% CI/样本下钻，300 行 P95<2s；15 tests + TS/build |
| P04 | completed | P01、P03 | 2026-07-22 | B0–B3/生产安全策略总体+难度/任务族/语言切片；全可用指标 N/分母/95% CI；M/N NO-GO，SFT/Cascade unavailable；30/300 人工 Gold 审计 |
| P05 | completed | P04 | 2026-07-22 | README 首屏、可复现离线 Demo/3–5 分钟录制稿、ADR、Evaluation/Model/Dataset Card、三例复盘、面试/简历材料；全量 425 tests |

---

## 10. 每个工作包的 Codex 完成报告模板

```markdown
### 工作包：M04 策略型 Replanner

- 状态：completed / blocked
- 前置检查：
- 本次目标：
- 主要实现：
- Schema/Port/迁移变化：
- 数据与评测版本：
- 执行测试及结果：
- 真实模型实验及结果：
- 与 Baseline 的变化：
- 未解决风险：
- 文档同步：
- 建议下一工作包：
```

如果工作包因数据、模型、GPU、权限或外部依赖无法达到验收标准，必须保持 `blocked` 或 `in_progress`，并列出已经完成的安全替代工作和解除阻塞所需条件。

---

## 11. 最终简历证据模板

只有 P04 真实报告完成后才填写数值：

> 设计并落地结构化 DAG Plan-and-Execute Agent，依据工具 Observation、证据充分度与执行预算进行动态重规划；在 `[N]` 条冻结复杂论文任务上，相比 `[最佳基线]` 将任务完成率提升 `[X]` 个百分点、无效工具调用降低 `[Y]%`，死循环率为 0。

> 构建 Coordinator、Reader、Evidence、Critic、Writer、Verifier 多智能体协作链路，通过共享 Evidence Blackboard 和有界 Critic–Verifier 闭环，在多论文综述任务上将 Claim 引用支持率提升 `[X]` 个百分点、冲突识别 Recall 提升 `[Y]` 个百分点。

> 建立覆盖效果、轨迹、效率、成本与安全的 Agent 评测平台，沉淀 `[N]` 条分层任务和 Vanilla RAG/Workflow/ReAct/全 4B Baseline，支持 Trace 回放、错误聚类、95% 置信区间和版本化复现。

> 针对路由、工具调用和 Self-RAG 决策训练 1.7B QLoRA Adapter，并设计置信度感知的 1.7B/4B Model Cascade；在任务成功率下降不超过 `[X]` 个百分点的条件下，将 4B 调用比例降低 `[Y]%`、单位成功任务 Token 降低 `[Z]%`、P95 延迟降低 `[W]%`。

以上模板中的所有 `[N/X/Y/Z/W]` 必须来自版本化真实评测报告，不得使用预期值、Fake 测试值或未完成训练的结果。
