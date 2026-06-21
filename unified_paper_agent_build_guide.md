# 统一对话式论文 Agent：从零理解、搭建、训练与调优指南

> 这份文档是写给项目开发者本人的学习与执行手册。
>
> 目标不是做几个相互独立的“论文小功能”，而是搭建一个类似 ChatGPT/Codex 的统一对话式 Agent 系统：用户只看到一个对话窗口，在其中输入需求、上传文件和查看结果；系统在后台自动理解任务、制定计划、选择 Skill、调用 Tool、创建子 Agent、检查结果，并把最终答案返回到同一个会话。
>
> 领域目标：论文检索、阅读、问答、分析、对比、写作辅助、改写、语言润色、引用核验和格式检查。
>
> 模型约束：使用 1.5B/1.7B 或 4B 开源小模型，优先本地部署、量化、LoRA/QLoRA 和教师蒸馏。

---

# 一、先理解：你真正要搭建的是什么

## 1. 用户看到的产品

用户只需要面对一个聊天窗口：

```text
┌────────────────────────────────────────────────────┐
│ 对话记录                                           │
│                                                    │
│ 用户：请分析我上传的三篇论文，比较方法和实验结果。 │
│ Agent：正在解析文件……                              │
│ Agent：已建立比较维度，正在核验实验数据……          │
│ Agent：最终结果……                                  │
│                                                    │
├────────────────────────────────────────────────────┤
│ ＋上传文件      输入你的需求……              发送   │
└────────────────────────────────────────────────────┘
```

用户不需要知道系统调用了多少工具、Skill 或子 Agent，也不需要手工选择工作流。

界面可以展示必要的执行状态，例如：

- 正在解析 3 个文件。
- 正在检索相关章节。
- 正在比较实验结果。
- 正在核验引用。
- 任务已完成。

但不应把模型冗长的内部推理过程直接展示给用户。

## 2. 系统背后实际发生的事情

用户发送请求后，系统执行下面的闭环：

```text
接收消息和附件
      ↓
建立本轮任务上下文
      ↓
识别意图、约束和预期输出
      ↓
判断是直接回答还是进入 Agent 工作流
      ↓
选择 Skill，并生成可执行计划
      ↓
按步骤调用 Tool 或创建子 Agent
      ↓
持续记录中间结果和任务状态
      ↓
检查计划是否完成、证据是否充分
      ↓
失败时重新规划、重试或安全终止
      ↓
生成最终答案并附上文件/引用
      ↓
保存本轮有价值的记忆
```

这个循环就是系统的核心，可称为 **Agent Runtime** 或 **Agent Orchestrator**。

## 3. Agent、Tool、Skill、Workflow 和子 Agent 的区别

这些概念必须先分清，否则实现时很容易把所有东西都做成 Prompt。

### 3.1 Agent

Agent 是能够观察当前状态、决定下一步行动并使用工具完成任务的执行主体。

主 Agent 负责：

- 理解用户目标。
- 选择 Skill。
- 制定或修改计划。
- 决定下一步调用什么。
- 汇总和检查结果。
- 与用户保持统一对话。

### 3.2 Tool

Tool 是一个范围明确、输入输出固定的原子能力。它通常由代码完成，不应该自行制定复杂计划。

例如：

- `parse_pdf(file_id)`
- `search_chunks(query, file_ids, top_k)`
- `get_page_text(file_id, page)`
- `verify_citation(claim, evidence)`
- `lookup_doi(title)`
- `compare_numbers(value_a, value_b)`
- `save_artifact(name, content)`

Tool 的特点：

- 功能单一。
- 参数有严格 Schema。
- 可以独立测试。
- 执行结果可预测。
- 有清楚的错误返回。

### 3.3 Skill

Skill 是解决某一类任务的方法说明和可复用工作流。它会告诉 Agent：

- 什么时候使用这个 Skill。
- 任务应分成哪些步骤。
- 可以调用哪些 Tool。
- 输出应采用什么格式。
- 如何检查结果。
- 什么情况下应该停止或向用户追问。

例如 `paper_comparison` Skill：

```text
适用场景：
  用户要求比较两篇或多篇论文。

执行方法：
  1. 确认论文文件。
  2. 分别提取研究问题、方法、数据集、指标和结论。
  3. 将字段标准化。
  4. 生成比较矩阵。
  5. 核验数字和引用。
  6. 输出比较结果和局限。

允许工具：
  parse_pdf、search_chunks、extract_paper_card、
  verify_claim、render_comparison_table
```

Skill 不一定需要训练模型。第一版可以是 Markdown/YAML 文件加程序约束。

### 3.4 Workflow

Workflow 是一次具体任务的实际执行计划。

Skill 是可复用的“做事方法”，Workflow 是 Agent 根据本次用户请求生成的“执行实例”。

