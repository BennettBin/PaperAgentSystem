# Memory

- `short_term.py`：当前会话最近消息与可追溯 MemorySegment，负责短期记忆、摘要和失效。
- `long_term.py`：跨会话摘要、显式保存的用户偏好和历史文件检索，负责长期记忆与遗忘。
- 临时工作记忆不另建持久事实库：当前 Task/Plan/Observation 位于 `backend/agent_runtime/`，Redis 中仅保存队列、取消标记、事件和短生命周期协调状态，适配器位于 `backend/infrastructure/redis/`。

原始消息和 PostgreSQL 记录始终是事实来源；摘要只用于定位，删除后必须同步失效。