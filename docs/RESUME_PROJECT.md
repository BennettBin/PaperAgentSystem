# Resume-ready Project Description

**统一对话式学术论文 Agent 系统｜项目负责人**

- 设计 Fast Path / Dynamic Planner + Safe RAG / Multi-Agent 的统一运行时，通过 Port、Profile、预算、权限、Checkpoint、Verifier 与公开 SSE Trace 保持可恢复和可审计；单论文与合格多论文任务使用不同的有界默认路由。
- 实现默认多论文协作 DAG：Coordinator 编排、Paper Reader 按文件并发、Evidence Matrix 聚合、Critic 审阅、Writer 生成、Verifier 独立核验，以及最多一次定向修订。
- 通过任务级 PostgreSQL Blackboard、Tool 白名单、文件作用域、取消传播、部分失败、幂等重放和 ProductService 二次证据边界保证多 Agent 结果可追溯、可恢复、可安全失败。
- 建立版本化评测框架与指标体系；旧代码生成的结果已废弃，当前版本的质量、Token 和 P95 状态明确为待重新评测，不以旧报告代替当前证据。
- 建立失败聚类→授权/匿名化→人工审核→staging→自动回归/安全门禁→版本晋级/回滚的离线 HITL 闭环，并实现管理员 Evaluation Dashboard 与样本级公开轨迹下钻。

面试时同时说明：默认开启不等于所有任务都走 Multi-Agent，也不等于已经证明效果提升；Stage O 被跳过，不声称 SFT/Cascade 效果。
