# ADR-0002: PostgreSQL + pgvector 作为主数据库

**状态**: 已接受  
**日期**: 2026-06-19

## 背景

系统需要存储：

- 结构化数据（用户、会话、消息、任务）
- 向量数据（文本块 Embedding）
- 全文搜索索引
- ACID 事务保证

## 决策

采用 PostgreSQL + pgvector 扩展：

- 主数据库：PostgreSQL 15+（兼容 pgvector 0.5+）
- ORM：SQLAlchemy 2（支持异步和类型提示）
- 迁移：Alembic
- 向量索引：pgvector HNSW（相似度搜索）
- 全文搜索：PostgreSQL FTS（BM25 近似）

## 替代方案

1. **MongoDB + Milvus**: 优点是原生向量支持。缺点是多个系统复杂度高。
2. **Elasticsearch + PostgreSQL**: 优点是搜索性能好。缺点是运维复杂。
3. **DuckDB**: 优点是轻量级。缺点是不支持分布式。

## 后果

### 优点

- ✅ 单一数据库简化运维
- ✅ 强 ACID 保证
- ✅ pgvector 性能满足 MVP 需求
- ✅ FTS 足以覆盖关键词搜索
- ✅ SQLAlchemy 生态成熟

### 缺点

- ⚠️ 大规模向量搜索可能需要优化（后续考虑 Qdrant）
- ⚠️ PostgreSQL 版本需求 15+

## 不变量

1. 所有持久化数据必须过 Repository
2. 向量操作必须通过 EmbeddingPort
3. 不允许在业务代码中直接执行 SQL
4. Workspace 隔离必须在查询层强制

## 验收标准

- [ ] PostgreSQL 15+ 启动成功
- [ ] pgvector 扩展注册
- [ ] Alembic migration 可在空库完整执行
- [ ] Repository 契约测试通过
- [ ] Workspace 隔离测试通过
