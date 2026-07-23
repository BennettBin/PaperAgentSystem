# RAG 系统章节精确定位修改计划

> 状态：K04.1～K04.4 已完成
> 适用仓库：`D:\vscode\Projects\PaperAgentSystem`  
> 原始问题：用户明确指定“第 4.5 节”“section 3.2”“Methods”等章节后，系统仍可能召回其他章节，或者只看到目标章节的一小部分。

## 1. 审查结论与修改原则

原计划提出的 section-aware RAG 方向正确，但不能直接按原方案实施，原因如下：

1. 当前项目已经存在 `DocumentSection`、`StructureAwareChunker`、`section_path`、
   `HybridRetriever` 和 ReAct Self-RAG，不应另建一套平行的 `self_rag/` 目录。
2. 当前解析以 PDF layout block、页码和 bbox 为事实来源。不能退化为只在
   `full_text` 上计算 `start_char/end_char`，否则会破坏引用定位。
3. 当前真正缺少的是稳定的章节编号、规范化标题、父子关系和持久化 section tree，
   而不是完全缺少 section。
4. “在指定章节中问一个事实”和“完整总结指定章节”是两种检索模式：
   - 章节内问答需要在目标章节范围内做相关性检索。
   - 章节总结需要按原文顺序覆盖整个章节，不能只取相似度最高的几个 chunk。
5. 章节编号/标题识别应以确定性解析为主，模型只用于补充歧义判断；不能让模型自由生成
   section ID。
6. 旧索引必须通过 schema/index version 自动识别并重建，不能只在文档中提醒用户手工处理。

本次修改必须复用当前架构，并遵守以下边界：

- PDF 原始页码、bbox、block ID 是引用真值。
- `ParsedDocumentModel` / `DocumentChunkModel` 是章节索引持久化真值。
- Self-RAG 仍决定是否需要检索；Section Resolver 只在需要检索时确定检索范围。
- 普通问题继续走现有混合检索。
- 不修改无关 UI、认证、模型配置和训练模块。
- 不新增重量级依赖；fuzzy match 优先使用标准库，除非评测证明必须引入依赖。

---

## 2. 当前代码基线

Codex 开始实现前必须重新确认这些文件，没有确认前不得创建替代目录：

| 职责 | 当前文件 |
|---|---|
| PDF layout 与 heading 识别 | `document_processing/pdf_parser.py` |
| 解析 Schema | `document_processing/schema.py` |
| Parent/child chunk 与索引 | `rag/indexing.py`、`rag/schema.py` |
| PostgreSQL 文档和 chunk 表 | `infrastructure/postgres/models.py` |
| 混合检索、section hint 与展开 | `rag/retrieval.py` |
| ReAct / Self-RAG 决策 | `agent_runtime/react_self_rag.py` |
| 产品问答链路 | `apps/api/product_service.py` |
| 文档检索 Tool | `tools/`、`tests/test_document_tools.py` |
| 当前检索测试 | `tests/test_hybrid_retrieval.py`、`tests/test_document_indexing.py` |

现有能力不可删除：

- 页码、bbox、source block ID 追踪。
- parent/child chunk。
- Vector + FTS + RRF + rerank。
- Workspace 和 file ID 隔离。
- Self-RAG 的 `clarify/retrieve/answer` 决策。
- 引用 evidence metadata。

---

## 3. 目标数据流

```text
PDF layout blocks
→ heading candidates
→ normalized section tree
→ section-aware parent/child chunks
→ section catalog + chunk metadata 持久化

用户问题
→ Self-RAG 判断是否检索
→ SectionReferenceParser 提取编号/标题/指代
→ SectionResolver 精确或模糊匹配
→ 决定 section_qa / section_summary / ordinary_rag
→ SQL 级 section scope filter
→ 章节内相关性检索或顺序覆盖读取
→ rerank / context budget
→ 带 section evidence 的回答
```

---

## 4. 数据契约修改

### 4.1 扩展现有 `DocumentSection`