例如：

```json
{
  "goal": "比较用户上传的三篇论文",
  "steps": [
    {"id": 1, "action": "parse_files", "status": "completed"},
    {"id": 2, "action": "extract_paper_cards", "status": "running"},
    {"id": 3, "action": "compare_methods", "status": "pending"},
    {"id": 4, "action": "verify_results", "status": "pending"},
    {"id": 5, "action": "compose_answer", "status": "pending"}
  ]
}
```

### 3.5 子 Agent

子 Agent 是主 Agent 为某个相对独立的子任务创建的临时执行者。

例如比较 10 篇论文时：

- 主 Agent 创建 10 个“论文分析子 Agent”。
- 每个子 Agent 只读取一篇论文。
- 子 Agent 输出统一格式的 Paper Card。
- 主 Agent 收集结果并进行综合比较。

子 Agent 不是必须拥有不同模型，也不一定是真正的独立服务。第一版可以只是：

- 独立的任务状态。
- 独立的上下文。
- 限定的 Tool 集合。
- 相同的小模型。
- 并发执行的后台任务。

不要把多个模型互相聊天误认为“多 Agent”。真正有价值的是任务隔离、并行执行、权限约束和结果汇总。

## 4. 论文能力在系统中的位置

“论文助手”不是整个底层系统，而是运行在通用 Agent Runtime 上的一组领域 Skill：

```text
统一对话界面
      ↓
通用 Agent Runtime
      ↓
Skill Registry
      ├── 论文问答 Skill
      ├── 论文分析 Skill
      ├── 多论文比较 Skill
      ├── 文献综述 Skill
      ├── 论文大纲 Skill
      ├── 学术润色 Skill
      ├── 引用核验 Skill
      └── 格式检查 Skill
      ↓
论文解析、检索、文件、引用等 Tools
```

这样的架构将来还可以增加代码分析、数据分析等 Skill，而不需要重写聊天界面和 Agent Runtime。

---

# 二、系统完整架构

## 1. 总体结构

```text
┌─────────────────────────────────────────────────────────┐
│                 单一 Web 对话窗口                        │
│ 消息、附件、任务状态、引用、生成文件、确认与取消         │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                Conversation Service                     │
│ 会话、消息、附件、流式输出、用户确认、任务恢复           │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                 Agent Orchestrator                       │
│ 意图识别 → Skill 选择 → 规划 → 执行 → 校验 → 重规划     │
│ 预算控制、权限控制、终止判断、上下文构建                 │
└───────┬──────────────────┬───────────────────┬──────────┘
        │                  │                   │
┌───────▼──────┐  ┌────────▼────────┐  ┌──────▼──────────┐
│ Skill Registry│  │ Sub-agent Manager│  │ Memory Manager │
│ Skill 检索    │  │ 创建、并发、取消 │  │ 会话/任务/长期  │
└───────┬──────┘  └────────┬────────┘  └──────┬──────────┘
        │                  │                   │
┌───────▼──────────────────▼───────────────────▼──────────┐
│                       Tool Layer                         │
│ 文件、解析、OCR、检索、重排、引用、元数据、写作、导出   │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                Model & Retrieval Layer                   │
│ 1.5B 路由/抽取、4B 规划/生成、Embedding、Reranker、NLI   │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                       Data Layer                         │
│ PostgreSQL、对象存储、向量库、缓存、任务队列、Trace     │
└─────────────────────────────────────────────────────────┘
```

## 2. 核心服务

### 2.1 Conversation Service

负责：

- 创建和读取会话。
- 保存用户与 Agent 消息。
- 关联上传文件。
- 通过 SSE 或 WebSocket 流式返回状态和答案。
- 支持取消任务和继续任务。
- 管理需要用户确认的操作。

### 2.2 Agent Orchestrator

这是项目最重要的部分，建议先实现为明确的状态机，而不是完全自由的模型循环。

基本节点：

```text
RECEIVE
  → UNDERSTAND
  → SELECT_SKILL
  → PLAN
  → EXECUTE
  → OBSERVE
  → VERIFY
  ├→ REPLAN
  ├→ ASK_USER
  ├→ FAIL
  └→ RESPOND
```

### 2.3 Skill Registry

保存所有 Skill 的：

- 名称和版本。
- 适用场景。
- 输入要求。
- 允许使用的 Tool。
- 标准步骤。
- 输出 Schema。
- 验收规则。
- 示例。

第一版用本地 Markdown/YAML 文件即可，后续再增加向量检索和动态加载。

### 2.4 Tool Registry

每个 Tool 至少记录：

```json
{
  "name": "search_paper_chunks",
  "description": "从指定论文中检索能够回答问题的证据",
  "input_schema": {},
  "output_schema": {},
  "permission": "read",
  "timeout_seconds": 10,
  "retryable": true
}
```

