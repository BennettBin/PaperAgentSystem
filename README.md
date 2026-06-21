# PaperAgentSystem

一个全方位的学术论文 Agent 助手，能够处理与论文相关的所有任务——包括论文阅读、理解、分析、对比、撰写、改写和语言润色。

**项目状态**: 🚧 Alpha Development（阶段 B：完整代码骨架已完成）

## 📋 核心特性

- **单一对话入口**: 类似 ChatGPT 的简洁交互体验
- **论文智能分析**: 理解、总结、提取关键信息和证据
- **多文件对比**: 自动识别论文维度，生成对比表
- **学术写作辅助**: 章节撰写、段落改写、引用核验
- **完整记忆系统**: 短期会话记忆 + 长期跨会话检索
- **证据追踪**: 所有答案都附带原文页码和引用
- **本地部署**: Docker Compose 完整部署，支持私有数据

## 🛠️ 技术栈

| 层级 | 技术 |
|---|---|
| 前端 | Next.js + React + TypeScript + Tailwind CSS |
| API | FastAPI + Pydantic + SQLAlchemy 2 |
| 数据库 | PostgreSQL + pgvector |
| 缓存/队列 | Redis + Celery |
| 存储 | MinIO |
| Agent Runtime | 显式状态机 + Schema 验证 |
| LLM | Qwen 1.7B/4B（可插拔） |
| Embedding | BGE-M3 |

## 📚 核心文档

请按以下顺序阅读：

1. **[AGENTS.md](./AGENTS.md)** - 工程规则和架构原则（必读）
2. **[技术栈文档](./develop_guide/01-技术栈文档.md)** - 技术选型和依赖
3. **[产品架构文档](./develop_guide/02-产品架构文档.md)** - 产品功能和用户场景
4. **[执行计划文档](./develop_guide/03-执行计划文档.md)** - 开发方向和重点
5. **[详细开发计划](./develop_guide/DEVELOPMENT_PLAN.md)** - 工作包和验收标准

## 🚀 快速开始

### 环境要求

- Python 3.12+
- Node.js 18+
- Docker & Docker Compose（推荐）

### 本地开发

```bash
# 1. 克隆并进入项目
git clone <repo>
cd PaperAgentSystem

# 2. 复制环境配置
cp .env.example .env.local

# 3. 启动前端 Mock UI
npm install
npm run dev

# 4. 启动 Fake API
uvicorn apps.api.main:app --reload

# 5. 运行当前阶段检查
python -m pytest -q
npm test
npm run type-check
npm run build
```

### 项目结构

```
PaperAgentSystem/
├── apps/                    # 应用入口
│   ├── api/                # FastAPI 应用
│   └── worker/             # Celery worker
├── core/                    # 核心 Domain、Port、错误
├── agent_runtime/           # Agent 运行时和状态机
├── conversations/           # 会话和消息管理
├── tasks/                   # 任务和规划
├── memory/                  # 记忆系统
├── skills/                  # Skill 定义和加载
├── tools/                   # Tool 框架和实现
├── subagents/              # 子 Agent（paper_reader_agent 等）
├── documents/              # 文档解析
├── retrieval/              # RAG 和检索
├── writing/                # 论文生成和改写
├── verification/           # 结果验证和核验
├── models/                 # 模型注册和 Profile
├── storage/                # 存储 Adapter
├── observability/          # 可观测性和 Trace
├── security/               # 安全加固
├── evaluation/             # 评测框架
├── training/               # 训练脚本
├── tests/                  # 测试套件
├── infra/                  # Docker Compose 和部署
├── scripts/                # 开发脚本
├── docs/                   # 文档和 ADR
└── develop_guide/          # 开发指引
```

## 📦 开发命令（待实现）

```bash
# 安装开发依赖
make/bootstrap

# 本地开发（启动 API + Worker）
make/dev

# 代码检查
make/format              # 自动格式化
make/lint                # 静态检查
make/typecheck           # 类型检查

# 测试
make/test-unit           # 单元测试
make/test-contract       # 契约测试
make/test-integration    # 集成测试
make/test-e2e            # 端到端测试
make/test-security       # 安全测试

# 评测
make/eval                # 自动评测
make/check               # 本地完整检查
```

## 🔄 开发阶段

- **A: 项目治理和架构契约** ✅ 完成
  - A01: 清理入口并建立项目元数据 ✅
  - A02: 建立 ADR 和模块依赖规则 ✅
  - A03: 定义全局 ID、枚举和错误模型 ✅
  - A04: 定义核心 Domain 实体 ✅
  - A05: 定义所有 Port ✅
  - A06: 定义 Agent Schema 和状态机 ✅
  - A07: 定义 REST API 和 SSE 契约 ✅
