# 阶段 I 自动评测报告

评测框架覆盖 Contract、Component、Trajectory、Domain、E2E、Security 和 Performance。

```bash
python -m evaluation --suite all --output evaluation/reports/stage_i_baseline.json
python -m evaluation --suite security --suite e2e
python -m evaluation.final_acceptance
```

报告记录 Git Commit、配置、Model Profile/Version、Skill 版本、Prompt 内容哈希、数据集
版本、指标和失败项。阶段 I 最终十场景结果：

- 核心任务完成率：100%（门槛 80%）。
- 死循环率：0%。
- 引用支持率：100%（门槛 90%）。
- Workspace/Memory 删除后不可检索：通过。
- 无 SFT/RL Adapter 的基础模型配置：通过。

机器可读报告位于 `evaluation/reports/stage_i_baseline.json` 和
`evaluation/reports/final_acceptance.json`。这些结果是确定性测试环境基线，不等同于
真实 4B 模型真人盲评或生产负载性能结论。
