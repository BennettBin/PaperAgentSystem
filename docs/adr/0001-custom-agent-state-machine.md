# ADR-0001: 自定义 Agent 状态机

**状态**: 已接受  
**日期**: 2026-06-19

## 背景

Agent 系统需要支持复杂的任务编排，包括需求澄清、Skill 选择、规划、执行、验证和重规划。异步状态管理需要可靠的持久化和恢复。

## 决策

实现显式状态机，而非隐式的函数调用链：

- 定义清晰的状态集和迁移规则
- 每个状态有对应的 Orchestrator 节点
- 状态变化必须持久化到数据库
- 任务恢复通过重放状态和 Context 实现
- SSE 事件流反映状态迁移

## 状态模型

```
RECEIVED → UNDERSTANDING → REQUIREMENT_CHECK
REQUIREMENT_CHECK → CLARIFYING (if need clarification) / EXECUTING (if ready)
CLARIFYING → WAITING_USER → REQUIREMENT_CHECK
EXECUTING → SKILL_SELECTED → PLANNED → EXECUTING → VERIFYING
VERIFYING → COMPLETED / REPLANNING / FAILED
任意非终止状态 → CANCELLED
```

## 替代方案

1. **事件溯源**: 通过事件日志重建状态。缺点：查询当前状态效率低。
2. **隐式状态**: 通过函数调用位置推断。缺点：难以追踪、无法可靠恢复。
3. **有限状态机库 (transitions、transitions_plus)**: 优点是现成，缺点是绑定框架。

## 后果

### 优点

- ✅ 状态清晰可追踪
- ✅ 可靠的任务恢复
- ✅ SSE 事件和状态一致
- ✅ 支持任意阶段取消和重新开始

### 缺点

- ⚠️ 需要维护状态迁移规则
- ⚠️ 数据库 I/O 增加
- ⚠️ 复杂的并发场景需要锁机制

## 不变量

1. 状态值一旦进入 PostgreSQL 不能更改
2. 每次状态变化后 Trace 必须记录
3. 任务只能在允许的状态下被取消
4. 状态迁移必须原子性（事务保护）
5. 无限期停留在某状态需要超时机制

## 验收标准

- [ ] 状态机实现支持所有 7 个预定义状态
- [ ] 状态变化持久化到 PostgreSQL
- [ ] 所有非法迁移被拒绝
- [ ] 任务恢复测试通过
- [ ] SSE 事件和状态一致
