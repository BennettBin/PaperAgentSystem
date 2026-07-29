# Memory

- `short_term.py`：当前会话最近消息与可追溯 MemorySegment，负责短期记忆、摘要和失效。
- `long_term.py`：跨会话摘要、显式保存的用户偏好和历史文件检索，负责长期记忆与遗忘。
- `summarizer.py`：通过 Small Model Profile 生成结构化摘要；模型异常时使用确定性结构化降级，不影响已生成回答。
- `coordinator.py`：默认 Worker 的 Memory 应用服务；在同一份已持久化会话快照上更新长短期 Memory。
- 临时工作记忆不另建持久事实库：当前 Task/Plan/Observation 位于 `backend/agent_runtime/`，Redis 中仅保存队列、取消标记、事件和短生命周期协调状态，适配器位于 `backend/infrastructure/redis/`。

原始消息和 PostgreSQL 记录始终是事实来源；摘要只用于定位，删除后必须同步失效。

生产链路：

```text
assistant Message 保存
  → 幂等投递 memory_summary
  → ConversationMemoryCoordinator
  → 最近 12 条 Message 保留原文，不进入 Segment
  → 更早 Message 按固定窗口归入稳定 MemorySegment
  → Small Model 生成 topics / user_goals / decisions /
    referenced_files / open_questions / source_message_ids
  → ConversationSummary 使用旧摘要 + 新消息增量更新
```

每条消息最多归属一个未失效 Segment；Segment 可以在未达到固定窗口大小时原地追加，但 ID 不变，已经归属的消息不会因为新消息到来而移动到其他 Segment。下一轮任务始终保留最近 12 条原始消息；同时检索当前会话 `MemorySegment`，命中后通过 `source_message_ids` 回读原文。只有明确的历史/跨会话意图才检索 `ConversationSummary`，并排除当前 Conversation。Memory 使用情况、Segment ID、历史 Conversation ID 和原始消息 ID 会保存在答案的 `rag` 元数据中。
