# ADR-0011: Evidence-gated Agent Promotion

**状态**: 已接受  
**日期**: 2026-07-22

## 背景

结构化 Planner、多 Agent 与模型级联可以增加系统能力，也会增加 Token、延迟、恢复复杂度和无依据输出风险。组件测试通过不能推出产品效果提升。

## 决策

所有新 Agent 路径必须经过冻结数据集、真实模型、相同预算、95% CI、成本与安全门禁，才能成为生产默认。机制完成但效果门禁失败时保留实现与版本化报告，运行时默认关闭并公开 fallback reason。未执行的实验必须标记 `unavailable`，不得用组件指标替代效果指标。

P01 的生产策略因此固定为 Fast Path / Safe RAG；M06 Dynamic Planner 与 N05 Multi-Agent 为显式实验能力。Stage O 被用户跳过，SFT/Cascade 为 `unavailable_o_skipped`。P02 的数据候选只能进入离线 staging，经授权、匿名化、人审、回归与安全 Gate Runner 后晋级，生产环境不自动修改 Prompt 或权重。

## 后果

- 优点：防止“功能更多”等同于“效果更好”，所有对外数字可追溯，可快速回滚。
- 代价：部分完成的高级能力不会默认展示；重新晋级需要新开发集和独立标注。
- 面试表达：重点说明实验设计、负结果和工程决策，而不是隐藏失败。