Tool Registry 负责：

- 向模型提供可用工具描述。
- 验证调用参数。
- 检查权限。
- 执行 Tool。
- 统一处理超时与异常。
- 记录调用 Trace。

### 2.5 Sub-agent Manager

负责：

- 创建子任务。
- 为子 Agent 分配上下文、Skill 和 Tool 白名单。
- 设置最大步骤、Token、时间和并发。
- 收集中间结果。
- 取消失控任务。
- 把结果压缩后交还主 Agent。

### 2.6 Memory Manager

至少区分四类信息：

1. 对话历史：用户和 Agent 的消息。
2. 任务状态：计划、步骤和中间结果。
3. 工作区记忆：用户上传的论文和生成文件。
4. 长期偏好：用户语言、写作风格等经过允许保存的信息。

不要把全部历史消息原样塞给模型。应构建“本轮最相关上下文”。

### 2.7 File Workspace

每个用户或会话拥有隔离的工作区：

```text
workspace/
├── uploads/
├── parsed/
├── indexes/
├── artifacts/
└── temp/
```

系统内部使用 `file_id`，而不是让模型直接操作任意磁盘路径。

---

# 三、小模型如何支撑这个系统

## 1. 推荐模型职责

如果你拥有两个模型：

| 模型 | 主要职责 |
|---|---|
| 1.5B/1.7B | 意图分类、Skill 初选、查询改写、字段抽取、简单工具参数、格式检查 |
| 4B | 复杂规划、证据问答、多步工具调用、结果综合、论文写作和润色 |

如果只能运行一个模型，选择 4B。

当前可优先用 Qwen3-1.7B 和 Qwen3-4B 建立基线，但系统代码必须允许替换模型。

## 2. 小模型系统设计原则

小模型不擅长：

- 在几十个工具中稳定选择。
- 一次制定很长的可靠计划。
- 记住整篇论文。
- 自行核验数字和引用。
- 在长循环中一直保持目标。

因此需要：

1. 每次只提供与当前 Skill 有关的 3～8 个 Tool。
2. 计划限制为 3～8 个步骤。
3. 每执行一步都更新结构化状态。
4. 使用 JSON Schema 或 Grammar 约束模型输出。
5. 把检索、计算、文件和引用核验交给代码。
6. 把长任务拆成多个短上下文任务。
7. 限制重试次数，避免无限循环。
8. 使用程序判断终止条件，不完全依赖模型。

## 3. 上下文预算

即使模型支持较长上下文，也不要把所有内容都交给它。

建议初始预算：

| 场景 | 输入预算 |
|---|---:|
| 意图识别与 Skill 选择 | 1K～2K tokens |
| 规划 | 2K～4K tokens |
| 工具调用决策 | 2K～4K tokens |
| 单论文问答 | 4K～8K tokens |
| 子 Agent 单篇论文分析 | 6K～12K tokens |
| 最终多论文综合 | 6K～12K tokens |

长论文必须通过 RAG、结构化抽取或分层摘要处理。

## 4. 本地推理

原型阶段可选：

- Transformers：最容易调试。
- llama.cpp/Ollama：适合量化模型和本地演示。
- vLLM/SGLang：适合 GPU 服务化和并发。

粗略的仅权重显存：

| 规模 | FP16/BF16 | 8-bit | 4-bit |
|---|---:|---:|---:|
| 1.5B/1.7B | 约 3～4 GB | 约 2 GB | 约 1～1.5 GB |
| 4B | 约 8～10 GB | 约 5 GB | 约 2.5～4 GB |

实际还需为 KV Cache、运行时和并发预留显存。

---

# 四、你应该按什么顺序完成

下面的阶段顺序非常重要。每一个阶段都能运行和验收后，再进入下一阶段。

---

## 阶段 0：建立项目认知和最小目标

### 你要理解什么

第一版不是完整复制 ChatGPT/Codex，而是实现它们最核心的交互模式：

- 一个对话入口。
- 能接收文件。
- 能理解任务。
- 能自动执行多步工作流。
- 能调用工具。
- 能返回结果和引用。
- 执行过程可观察、可终止、可复现。

### 第一版只支持三个任务

1. 上传论文后问答。
2. 分析一篇论文。
3. 比较多篇论文。

先不要加入联网搜索、长期记忆、语音、图片生成或复杂权限操作。

### 需要准备

- 20 篇公开许可论文。
- 50 个带原文证据的问答。
- 10 个论文分析任务。
- 5 个多论文比较任务。
- 一台开发机器。
- Git 仓库和 Python 环境。

### 验收标准

- 你能清楚解释 Agent、Tool、Skill、Workflow 和子 Agent 的区别。
- 三个首版任务都有明确输入、输出和成功标准。
- 建立项目 README 和任务清单。

