# ADR-0004: Port-Adapter 边界

**状态**: 已接受  
**日期**: 2026-06-19

## 背景

系统涉及多个外部系统：

- 数据库 (PostgreSQL)
- 缓存 (Redis)
- 对象存储 (MinIO)
- 任务队列 (Celery)
- LLM 服务 (vLLM)
- Embedding 服务
- 事件发布

Domain 层不应直接依赖这些系统。

## 决策

采用 Port-Adapter 模式（六边形架构）：

```
Domain/Application → Port (接口) → Adapter (实现)
```

**Port** (core/ports/):
- `ConversationRepository`
- `MessageRepository`
- `TaskRepository`
- `WorkspaceRepository`
- `LLMClient`
- `EmbeddingClient`
- `ObjectStore`
- `TaskQueue`
- `EventPublisher`
- 等等

**Adapter** (infrastructure/):
- PostgreSQL Repository
- Redis Cache
- MinIO ObjectStore
- Celery TaskQueue
- vLLM/llamacpp LLMClient
- 等等

**Fake** (testing/):
- FakeRepository (内存)
- FakeLLMClient (确定性输出)
- FakeObjectStore (临时文件)
- 等等

## 替代方案

1. **直接依赖框架**: 简单但难以测试。
2. **单一接口模式**: 只有一个大接口。缺点是粒度太粗。
3. **依赖注入 (DI)**: 没有明确的 Port 定义。缺点是隐式。

## 后果

### 优点

- ✅ Domain 不依赖框架库
- ✅ Fake 和真实实现可互换
- ✅ 易于测试和模拟
- ✅ 新增 Adapter 不需要修改 Domain

### 缺点

- ⚠️ 代码行数增加
- ⚠️ 需要明确的接口定义
- ⚠️ 需要适配层转换

## 不变量

1. Domain Entity 不包含 ORM 装饰器
2. Application Service 不直接导入框架
3. Port 输入/输出只能是 Domain 类型
4. Adapter 必须通过 Port 接口声明
5. 跨模块通信只能通过 Repository 或 EventPublisher

## 验收标准

- [ ] Domain 层不导入 SQLAlchemy、FastAPI、Celery
- [ ] 所有外部系统都有对应 Port
- [ ] Fake 实现通过契约测试
- [ ] 依赖检查脚本不报错
