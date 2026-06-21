# PaperAgent 独立训练工程

该目录只读取已导出的 JSON Schema、Tool 定义和版本化 JSONL 数据，不导入或连接 API、
Worker、数据库、Workspace、Memory 或 Agent Runtime。

```bash
python -m training validate \
  --bundle training/exported \
  --dataset training/fixtures/router.sample.jsonl
```

真实训练依赖使用 `training/pyproject.toml` 的 `train` extra 单独安装。权重、缓存、私有
数据和训练输出不得提交 Git。用户私有会话只有在显式授权、匿名化并记录 consent_id 后
才允许进入导出数据。