修改 `document_processing/schema.py` 中的现有结构，不创建重复的 `PaperSection`。

建议字段：

```python
class DocumentSection(BaseModel):
    section_id: str                 # 程序生成的稳定 ID
    number: str | None              # "4.5"、"A.2"、"IV"
    title: str                      # 原始标题
    normalized_title: str           # "model architecture"
    level: int
    parent_section_id: str | None
    section_path: list[str]         # ["4 Results", "4.5 Managerial Implications"]
    page_start: int
    page_end: int
    heading_block_id: str
    block_ids: list[str]            # 本节直接拥有的正文块
    descendant_block_ids: list[str] # 可选；父节作用域可按树动态计算
    ordinal: int                    # 文档顺序
```

要求：

- `section_id` 由程序生成，不能直接信任模型输出。
- `number` 与 `title` 分离，避免把 `"4.5"` 当作普通语义词。
- `section_path` 必须保留层级，不再永远只有 `[section.title]`。
- 继续保留页码和 block ID，不以字符偏移替代。

### 4.2 持久化 section catalog

新增 `DocumentSectionModel`（推荐）或等价的结构化表，至少保存：

- workspace_id、file_id、document_id。
- section_id、number、title、normalized_title。
- level、parent_section_id、section_path、ordinal。
- page_start、page_end、heading_block_id、block_ids。
- parser/schema version。

为以下字段建立索引：

- `(workspace_id, file_id, number)`
- `(workspace_id, file_id, normalized_title)`
- `(document_id, ordinal)`
- `parent_section_id`

`DocumentChunkModel` 增加或明确持久化：

- `section_id`
- `section_number`
- `section_title`
- `section_path`
- `chunk_index_in_section`

需要新增 Alembic migration，且 migration 必须可 upgrade/downgrade。

---

## 5. 解析与章节树

### 5.1 改造现有 PDF parser

在 `document_processing/pdf_parser.py` 的 layout block 流程中增强 heading detection，
不要再从拼接后的全文重新切割。

heading candidate 综合使用：

- 字号相对正文基线。
- 粗体/字体信息（PyMuPDF 可获得时）。
- 行长度、前后留白和页面位置。
- 编号模式。
- 常见无编号标题。
- PDF bookmark / TOC（存在时作为辅助信号，不能作为唯一真值）。

编号至少支持：

- `1`、`1.2`、`1.2.3`
- `A`、`A.1`
- `I`、`II`、`IV`
- `Chapter 3`、`Section 4.5`
- 无编号 `Abstract`、`References`、`Appendix`

常见标题和别名至少覆盖：

- Abstract / 摘要
- Introduction / 引言
- Related Work / Literature Review / 相关工作
- Background / 背景
- Methods / Methodology / Materials and Methods / 方法
- Experiments / Experimental Setup / 实验
- Results / Findings / 结果
- Discussion / 讨论
- Conclusion / Conclusions / 结论
- References / 参考文献
- Appendix / Supplementary Material / 附录

### 5.2 防止错误标题

必须处理以下负例：

- 目录页中的章节条目不能重复变成正文 section。
- 页眉、页脚和图表标题不能成为 section。
- 正文中以数字开头的普通句子不能成为 section。
- References 中的编号参考文献不能成为 section。
- OCR 断行标题需要合并，但低置信度时应记录 warning。

### 5.3 构建父子关系

根据编号层级和文档顺序构建树：

```text
4 Experiments
├── 4.1 Dataset
├── 4.2 Baselines
└── 4.3 Ablation Study
```

语义：

- 子节的直接 `block_ids` 不重复归入父节直接正文。
- 用户指定父节时，检索 scope 包含父节及全部后代。
- `page_end` 是该 section scope 的最后一页。
- 无编号标题通过 heading level 和最近祖先确定父级。

### 5.4 Parser 验收指标

建立至少 10 篇结构不同的测试 PDF：

- 单栏、双栏。
- 有/无编号。
- 多级编号。
- Appendix。
- 带目录页。
- OCR 或标题断行。

