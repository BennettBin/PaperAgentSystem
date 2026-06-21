# ADR-0007: Conversation、Task 和 Workspace

**状态**: 已接受  
**日期**: 2026-06-19

## 背景

系统需要管理：

- **Conversation**: 用户与系统的历史对话
- **Task**: 对话内的单个请求和后台执行
- **Workspace**: 文件存储和执行环境隔离

三者的关系需要清晰定义。

## 决策

```
Conversation (主)
  ├─ Message (输入和输出)
  ├─ Task (此对话内的任务)
  │  ├─ State Machine (执行状态)
  │  ├─ Plan
  │  ├─ Step / ToolCall
  │  └─ Result
  └─ ConversationWorkspace (持久文件存储)
     ├─ uploads/ (用户上传)
     ├─ shared/ (本会话共享)
     └─ artifacts/ (生成文件)

Task (临时执行视图)
  └─ TaskWorkspace
     ├─ inputs/ (只读，来自 ConversationWorkspace)
     ├─ scratch/ (读写临时目录)
     ├─ scripts/ (脚本存储)
     ├─ outputs/ (任务输出)
     └─ logs/ (执行日志)
```

**关键约束**:

- 一个 Conversation 可有多个 Task
- 一个 Task 只属于一个 Conversation
- TaskWorkspace 是隔离的执行环境
- ConversationWorkspace 是持久存储，TaskWorkspace 完成后可清理
- 跨 Task 文件共享通过 promote_workspace_entry

## 替代方案

1. **Task 即 Conversation**: 缺点是不支持多轮对话。
2. **Conversation 只是日志**: 缺点是无法查询历史。
3. **无隔离的共享存储**: 缺点是安全问题。

## 后果

### 优点

- ✅ 对话历史持久化
- ✅ 任务隔离，安全性高
- ✅ 支持文件共享和提升
- ✅ Worker 重启可恢复

### 缺点

- ⚠️ 需要维护两层 Workspace
- ⚠️ 文件提升需要明确操作
- ⚠️ 清理策略需要配置

## 不变量

1. Task 删除后，TaskWorkspace 可清理但 Message 保留
2. Conversation 删除后，所有关联资源级联删除
3. 跨 Task 文件访问必须通过 promote_workspace_entry
4. TaskWorkspace 中绝对路径、`..` 和符号链接被禁止

## 验收标准

- [ ] Conversation-Task-Workspace 映射正确
- [ ] 路径穿越测试 100% 阻断
- [ ] 并行任务目录隔离
- [ ] Worker 重启后可恢复