---

## 阶段 1：先做一个只有聊天功能的系统外壳

### 为什么先做

所有能力最终都要通过统一会话运行。先建立会话和任务基础，后续不会变成互不相连的脚本。

### 具体实现

前端：

- 单一消息列表。
- 文本输入框。
- 多文件上传。
- 发送、停止生成和重新执行。
- 消息中的引用与文件链接。
- 任务状态展示。

后端 API：

- `POST /conversations`
- `GET /conversations/{id}`
- `POST /conversations/{id}/messages`
- `POST /files`
- `GET /tasks/{id}`
- `POST /tasks/{id}/cancel`
- `GET /events/{task_id}`，用于流式事件。

数据库最小表：

- users
- conversations
- messages
- files
- tasks
- task_events
- artifacts

### 事件格式

```json
{
  "task_id": "task_001",
  "type": "tool_started",
  "title": "正在解析论文",
  "data": {"tool": "parse_pdf", "file_id": "file_001"},
  "timestamp": "..."
}
```

### 注意事项

- 消息发送后应立即创建后台任务，避免 HTTP 请求一直阻塞。
- 前端展示的是可理解的进度，不展示隐藏推理。
- 文件必须关联用户和会话。
- 支持用户取消任务。

### 验收标准

- 用户可创建会话并上传文件。
- 消息和附件刷新页面后仍然存在。
- 后台任务状态能实时显示。
- 任务可以被取消。
- 不同会话的文件不会混用。

---

## 阶段 2：搭建最小 Agent Runtime

### 目标

先让 Agent 在没有论文能力的情况下完成一个简单的“理解—计划—调用工具—回答”闭环。

### 第一个 Tool

可先实现三个简单 Tool：

- `list_files`
- `read_text_file`
- `save_text_artifact`

### Agent 状态

```json
{
  "task_id": "task_001",
  "conversation_id": "conv_001",
  "goal": "总结上传的文本文件",
  "status": "running",
  "selected_skill": null,
  "plan": [],
  "current_step": 0,
  "observations": [],
  "artifacts": [],
  "limits": {
    "max_steps": 8,
    "max_replans": 2,
    "deadline_seconds": 120
  }
}
```

### 最小执行循环

```python
while not finished:
    context = build_context(state)
    decision = model_decide(context, allowed_tools)
    decision = validate_schema(decision)

    if decision.type == "tool_call":
        result = execute_tool(decision)
        state.observations.append(result)
    elif decision.type == "final":
        finished = verify_completion(decision, state)
    elif decision.type == "ask_user":
        pause_task()

    enforce_limits(state)
```

### 必须由代码控制

- 最大步骤数。
- 最大重规划次数。
- Tool 白名单。
- 参数 Schema。
- 超时。
- 文件权限。
- 任务取消。
- 错误处理。

### 验收数据

准备 30 条简单任务，例如：

- 列出上传文件。
- 读取某个文件并总结。
- 从两个文件中提取标题。
- 将结果保存为 Markdown。
- 请求不存在的文件。

### 验收标准

- 90% 以上简单任务能正确完成。
- Tool 参数合法率达到 98%。
- Agent 不会无限循环。
- Tool 失败后能重试或返回明确错误。
- 每一步均有 Trace。

---

## 阶段 3：建立 Tool 系统

### 目标

把所有外部能力做成安全、可测试的 Tool，而不是让模型直接操作数据库和文件系统。

### Tool 接口

每个 Tool 实现：

- `name`
- `description`
- `input_schema`
- `output_schema`
- `permission`
- `execute`
- `timeout`
- `retry_policy`

统一返回：

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "metadata": {
    "duration_ms": 120,
    "cached": false
  }
}
```

### 第一批论文 Tools

1. `parse_document`
2. `get_document_outline`
3. `search_document`
4. `get_document_section`
5. `extract_paper_card`
6. `verify_claim`
7. `lookup_paper_metadata`
8. `compare_paper_cards`
9. `rewrite_academic_text`
10. `save_artifact`

### Tool 测试

每个 Tool 都要有：

- 正常输入。
- 空输入。
- 错误类型。
- 文件不存在。
- 权限不足。
- 超时。
- 超大结果。

### 验收标准

- 所有 Tool 都能脱离 Agent 独立测试。
- 输入输出全部经过 Schema 验证。
- 未授权文件访问被阻止。
- Tool 错误不会使整个服务崩溃。
- Tool 调用日志可通过 task_id 查询。

---

## 阶段 4：完成论文解析和 RAG

### 目标

让 Tool 层能够可靠读取论文，并提供可追溯证据。

### 数据准备

- 20 篇普通 PDF。
- 10 篇双栏 PDF。
- 5 篇包含复杂表格的 PDF。
- 5 篇扫描 PDF。
- 200 条带页码和证据的问答。

### 解析流程

```text
文件检测
 → 文本型/扫描型判断
 → PDF 解析或 OCR
 → 阅读顺序恢复
 → 标题与章节识别
 → 页眉页脚清理
 → 表格、图片标题和引用提取
 → 页码与坐标映射
 → 结构化 JSON