指标：

- Heading detection F1 ≥ 0.92。
- Section number exact accuracy ≥ 0.98。
- Parent relation accuracy ≥ 0.95。
- Section page range accuracy ≥ 0.95。
- 已有页码/bbox 映射测试不得退化。

---

## 6. Section-aware chunk 与索引

修改现有 `StructureAwareChunker`：

1. 先遍历 section tree，再在每个 section 的直接正文内切 child chunk。
2. chunk 不得跨 section。
3. 每节至少生成一个 parent chunk；有正文时至少一个 child chunk。
4. chunk embedding 输入包含规范化 section path，但 `text` 仍保存原始正文。
5. `previous_chunk_id` / `next_chunk_id`：
   - 同一 section 内必须连续。
   - 是否跨 section 链接必须明确，章节展开不得依赖跨节链接。
6. 父节 parent chunk 不复制全部子节正文，避免索引重复；父节查询通过 section scope 获取后代。

旧索引兼容：

- 增加 `section_schema_version` / `embedding_model` 版本检查。
- 版本不匹配时，解析任务自动重建该文件的 section catalog 和 chunks。
- 重建必须幂等，不产生重复 section/chunk。
- 重建失败时保留旧索引并明确标记，不允许静默删除可用数据。

---

## 7. 章节引用解析

新增职责明确的模块，例如 `rag/section_resolver.py`，不要把逻辑继续堆入
`rag/retrieval.py`。

### 7.1 `SectionReferenceParser`

输入用户问题和最近对话，输出结构化引用：

```python
class SectionReference(BaseModel):
    kind: Literal["number", "title", "deictic", "none"]
    number: str | None
    title: str | None
    raw_text: str | None
    requested_mode: Literal["qa", "summary"]
    confidence: float
```

支持：

- `第 4.5 节`、`第4章`、`4.5节`
- `section 3.2`、`Sec. 3.2`
- `3.2 Model Architecture`
- `Methods section`、`结果部分`
- `这一节`、`上一节`：只能结合最近一次已解析的 section context；没有上下文时必须澄清。

确定性正则优先于模型：

- 编号被正则可靠提取时，模型不得改写编号。
- 模型只可补充标题别名、意图类型和歧义判断。
- 解析结果进入 Trace，但不记录不必要的完整用户正文。

### 7.2 章节匹配 `SectionResolver`

匹配优先级：

```text
number exact
> number + normalized title exact
> normalized full title exact
> alias exact
> token/fuzzy title match
> optional title embedding
> unresolved
```

规则：

- 标题 normalization 去编号、标点、大小写和多余空格，但保留数字语义。
- 中英文 alias 必须集中版本化，不能散落在 prompt 和 retriever 中。
- fuzzy threshold 不能拍脑袋写死；应在固定集上选择，并记录误匹配率。
- 出现多个高分候选且差值低于 margin 时，不得任选一个，应返回候选并触发一次澄清。
- 找不到 section 时明确告诉用户“未识别到该章节”，同时可展示最接近标题；不能直接悄悄退回全篇检索并假装命中。

章节匹配验收：

- 编号 exact accuracy = 100%。
- 标准标题 Top-1 ≥ 0.98。
- 中英别名 Top-1 ≥ 0.95。
- 不存在章节的错误强匹配率 ≤ 0.02。
- 歧义样例应澄清率 ≥ 0.95。

---

## 8. 检索模式

### 8.1 Self-RAG 路由

保留当前 `ReActSelfRAGController` 的 `clarify/retrieve/answer`。当 action 为
`retrieve` 时，再执行 SectionReferenceParser / SectionResolver。

不要让小模型直接生成数据库 filter；filter 必须由程序根据 resolved section 构建。

### 8.2 三种检索模式

#### A. `ordinary_rag`

没有明确章节引用时，保持现有 Vector + FTS + RRF + rerank。

#### B. `section_qa`

例如：“4.5 节的三个管理启示是什么？”

流程：

