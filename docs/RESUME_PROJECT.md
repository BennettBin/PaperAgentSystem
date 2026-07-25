# Resume-ready Project Description

**统一对话式学术论文 Agent 系统｜项目负责人**

- 设计 Fast Path / Safe RAG / 实验型 Plan-and-Execute / Multi-Agent 的统一运行时，通过 Port、Profile、预算、权限、Checkpoint、Verifier 与公开 SSE Trace 保持可恢复和可审计；隔离 Docker Compose 验收 8 个服务全部 healthy，真实 API 无 Fake 默认回答链。
- 构建 300-case 中英冻结评测集与 B0–B3 对照实验，完成 1,200 个系统结果、1,800 次本地真实模型调用，调用 metadata/usage 完整率 100%、系统异常 0；报告总体/切片、95% CI、Token、P95 latency 和失败分类。
- Planner V2 在 270-case 验收中实现最终 Schema 合法率 100%、非法 Tool 调用 0、Required Step Recall 96.84%；进一步真实消融未通过效果/成本门槛。后续按产品策略将有界 Dynamic Planner 设为文档任务默认的公开计划/状态层，但仍由 Safe RAG 执行并保留安全回退，不把该策略变更表述为效果晋级。
- 多 Agent 六组×90 case 消融中，Full 相对 Single 的 Claim Support +5.63pp，但 Task Success -1.11pp、Token +398.03%；据此关闭额外 LLM Critic/Verifier/Revision 默认链，保留确定性核验。
- 建立失败聚类→授权/匿名化→人工审核→staging→自动回归/安全门禁→版本晋级/回滚的离线 HITL 闭环，并实现管理员 Evaluation Dashboard 与样本级公开轨迹下钻。

面试时同时说明：B0–B3 Task Success 仅 6.33%–8.0%，无系统显著优于 B0；Stage O 被跳过，不声称 SFT/Cascade 效果。