```

### RAG 流程

```text
问题
 → 查询改写
 → 向量检索
 → BM25 检索
 → 合并去重
 → Reranker
 → 选择证据
 → 4B 基于证据生成
 → Claim-Evidence 核验
```

### 必备数据字段

每个文本块保存：

- file_id
- paper_id
- chunk_id
- section_path
- page_start/page_end
- text
- bbox，可选
- parent_chunk_id
- previous/next_chunk_id

### 验收标准

- 普通 PDF 有效字符提取率 ≥ 98%。
- 章节标题识别 F1 ≥ 90%。
- 证据到页码映射准确率 ≥ 98%。
- Recall@10 ≥ 90%。
- 单论文问答正确率 ≥ 80%。
- 引用支持率 ≥ 90%。
- 不可回答问题拒答率 ≥ 85%。

---

## 阶段 5：建立 Skill 系统

### 目标

让 Agent 不需要把所有任务方法都记在一个巨大 System Prompt 中，而是按需加载相关 Skill。

### Skill 文件建议

```text
skills/
├── paper_qa/
│   ├── SKILL.md
│   └── examples.json
├── paper_analysis/
│   ├── SKILL.md
│   └── schema.json
├── paper_comparison/
│   ├── SKILL.md
│   └── schema.json
└── academic_rewrite/
    ├── SKILL.md
    └── schema.json
```

### Skill 文档模板

```markdown
# Skill 名称

## 适用场景

## 不适用场景

## 所需输入

## 允许使用的 Tools

## 标准执行流程

## 输出格式

## 质量检查

## 停止与追问条件

## 正确示例

