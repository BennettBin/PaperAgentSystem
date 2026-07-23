# Evaluation Truth Classes

任何评测运行和结果在进入对比表前必须标记以下一种真实性类别。类别描述的是证据来源，
不表示结果质量高低。

| 类别 | 允许的组件 | 可支持的结论 | 禁止的结论 |
|---|---|---|---|
| `unit_fake` | FakeLLM、FakeRetriever、内存 Repository、fixture | Schema、状态机、预算、错误恢复等确定性逻辑正确 | 真实任务质量、真实 Token、真实延迟、模型优劣 |
| `integration_real` | 真实 PostgreSQL/Redis/MinIO/Celery/SSE，可使用确定性模型替身 | Adapter、持久化、隔离、恢复和系统开销 | 生成质量、模型路由准确率、真实模型成本 |
| `offline_real_model` | 冻结数据集、真实 Model Profile、真实 Retriever、版本化 Prompt | 效果、轨迹、Token、延迟和模型对比 | 未记录版本或混入测试集调参后的泛化结论 |
| `human_review` | 有标注指南、样本 ID、双人复标或明确单人审核 | 主观质量、事实支持、结构和错误分类 | 无分母、无样本来源或无一致性记录的百分比 |

## 强制规则

- Fake 结果必须在报告标题、metadata 和 Dashboard 中显式标记，不能进入真实效果主表。
- `Task Success`、`Citation Support`、模型准确率、真实 Token/延迟等效果指标至少需要
  `offline_real_model`；主观指标还需要 `human_review` 或可靠程序金标。
- `integration_real` 可以证明基础设施工作，但不能证明 Agent 比 Baseline 更强。
- 一份报告可以包含多类结果，但每个 suite/case 必须能反查自己的 truth class。
- 测试集不得用于 Prompt few-shot、阈值选择、SFT、DPO 或错误驱动开发。

## 当前历史结果的归类

- 普通 pytest 中的 FakeLLM/FakeEmbedding 结果：`unit_fake`。
- Testcontainers PostgreSQL/Redis/MinIO/SSE：`integration_real`。
- K04 真实 PDF 格式但确定性 LLM 替身的 E2E：解析/存储/检索属于
  `integration_real`，不能作为真实生成质量结果。
- `evaluation/reports/final_acceptance.json` 的固定场景通过率主要来自 fixture/pytest，当前
  不能作为 L05 的真实模型 Baseline。
- `evaluation/reports/stage_i_baseline.json` 中部分 suite 只检查产物存在，属于工程审计，
  不能作为 Agent 效果对比。
- K02/K03 文档记录过独立真实 Ollama 探活/推理，但在新的冻结数据集上重跑前，不进入
  L05 主结果表。

