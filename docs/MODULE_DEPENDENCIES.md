# 模块依赖规则

遵循 ADR-0004: Port-Adapter 边界

## 依赖方向

```
                用户界面 (Next.js/React/TypeScript)
                    ↓
              Route (FastAPI)
                    ↓
        Application Service 应用服务
                    ↓
        ┌───────────┴─────────────┐
        ↓                         ↓
   Domain Entity            Port (接口)
   + Domain Service         + Schema
                                 ↓
                        ┌────────┴──────────┐
                        ↓                   ↓
                  Fake Adapter      Real Adapter
                  (测试使用)      (生产使用)
                        ↓                   ↓
                   (内存)        (PostgreSQL/Redis/MinIO/Celery)
```

## 禁止

- ❌ Domain 层导入 `fastapi`、`sqlalchemy`、`celery`、`redis`、`minio`、`vllm`、`transformers`
- ❌ 跨模块直接导入业务代码（需通过 Port）
- ❌ Application Service 直接使用框架特定类型（如 SQLAlchemy Model）
- ❌ Route 包含业务逻辑（只做参数转换和权限检查）
- ❌ Worker Handler 包含核心业务逻辑（只做参数反序列化和结果序列化）

## 必须

- ✅ 所有外部系统访问通过 Port
- ✅ Domain Entity 使用强类型 ID（UserId、ConversationId 等）
- ✅ 错误使用统一 ProjectError + ErrorCode
- ✅ 时间字段统一使用 UTC
- ✅ 配置通过环境变量或 Settings 注入

## 分层示例

### 1. Domain 层 (core/domain/)

```python
# ✅ 允许
from core.domain.user import User, UserId
from core.domain.conversation import Conversation, ConversationId
from core.ports.repositories import ConversationRepository

class CreateConversationService:
    def __init__(self, repo: ConversationRepository):
        self.repo = repo
    
    async def execute(self, user_id: UserId, title: str) -> Conversation:
        conv = Conversation.create(user_id=user_id, title=title)
        await self.repo.save(conv)
        return conv

# ❌ 禁止
from sqlalchemy import Column, String  # 框架特定
from fastapi import HTTPException  # 不应该在 Domain 使用
import os  # 直接访问环境，应该通过 Settings 注入
```

### 2. Application 层 (apps/api/services/)

```python
# ✅ 允许
from core.domain.conversation import Conversation, ConversationId
from core.ports.repositories import ConversationRepository
from core.errors import ProjectError, ErrorCode

class ConversationApplicationService:
    def __init__(self, repo: ConversationRepository):
        self.repo = repo
    
    async def create(self, user_id: str, title: str) -> dict:
        try:
            conv = Conversation.create(
                user_id=UserId(user_id),
                title=title
            )
            await self.repo.save(conv)
            return {"id": str(conv.id), "title": conv.title}
        except ValueError as e:
            raise ProjectError(ErrorCode.INVALID_ARGUMENT, str(e))

# ❌ 禁止
from sqlalchemy.orm import Session  # 直接使用 ORM
from apps.api.models import ConversationModel  # 直接使用 ORM Model
```

### 3. Infrastructure 层 (infrastructure/repositories/)

```python
# ✅ 允许
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from core.domain.conversation import Conversation, ConversationId
from core.ports.repositories import ConversationRepository
from infrastructure.models import ConversationModel

class PostgresConversationRepository(ConversationRepository):
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def save(self, conv: Conversation) -> None:
        model = ConversationModel(
            id=str(conv.id),
            user_id=str(conv.user_id),
            title=conv.title
        )
        self.session.add(model)
        await self.session.flush()
    
    async def find_by_id(self, conv_id: ConversationId) -> Conversation | None:
        stmt = select(ConversationModel).where(
            ConversationModel.id == str(conv_id)
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return model.to_domain() if model else None

# ❌ 禁止
from core.domain.services import CreateConversationService  # 不应该导入 Domain Service 的服务实现
```

### 4. Route 层 (apps/api/routes/)

```python
# ✅ 允许
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from apps.api.services import ConversationApplicationService
from core.errors import ProjectError, ErrorCode

class CreateConversationRequest(BaseModel):
    title: str

class ConversationResponse(BaseModel):
    id: str
    title: str

@router.post("/conversations", response_model=ConversationResponse)
async def create_conversation(
    req: CreateConversationRequest,
    service: ConversationApplicationService = Depends(get_service),
    user_id: str = Depends(get_current_user_id)
) -> ConversationResponse:
    try:
        result = await service.create(user_id, req.title)
        return ConversationResponse(**result)
    except ProjectError as e:
        raise HTTPException(status_code=e.http_status_code, detail=e.message)

# ❌ 禁止
from core.domain.conversation import Conversation  # 直接返回 Domain 实体
async def create_conversation(...) -> Conversation:  # 应该返回 Response Model
    ...
```

## 检查命令（待实现）

```bash
# 检查 Domain 层是否有禁止的导入
python scripts/check_dependencies.py --layer domain

# 检查跨模块直接耦合
python scripts/check_dependencies.py --check circular

# 生成依赖图
python scripts/check_dependencies.py --graph deps.dot
```

## 验收标准

- [ ] 无依赖循环
- [ ] Domain 不导入框架库
- [ ] Application Service 不直接导入 ORM Model
- [ ] Route 不包含业务逻辑
- [ ] 所有外部系统访问通过 Port