## 错误示例
```

### Skill 选择

第一版采用两级选择：

1. 1.5B 对任务进行粗分类。
2. 从对应类别中向 4B 提供少量候选 Skill，由其最终选择。

不要一次把全部 Skill 正文塞给模型。先根据名称、描述和标签选出 Top-K，再加载正文。

### 初始 Skill

- `paper_qa`
- `paper_summary`
- `paper_analysis`
- `paper_comparison`
- `literature_review`
- `outline_generation`
- `academic_rewrite`
- `citation_check`

### 验收数据

每个 Skill 准备：

- 20 条正例。
- 10 条相似但不适用的负例。
- 5 条信息不足、需要追问的任务。

### 验收标准

- Skill Top-1 选择准确率 ≥ 90%。
- Skill Top-3 召回率 ≥ 98%。
- 每个 Skill 只暴露必要 Tool。
- 更换 Skill 版本不需要修改 Agent 主循环。
- Skill 执行结果符合各自输出 Schema。

---

## 阶段 6：让 Agent 自动规划和重规划

### 目标

让系统面对复合需求时能够自动形成工作流。

示例请求：

> 阅读这三篇论文，比较它们的方法和实验结果，然后生成一份中文综述草稿，并把比较表保存成 Markdown。

可能计划：

```json
{
  "goal": "完成三篇论文的比较和综述草稿",
  "steps": [
    {
      "id": "s1",
      "description": "解析三个文件",
      "executor": "tool",
      "depends_on": []
    },
    {
      "id": "s2",
      "description": "分别提取论文卡片",
      "executor": "subagents",
      "depends_on": ["s1"]
    },
    {
      "id": "s3",
      "description": "比较方法和实验结果",
      "executor": "main_agent",
      "depends_on": ["s2"]
    },
    {
      "id": "s4",
      "description": "核验数字与引用",
      "executor": "tools",
      "depends_on": ["s3"]
    },
    {
      "id": "s5",
      "description": "撰写综述并保存比较表",
      "executor": "main_agent",
      "depends_on": ["s4"]
    }
  ]
}
```

### 规划器必须输出

- 任务目标。
- 所需 Skill。
- 步骤。
- 步骤依赖。
- 每步执行者。
- 预期输出。
- 完成条件。
- 失败处理。

### 重规划触发条件

- 文件解析失败。
- 检索证据不足。
- Tool 返回不可恢复错误。
- 计划依赖不存在。
- 核验未通过。
- 超出预算。

### 注意事项

- 简单问答不要规划五六步。
- 复杂计划也尽量控制在 8 步以内。
- 计划必须可执行，不能出现不存在的 Tool。
- 重规划最多 1～2 次。
- 风险操作需要用户确认。

### 验收标准

- 简单任务不会被过度规划。
- 复杂任务的计划可执行率 ≥ 90%。
- 步骤依赖正确率 ≥ 95%。
- 不存在调用未注册 Tool 的情况。
- 失败后正确恢复或安全停止的比例 ≥ 90%。

---

## 阶段 7：加入子 Agent

### 什么时候才需要

满足任一条件再创建子 Agent：

- 多个子任务可以并行。
- 每个子任务需要独立上下文。
- 主上下文会因材料过多而溢出。
- 某个子任务需要不同 Tool 权限。

不应为简单问答创建子 Agent。

### 第一种子 Agent

只实现 `paper_reader_agent`：

输入：

- 单个 file_id。
- 分析目标。
- 指定 Paper Card Schema。
- Tool 白名单。
- 最大步骤和时间。

输出：

- 结构化 Paper Card。
- 每个字段的引用。
- 未找到的信息。
- 执行状态。

### 主 Agent 如何使用

1. 将多篇论文拆成独立任务。
2. 并发创建多个 `paper_reader_agent`。
3. 等待结果或处理部分失败。
4. 校验每个结果 Schema。
5. 压缩为统一比较输入。
6. 主 Agent 完成跨论文综合。

### 子 Agent 约束

- 不直接与用户交流。
- 不读取其他子 Agent 的上下文。
- 不拥有超过任务所需的 Tool。
- 不无限创建新的子 Agent。
- 最多一层或两层委派。
- 每个子 Agent 都有独立预算。

### 验收标准

- 多论文任务能正确拆分和汇总。
- 子 Agent 之间不存在文件串用。
- 单个子任务失败不会导致全部结果丢失。
- 并行执行相对串行执行有明确耗时改善。
- 汇总结果中的每个结论能追踪到具体子 Agent 和原文证据。

---

## 阶段 8：完善记忆、文件和上下文管理

### 目标

让长对话仍然能保持任务连续性，同时避免上下文无限增长。

### 上下文构建顺序

每次模型调用只组装：

1. 固定系统规则。
2. 当前 Skill。
3. 当前允许的 Tool。
4. 当前任务目标和计划。
5. 最近相关消息。
6. 必要的工作区信息。
7. 当前步骤的观察结果。

### 记忆写入规则

可以保存：

- 用户明确表达的稳定偏好。
- 当前研究主题。
- 用户确认过的术语和格式。
- 已完成任务产生的 Artifact。

不应自动长期保存：

- 未经确认的敏感信息。
- 整篇论文全文副本。
- 模型的隐藏推理。
- 临时错误结果。

### 验收标准

- 20 轮对话后仍能正确识别当前任务。
- 不相关历史不会显著干扰新任务。
- 用户可以查看和删除文件与长期记忆。
- 同一文件不重复解析和 Embedding。
- 上下文 Token 消耗有可观察指标。

---

## 阶段 9：建立评测、Trace 和安全机制

### 目标

能够回答三个问题：

1. Agent 为什么这样做？
2. 失败发生在哪一步？
3. 新版本是否真的更好？

### 每次任务记录

- 用户目标。
- 选中的 Skill。
- 计划版本。
- 每个步骤。
- Tool 调用和结果摘要。
- 子 Agent 输入输出。
- 模型及 Prompt 版本。
- Token、耗时和显存。
- 核验结果。
- 最终状态。

### 评测层级

组件指标：

- Skill 选择准确率。
- Tool 选择准确率。
- Tool 参数合法率。
- 检索 Recall/MRR/nDCG。
- PDF 解析准确率。

Agent 指标：

- 计划可执行率。
- 任务完成率。
- 平均步骤数。
- 重规划率。
- 死循环率。
- 子任务成功率。

论文质量指标：

- 问答正确率。
- 引用支持率。
- 不可回答拒答率。
- 多论文比较准确率。
- 润色语义保持率。

工程指标：

- P50/P95 延迟。
- 单任务 Token。
- 单任务成本或 GPU 时间。
- 峰值显存。
- Tool 失败率。

### 安全

必须防止：

- 论文中的 Prompt Injection。
- 模型访问任意磁盘路径。
- 跨用户文件读取。
- Tool 参数注入。
- 无限制子 Agent 创建。
- 伪造引用和 DOI。
- 学术作弊与实验数据伪造。

论文内容始终被视为“不可信数据”，不能覆盖系统规则。

### 验收标准

- 所有任务都有完整 Trace。
- 跨用户文件访问测试通过率 100%。
- Agent 死循环率为 0。
- Prompt Injection 阻断率 ≥ 95%。
- 新旧版本能够在固定测试集上自动对比。

---

## 阶段 10：训练和调优 1.5B/4B 模型

不要在 Agent Runtime、Tool、Skill 和评测还没完成时开始训练。否则你不知道训练到底解决了什么问题。

### 10.1 先建立基础模型 Baseline

分别评测：

- 1.5B/1.7B 的路由和抽取能力。
- 4B 的规划和工具调用能力。
- 4B 的证据问答和写作能力。

保存全部失败案例。

### 10.2 首先训练 1.5B/1.7B

适合训练：

- 意图分类。
- Skill 选择。
- 查询改写。
- 结构化抽取。
- Tool 选择。
- Tool 参数生成。

建议数据规模：

| 数据 | 起步规模 | 较完整规模 |
|---|---:|---:|
| 意图与 Skill 选择 | 1,000 | 5,000～10,000 |
| Tool 调用 | 2,000 | 10,000～30,000 |
| 查询改写 | 1,000 | 5,000～10,000 |
| 结构化抽取 | 2,000 | 10,000～30,000 |

### 10.3 再训练 4B

适合训练：

- 多步计划。
- 受约束工具调用。
- 基于证据回答。
- 多论文综合。
- 学术文本改写。
- 结果自检。

建议数据规模：

| 数据 | 起步规模 | 较完整规模 |
|---|---:|---:|
| 计划轨迹 | 1,000 | 5,000～10,000 |
| 多步工具轨迹 | 2,000 | 10,000～30,000 |
| 证据问答 | 3,000 | 20,000～50,000 |
| 多论文综合 | 1,000 | 5,000～10,000 |
| 学术改写 | 2,000 | 10,000～30,000 |

### 10.4 教师蒸馏

可使用更强模型离线生成候选训练数据，但必须：

1. 给教师模型相同的 Tool 和 Skill 定义。
2. 保存计划、工具调用和最终答案。
3. 用程序检查 JSON、Tool 名称、参数、数字和引用。
4. 过滤失败轨迹。
5. 人工抽检并修正高价值样本。
6. 加入真实小模型失败案例。

不要直接把教师模型的所有输出当作正确答案。

### 10.5 QLoRA

建议从 QLoRA 开始：

- 4-bit 加载基座。
- LoRA rank 测试 8、16、32。
- 训练 1～3 epoch。
- 使用验证集早停。
- 按长度分桶。
- 使用梯度累积。
- 保存 Adapter 和训练配置。

参数通过实验确定，不要只报告 Training Loss。

### 10.6 Reranker 训练

Reranker 往往比直接微调生成模型更快改善论文问答。

数据包括：

- query。
- 正确证据块。
- BM25 或向量检索返回的困难负例。

验收：

- MRR@10 提升 ≥ 8%。
- nDCG@10 提升 ≥ 8%。
- 最终引用准确率有实际提升。

### 10.7 训练验收

- 1.5B Skill 选择 Top-1 ≥ 90%。
- 1.5B/4B Tool 参数合法率 ≥ 99%。
- 4B 计划可执行率 ≥ 90%。
- 4B 单论文问答正确率 ≥ 80%。
- 引用支持率 ≥ 90%。
- 微调后目标任务综合指标提升 ≥ 5%。
- 安全和通用能力没有明显退化。

---

# 五、推荐 16 周执行计划

| 周 | 目标 | 必须交付 |
|---|---|---|
| 1 | 理解架构、定义 MVP | 需求、架构图、测试任务 |
| 2 | 统一聊天界面和会话 | 可上传文件的聊天 Demo |
| 3 | 后台任务和事件流 | 流式状态、取消和恢复 |
| 4 | 最小 Agent Runtime | 计划、工具调用、终止闭环 |
| 5 | Tool Registry | 文件 Tools 和自动测试 |
| 6 | PDF 解析 | 结构化论文及页码映射 |
| 7 | RAG | 向量检索、BM25、引用问答 |
| 8 | Skill Registry | 论文问答、分析、比较 Skill |
| 9 | 自动规划和重规划 | 复合任务工作流 |
| 10 | 子 Agent | 多论文并行分析 |
| 11 | 写作和润色 Skill | 大纲、综述、改写、引用保护 |
| 12 | Memory 与 Context | 长对话和工作区管理 |
| 13 | Trace 与自动评测 | 评测脚本和可观察链路 |
| 14 | 安全与部署 | 权限、注入测试、容器部署 |
| 15 | QLoRA/Reranker 训练 | 训练报告和前后对比 |
| 16 | 消融、复盘和简历 | Demo、视频、实验报告、简历 |

如果时间有限，前 10 周已经可以形成有说服力的 Agent 项目。训练是后续增强，不应阻塞系统闭环。

---

# 六、推荐项目结构

```text
paper-agent/
├── apps/
│   ├── web/                    # 单一对话界面
│   ├── api/                    # 会话、文件和任务 API
│   └── worker/                 # 后台任务
├── agent_runtime/
│   ├── orchestrator.py
│   ├── state.py
│   ├── planner.py
│   ├── executor.py
│   ├── verifier.py
│   ├── context_builder.py
│   └── limits.py
├── skills/
│   ├── registry.py
│   ├── paper_qa/
│   ├── paper_analysis/
│   ├── paper_comparison/
│   └── academic_rewrite/
├── tools/
│   ├── registry.py
│   ├── files/
│   ├── parsing/
│   ├── retrieval/
│   ├── citation/
│   └── artifacts/
├── subagents/
│   ├── manager.py
│   └── paper_reader.py
├── models/
│   ├── router.py
│   ├── generator.py
│   ├── embedding.py
│   └── reranker.py
├── memory/
├── storage/
├── evaluation/
├── training/
│   ├── router_sft/
│   ├── agent_sft/
│   └── reranker/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── security/
├── configs/
├── docs/
└── docker-compose.yml
```

---

# 七、第一个真正可运行的 MVP

MVP 完成后，用户应该能够：

1. 打开一个聊天窗口。
2. 上传两篇 PDF。
3. 输入：“比较这两篇论文的方法和实验结果，结论要附页码。”
4. 系统自动：
   - 识别为论文比较任务。
   - 加载 `paper_comparison` Skill。
   - 生成计划。
   - 解析论文。
   - 创建两个论文阅读子任务。
   - 检索并提取证据。
   - 比较方法和结果。
   - 核验关键数字与引用。
   - 返回比较表和总结。
5. 用户只在同一个会话中看到进度与最终结果。

MVP 的最终验收：

- 端到端任务成功率 ≥ 80%。
- Skill 选择准确率 ≥ 90%。
- Tool 参数合法率 ≥ 98%。
- 引用支持率 ≥ 90%。
- 不存在无限循环。
- 不存在跨用户文件访问。
- 任一失败都能通过 Trace 定位。

---

# 八、你暂时不要做的事情

在 MVP 完成前，不要优先投入：

- 让 1.5B 模型自由规划几十步。
- 建立十几个不同人格的 Agent。
- 无限递归创建子 Agent。
- 全参数训练 4B 模型。
- 自研向量数据库。
- 把整篇论文直接放进上下文。
- 同时支持所有论文格式。
- 在没有固定测试集时反复改 Prompt。
- 为了“像 Codex”而加入与论文任务无关的工具。

先把一条主链路做得可靠：

```text
对话输入 → Skill 选择 → 计划 → Tool/子任务 → 核验 → 最终回答
```

---

# 九、最终简历应如何表达

项目完成后，可以根据真实指标写成：

> **统一对话式论文 Agent 系统｜个人项目**
>
> - 从零设计并实现统一对话式 Agent Runtime，用户仅通过单一聊天窗口上传文件和描述目标，后台自动完成 Skill 选择、任务规划、工具调用、子 Agent 并发执行、结果核验及失败重规划。
> - 基于 1.7B/4B 开源小模型构建分层推理架构，通过结构化状态机、Tool 白名单、JSON Schema 和执行预算提升小模型多步任务稳定性，实现 **X%** 的端到端任务完成率。
> - 构建论文解析、混合 RAG、Reranker 和 Claim-Evidence 核验流水线，在 **N** 篇论文及 **M** 条评测样本上将 Recall@10 从 **A%** 提升至 **B%**，引用支持率达到 **C%**。
> - 设计可插拔 Skill Registry 与受限子 Agent 机制，支持论文问答、多文档比较、综述辅助和学术润色，并实现会话级文件隔离、Prompt Injection 防护与全链路 Trace。
> - 基于真实失败轨迹和教师蒸馏数据对小模型进行 QLoRA/SFT，并训练领域 Reranker，使工具调用准确率提升 **X%**、nDCG@10 提升 **Y%**。

其中所有数字必须由你的真实实验填写。

---

# 十、从今天开始的第一批任务

请先只完成以下内容：

1. 创建项目仓库和目录。
2. 写清楚 MVP 的三个任务。
3. 准备 20 篇论文和 50 条问答。
4. 创建一个只有消息、上传和任务状态的聊天界面。
5. 建立会话、消息、文件、任务和事件五类数据。
6. 实现 `list_files`、`read_text_file`、`save_text_artifact` 三个 Tool。
7. 用 4B 模型完成第一次“计划—调用工具—回答”闭环。
8. 为该闭环写 30 条自动验收任务。

只有这八项通过后，再开始 PDF 解析和论文 RAG。

你最终要证明的不是“小模型什么都会”，而是：你设计了一套可靠的 Agent Runtime，让资源有限的小模型借助 Skill、Tool、子 Agent、检索、状态管理和验证机制完成原本无法独立完成的复杂任务。
