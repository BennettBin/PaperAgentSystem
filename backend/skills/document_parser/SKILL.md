---
name: document_parser
description: 把注入的 PDF 文件解析为带页码、章节与视觉材料溯源的结构。 Use when: 上传后的解析索引；提取章节和视觉材料. Do not use when: 回答论文内容；接收本地路径.
---

# PDF 结构化解析

## Metadata

- Description: 把注入的 PDF 文件解析为带页码、章节与视觉材料溯源的结构。
- Trigger: 上传后的解析索引；提取章节和视觉材料。
- Do not trigger: 回答论文内容；接收本地路径。
- Version: 1.0.0
- Input format: `object`
- Output format: `object`

## Function

处理系统注入的文件 ID、会话上下文和参数。只使用本目录 `tools/tools.yaml` 声明的 Tool；不得读取任意本地路径、跨会话数据或输出隐藏推理。

## Execution Steps

1. 按 manifest 的输入契约校验任务、文件范围和参数。
2. 根据下表选择最少必要 Tool；调用前校验其真实 Pydantic 输入 Schema。
3. 保留页码、章节、证据 ID，并区分论文事实、推断和缺失信息。
4. 按 manifest 声明的 `object` 输出契约生成结果。
5. 校验输出结构和证据后完成；失败时返回明确错误，不降级为随意文本。

## Available Tools

| Tool | 用途 | 何时调用 |
|---|---|---|
| `parse_document` | 解析并索引注入的 Workspace PDF | 文件未解析或索引过期时 |

Tool 的真实实现由 `implementation` 指向 `tool_runtime` 中的 Pydantic Tool 类。Skill-local 清单负责白名单、用途和合法样例；共享实现不复制到多个 Skill。

## Structured Input

格式：`object`，必须通过 `input.schema.json`。

```json
{
  "request": "上传后的解析索引",
  "file_ids": ["file-001"],
  "conversation_id": "conversation-001",
  "parameters": {}
}
```

## Structured Output

格式：`object`，必须通过 `output.schema.json`。示例：

```json
{"file_id":"file-001","page_count":10,"section_count":6,"chunk_count":24,"visual_artifact_count":3}
```

## Acceptance

- 输入和输出通过各自声明的结构化契约。
- 每次 Tool 调用仅使用本 Skill 清单中的名称，参数通过真实 Pydantic Schema。
- 事实绑定可追溯证据；不确定或缺失内容明确标注。
- 不补造论文内容、Tool 结果、引用或路径。

## Anti-Patterns

- 不把任意字符串当作结构化结果。
- 不绕过 Skill-local Tool 白名单或 Tool Runtime。
- 不访问未注入路径、未授权工具或其他会话。
- 不把推断写成论文原文事实。

## Resources

- `manifest.yaml`：触发、生命周期和输入输出格式。
- `input.schema.json`：结构化 object 输入契约。
- `tools/tools.yaml`：本 Skill 可用 Tool、用途、实现与合法参数样例。
- `examples.json`：该 Skill 的输入输出样例。
- `references/layout_and_provenance.md`：领域判定或执行细则；相关任务执行前按需读取。
