# PaperAgent Evaluation Dataset Card

## 当前版本

- Release：`paperagent-eval-v1`
- 固定 test 集：`evaluation/datasets/v1/test_cases_v1.jsonl`
- 文档逻辑页：`evaluation/datasets/v1/documents_v1.jsonl`
- Manifest：`evaluation/datasets/v1/dataset_manifest_v1.json`
- Split Manifest：`evaluation/datasets/v1/split_manifest_v1.json`
- 构建入口：`python -m evaluation.datasets.build_l02 ...`

L02 release 含 300 条评测专用 test case：L1/L2/L3 各 60 条，L4/L5 各 45 条，L6 30 条；
其中英文 240 条、中文 60 条。所有 case 都保留来源、许可、构建版本、资源预算和禁止行为，
且 `usable_for_training=false`。

## 数据来源与许可

1. QASPER v0.3 test：来自 AI2 的真实 NLP 论文问题、独立回答和 supporting evidence，数据集
   标注为 CC BY 4.0。源归档 SHA-256 固定在 release Manifest。
2. CSL Benchmark test：来自 CSL 中文科学文献标题、摘要、关键词及学科/门类标签，仓库
   采用 Apache 2.0。源 ZIP SHA-256 固定在 release Manifest。

L1 使用 CSL 官方 test 标签。L2/L3 使用 QASPER 原始人工问题与证据。L4/L5 是对多个互不
相同论文的人工 QA 进行确定性组合而得到的比较/Evidence Matrix case，不宣称其组合提示或
综述文本由原数据集标注者撰写。L6 是基于真实 QASPER 问题构造的安全、故障和控制流压力
场景，均标记 `derived_robustness`。

## 证据与页码

218 个证据任务含 657 个 Gold span。每条 Evidence 同时记录 paper、evaluation-rendered
page、section 和 claim-support ID；测试逐条验证 span 确实存在于声明页。这里的页码属于
本 release 的确定性逻辑页/渲染 PDF，而不是原出版 PDF 页码：第 1 页为标题/摘要，之后每个
来源段落占一页。该契约避免把无法从 QASPER JSON 证明的原始出版页码伪造为 Gold。

`evaluation.datasets.render` 可将逻辑页渲染为单栏、双栏和低分辨率灰度扫描 PDF。release
提交三个真实 PDF 样本并固定哈希；全部文档可用同一 renderer 重建。版式是评测输入变体，
不是对原论文版式的陈述。

## 双标注与一致性

QASPER 问题由独立 NLP 从业者回答。构建器只接纳前两位回答者在答案类型上达成共识且存在
可定位证据的 Gold；分歧样本不会静默晋级。release 从 L2/L3 分层抽取 30 条（10%）保留
两位匿名化 worker ID 和标签，一致性报告为 Cohen's kappa 1.0。由于采用 consensus-gold
准入策略，该值衡量已发布 Gold 的一致性，不代表 QASPER 全量原始数据的一致性。

## Split、去重与隐私

当前 release 只有固定 test split。paper、conversation、来源簇、文本指纹和版本化
Embedding cluster 的跨 split 泄漏均为 0。test 集不得用于 Prompt few-shot、SFT、DPO、
阈值选择或错误驱动调参。用户私有会话和上传论文数量为 0；下载缓存位于被 Git 忽略的
`scratch/l02_sources/`，release 不包含密钥或用户数据。

## 覆盖与适用范围

支持按 `task_family`、`difficulty`、`language`、`paper_type` 下钻。输入覆盖中英文、长短
文档、单栏、双栏、退化扫描、章节缺失、引用歧义、Prompt Injection、工具故障、部分失败、
取消和澄清。数据适合评估路由、检索、引用、跨论文比较、Evidence Matrix 和鲁棒控制流。

## 已知偏差与限制

- 英文部分集中于 NLP 论文；中文部分是标题/摘要级科学文献元数据，不等同于中文全文 QA。
- L4/L5 是组合任务，参考答案适合程序化 Evidence/Claim 检查，流畅综述质量仍需人工 Judge。
- 退化扫描是可复现的灰度低分辨率渲染，不覆盖所有真实 OCR 噪声。
- consensus-gold 过滤提高标签可靠性，也可能降低对本身高度歧义问题的代表性。
- 当前数据只用于评测，不能由此推断真实模型、延迟、Token 或成本表现；这些属于 L03～L05。

## 真实性声明

Schema 和 fixture 测试仍属于 `unit_fake`；本 release 的来源与标注属于真实公开数据，但只有
在 L04/L05 使用真实模型、完整 Trace 和冻结配置执行后，才可产生 `offline_real_model`
效果结论。