1. 精确解析并 resolve section。
2. 计算 scope：目标 section；若指定父节则包含全部后代。
3. 在 SQL 查询阶段使用 workspace_id + file_id + section scope 过滤。
4. 只在 scope 内执行 vector/keyword/RRF/rerank。
5. 必要时展开命中 chunk 的同节前后相邻块。
6. 最终 evidence 必须保留 section ID、页码、bbox。

禁止把“全篇检索后 Python post-filter”作为新索引的正常路径；它只能用于 legacy fallback。

#### C. `section_summary`

例如：“总结第 4 节”“这一节主要讲了什么？”

不能只做 top-k semantic search。应：

1. 按 section tree 和 `chunk_index_in_section` 顺序读取整个 scope。
2. 在 context budget 内优先保证首、中、尾覆盖。
3. 超长章节使用分段摘要或 map-reduce：
   - 每个连续窗口生成有来源的局部摘要。
   - 最终摘要只综合局部摘要及其 evidence。
4. 输出 coverage 信息，例如已覆盖多少 chunk / 页。
5. 不得把其他章节补入来填满 token。

### 8.3 Section-aware rerank

SQL scope 已过滤后，再做章节内 rerank。排序特征可包含：

- 语义/关键词 rerank score。
- 标题与 query 的匹配。
- exact section 与 descendant section。
- chunk 在 section 中的位置。
- 相邻上下文连续性。

不要用任意 `+0.20` 常数直接定案；权重需通过固定评测集比较，并保留 baseline 报告。

---

## 9. 回答与引用

传给大模型的上下文必须包含程序生成的：

- resolved section ID / number / title / path。
- retrieval mode。
- scope 中的 section IDs。
- 每条 evidence 的 page、bbox 和 chunk ID。
- section coverage（用于 summary）。

系统提示要求：

- 只基于 resolved scope 回答。
- 如果目标章节不存在或证据不足，明确说明。
- 不使用其他章节内容补造。
- `[E#]` 仍由程序绑定到 evidence，不能让模型伪造 citation ID。

回答 metadata 至少增加：

```json
{
  "rag": {
    "used": true,
    "mode": "section_qa",
    "section_reference": "4.5",
    "resolved_section_id": "...",
    "resolved_section_path": ["4 Results", "4.5 Managerial Implications"],
    "scope_section_ids": ["..."],
    "coverage": {"selected_chunks": 5, "scope_chunks": 7}
  }
}
```

---

## 10. Trace 与隐私

新增结构化 Trace：

- `section.reference_parsed`
- `section.resolved`
- `section.ambiguous`
- `rag.section_scope_built`
- `rag.section_retrieved`
- `rag.section_coverage`

记录：

- reference kind、规范化编号/标题。
- 候选 section ID 与分数。
- 最终 section、scope IDs。
- 召回和送入模型的 chunk ID、section ID、页码。
- fallback 原因和 schema/index version。

不要在普通日志中记录完整论文正文或完整 prompt。

---

## 11. 测试与评测

必须先写失败测试，再修改实现。

### 11.1 单元测试

建议文件：

- `tests/test_section_tree.py`
- `tests/test_section_reference_parser.py`
- `tests/test_section_resolver.py`
- `tests/test_section_chunking.py`
- `tests/test_section_retrieval.py`

覆盖：

- 多级数字、Roman、Appendix 和无编号标题。
- TOC、页眉、图标题和 references 负例。
- 中英文编号/标题/别名。
- 不存在章节和多个相似标题。
- “这一节”有/无历史 section context。
- parent scope 包含全部 descendants。
- chunk 不跨 section。
- legacy index 自动重建与失败保留。

### 11.2 固定章节定位评测集

至少准备：

- 10 篇真实或可合法使用的不同结构论文。
- 每篇人工标注 section tree。
- 每篇至少 10 条章节 query：
  - 编号 exact。
  - 标题 exact。
  - 中英别名。
  - 拼写/格式轻微变化。
  - 父章节。
  - 不存在章节。
  - 歧义章节。
- 总计至少 100 条 query。

