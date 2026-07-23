# ADR-0010: Agent 框架边界与冻结 Baseline

**状态**: 已接受  
**日期**: 2026-07-21

## 背景

后续工作需要深化 Planner、Replanner、多 Agent 和评测，同时目标岗位提及 LangChain、
AutoGen、ReAct 和 Plan-and-Execute。直接替换现有 Runtime 会破坏已经验证的状态真值、
权限、预算、恢复和 Trace 语义，也会使前后实验不可比较。

## 决策

保留自研显式状态机作为唯一 Agent Runtime 真值，通用框架只能通过现有 Port/Adapter
边界接入，不得拥有独立任务状态或绕过 Tool Registry。

能力映射如下：

| 通用概念/框架 | 本项目对应能力 | 边界 |
|---|---|---|
| ReAct | `ReActSelfRAGController` + Executor Observation | 只保存结构化决策摘要，不保存隐藏 CoT |
| Plan-and-Execute | `Planner`、`ExecutionPlan`、`Executor`、`Verifier` | Plan/预算/重规划上限由本项目 Schema 控制 |
| LangChain Tools | Tool Registry、Pydantic Tool Runtime、Skill 白名单 | 可适配 Tool，不接管权限与 Workspace |
| LangGraph | 显式 StateMachine 和持久 Task 状态 | 可作为节点实现实验，不成为第二状态真值 |
| AutoGen | SubAgentManager、父子 Task、Celery Group | 可适配角色消息，不允许递归或直接用户输出 |

同时冻结四套 Baseline：Vanilla RAG、Fixed Workflow、Current Bounded ReAct、Full 4B。
所有候选算法必须在相同数据、检索参数、预算和报告 Schema 下与至少一套 Baseline 比较。

## 替代方案

1. 全面迁移 LangGraph：生态成熟，但会同时改变状态、恢复和评测，无法归因算法收益。
2. 全面迁移 AutoGen：便于角色对话，但默认协作语义不满足深度、权限和预算不变量。
3. 不设 Baseline：开发更快，但无法回答质量、成本和延迟提升来自哪里。

## 后果

### 优点

- 保留现有架构和安全边界。
- 算法变更可独立消融和回滚。
- 面试中可解释框架原理，而不是只展示框架调用。
- 通用框架仍可在 Adapter 层用于对照实验。

### 缺点

- 需要自行维护 Plan/Observation/Blackboard Schema。
- 与第三方生态集成需要额外适配代码。
- Baseline 参数冻结后，修改必须创建新版本而非原地覆盖。

## 验收标准

- 四套 Baseline 均通过同一 Loader 和 Evaluation Runner。
- 报告记录 Baseline ID、kind 和配置哈希。
- Fake 结果不能进入效果指标主表。
- 第三方框架不得绕过 StateMachine、Port、Tool Registry 或 Workspace 权限。