- **B: 完整代码骨架** ✅ 完成
  - FastAPI/Worker/FakeQueue 与统一错误、健康检查、关联 ID
  - 可构建的 Next.js Mock UI 与主要用户操作入口
  - 全 Port Fake 组合根、故障注入和 Workspace 隔离契约
  - Port-only Agent Runtime Stub 与预算/取消/持久化门禁
  - 11 个能力型 Skill Manifest 和 `paper_reader_agent`
  - 九个 Fake 端到端控制流场景
- **C: 基础设施 Adapter** ✅ 完成
  - PostgreSQL/pgvector、SQLAlchemy 2、Alembic、Repository 和 Unit of Work
  - Redis/Celery 四类队列、数据库任务真值、取消、锁、重试、死信与崩溃恢复
  - MinIO Workspace 隔离、SHA-256 去重、MIME/签名校验、引用计数与流式上传
  - 数据库 TaskEvent、Redis 通知、SSE sequence、断线续传和最终事件关闭
- **D: 会话、Workspace 和 Memory** ✅ 完成
  - 历史会话与消息 CRUD、搜索分页、附件和删除级联
  - ConversationWorkspace/TaskWorkspace、Manifest、Promote、恢复和路径安全
  - Workspace 文本/摘要/Embedding 分层检索与完整来源追踪
  - 短期 Memory 摘要定位、原消息回读、删除失效和重建
  - 长期 ConversationSummary、显式 Preference、跨会话/历史文件检索和遗忘
- **E: 真实 Agent Runtime** ✅ 完成
  - 逻辑 Model Profile/Version Manifest、OpenAI 兼容客户端、fallback 和版本 Trace
  - 检索优先的 Requirement Clarifier、两轮澄清和原 Task 恢复
  - Top-3 Skill 选择、正文按需加载、结构化 DAG Plan 和最多两次 Replan
  - 有预算、取消、超时、幂等、逐步持久化和子 Agent 门禁的 Executor
  - 来源可追踪且受 Profile Token 预算约束的 ContextBuilder
  - Schema、Claim-Evidence、数字、引用和不可变项规则 Verifier
- **F: Tool、Skill 和子 Agent** ✅ 完成
  - Pydantic Tool Runtime、Skill 白名单、权限、确认、超时重试、幂等和 Trace
  - Workspace 六项 Tool，强制 Workspace/Task 范围、对象存储和 Promote 审计
  - 11 个能力型 Skill 的 Manifest、说明、Schema、示例、追问/终止/验收规则
  - 单文件 `paper_reader_agent`、完整 Paper Card、证据、缺失字段和独立 Profile/预算
  - 父子 Task 持久化、Celery Group、并发限制、部分失败汇总和取消传播
- **G: 论文解析和 RAG** ✅ 完成
  - PyMuPDF 页码、文本、bbox、页眉页脚、双栏阅读顺序、章节与质量评分
  - 扫描检测及 PaddleOCR/Tesseract 可选 Adapter、主备回退、置信度和低质量 Trace
  - 可追溯父子 Chunk、Section path、页面/bbox/邻接、幂等 Embedding 和删除失效
  - PostgreSQL pgvector HNSW、FTS GIN、Top-30 双路召回、RRF 和 Top-8 Reranker
  - 程序分配 Citation ID、PDF 页面定位、Claim-Evidence 检查和证据不足拒答
  - `parse_document`、`search_document`、`get_document_section` Tool Runtime 集成
- **H: 论文领域功能** (待启动)
- **I: 安全、观测和交付** (待启动)
- **J: 模型训练** (待启动)

详见 [DEVELOPMENT_PLAN.md](./develop_guide/DEVELOPMENT_PLAN.md)

## 🧪 测试

项目遵循自顶而下的测试策略：

- **Contract 测试**: Port 和 Fake/Real Adapter 一致性
- **Unit 测试**: 纯逻辑和状态机
- **Integration 测试**: 数据库、缓存、存储交互
- **E2E 测试**: 用户场景和任务完整流程
- **Security 测试**: 越权、路径穿越、注入

## 🔐 隐私和安全

- ✅ 所有用户数据隔离在 Workspace 层
- ✅ 不提交模型权重、用户论文、密钥和真实私有数据
- ✅ 支持本地部署和私有数据处理
- ⚠️ 首版不支持端到端加密（待实现）

## 📖 贡献指南

参考 [AGENTS.md](./AGENTS.md) 的工程规则。核心原则：

1. 先写测试和契约，再实现
2. Domain 层不依赖框架
3. 所有外部系统通过 Port 访问
4. 修改必须同步文档
5. 不覆盖用户未提交的修改

## 📝 许可证

MIT

---

**最后更新**: 2026-06-20
**当前维护者**: PaperAgent Team