### 11.3 指标

解析：

- Heading F1 ≥ 0.92。
- Section number accuracy ≥ 0.98。
- Parent relation accuracy ≥ 0.95。

定位：

- Section resolver Top-1 ≥ 0.95。
- Number exact = 1.00。
- False forced match ≤ 0.02。

检索：

- Section Scope Accuracy ≥ 0.98。
- Section Purity@3 ≥ 0.95。
- Section Pass@5 ≥ 0.95。
- Section QA Recall@5 ≥ 0.90。
- Parent-section descendant coverage ≥ 0.90。
- 普通 RAG Recall@5 不得下降超过 0.02。

总结：

- 目标章节首/中/尾覆盖率 ≥ 0.90。
- 非目标章节混入率 ≤ 0.03。

引用：

- 引用 section 正确率 ≥ 0.98。
- 引用页码/bbox 可定位率 = 1.00。

### 11.4 E2E 场景

至少验证：

1. “请总结第 3 节。”
2. “解释 section 2.1 的训练策略。”
3. “Methods section 用了什么数据集？”
4. “给我讲一下 4.5 节的三个管理影响。”
5. “总结这一节。”（有上一轮 section context）
6. 指定不存在的 `section 9.9`。
7. 同时上传两篇论文，只指定其中一篇的 section。
8. 普通全篇问题不触发 section filter。

---

## 12. 实施工作包

建议在 `DEVELOPMENT_PLAN.md` 中新增一个独立工作包，例如 `K04`，状态先设为
`in_progress`。不要把以下所有内容作为一次无边界修改同时提交。

### K04.1：Section Schema、解析树与迁移

- 扩展 `DocumentSection`。
- 增加 section catalog 表和 chunk 字段。
- 改造 layout heading detection 和 section tree。
- 完成 migration、parser/chunker 测试。

验收通过后再进入 K04.2。

### K04.2：Section Reference Parser 与 Resolver

- 编号/标题/指代解析。
- normalization、alias、fuzzy 和歧义澄清。
- 固定 100-query resolver 评测。

### K04.3：Section QA 与 Summary Retrieval

- SQL scope filter。
- parent/descendant scope。
- section QA rerank 和相邻块。
- section summary 顺序覆盖与长章节压缩。
- 普通 RAG 回归。

### K04.4：集成、重索引、Trace 与 E2E

- 自动检测旧 index version 并重建。
- 接入 ReAct Self-RAG 和回答 metadata。
- 增加 Trace、引用验证和真实 PDF E2E。
- 同步技术、产品、执行计划、README 和过程日志。

---

## 13. Codex 执行规则

Codex 接到该计划后必须：

1. 先读取 `AGENTS.md` 和四份开发文档。
2. 查看 Git 状态，保留当前 K03 等未提交修改。
3. 审查现有 Port/Schema，禁止创建重复的 `self_rag/` 平行架构。
4. 一次只执行一个 K04 子工作包。
5. 先新增失败测试和固定评测数据，再实现。
6. 每个子工作包运行相关 pytest、Ruff、Mypy；涉及前端/API 时运行对应检查。
7. 最后运行完整测试和真实多章节 PDF 验收。
8. 未达到指标时保持 `in_progress`，不得降低阈值或标记完成。
9. 不主动 commit 或 push。

---

## 14. 最终完成定义

只有同时满足以下条件，K04 才能标记 `completed`：

- 用户通过编号、标题、中英别名能稳定定位目标章节。
- 父章节查询覆盖其子章节。
- 章节问答只在目标 scope 内检索。
- 章节总结覆盖整个章节，而不是只返回最相关开头。
- 不存在或歧义章节不会被强行错误匹配。
- 旧索引可安全自动重建。
- 普通 RAG 指标无明显回退。
- 引用仍可定位到原始页码和 bbox。
- 固定评测和真实 PDF E2E 全部达到上述阈值。

建议提交信息（仅在用户要求提交时使用）：

```text
feat(rag): add structured section resolution and scoped retrieval
```
