# ADR-0003: SSE 事件流推送任务进度

**状态**: 已接受  
**日期**: 2026-06-19

## 背景

前端需要实时获取后台任务进度，包括：

- 需求澄清问题
- Skill 选择结果
- Plan 生成
- Step 执行状态
- Tool 调用结果
- 最终任务完成

## 决策

采用 Server-Sent Events (SSE) + PostgreSQL TaskEvent 表：

- HTTP 长连接推送
- 每个任务有唯一 task_id
- 事件表包含 sequence、task_id、event_type、payload
- 支持 Last-Event-ID 断线续传
- Redis 临时缓存最近事件加速推送

## 事件类型

```
task_queued
task_started
requirement_clarification_requested
requirement_clarification_received
skill_selected
plan_created
step_started
step_completed
step_failed
tool_started
tool_completed
tool_failed
subagent_started
subagent_completed
subagent_failed
verification_failed
artifact_created
task_completed
task_failed
task_cancelled
```

## 替代方案

1. **WebSocket**: 优点是双向。缺点是断线处理复杂。
2. **Polling**: 优点是简单。缺点是延迟高、资源浪费。
3. **GraphQL Subscription**: 优点是灵活。缺点是复杂度高。

## 后果

### 优点

- ✅ 标准 HTTP 易于集成
- ✅ 浏览器原生支持
- ✅ 断线自动重连
- ✅ 事件持久化便于回放

### 缺点

- ⚠️ 不支持真正的双向通信
- ⚠️ 需要处理超时

## 不变量

1. 每个事件必须有唯一 event_id
2. 事件必须包含 sequence 用于排序
3. 事件 payload 必须通过 Pydantic Schema 验证
4. 删除相关任务后，事件仍可查询但不再推送

## 验收标准

- [ ] SSE 端点返回 text/event-stream
- [ ] Last-Event-ID 断线续传测试通过
- [ ] 事件顺序不乱序
- [ ] Redis 宕机后回源 PostgreSQL 成功
