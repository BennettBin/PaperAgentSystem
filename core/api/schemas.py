"""
API 请求/响应 Schema

所有 API 端点的请求和响应格式。
"""

from dataclasses import dataclass, field
from typing import Optional, Any, List
from datetime import datetime
from pydantic import BaseModel, Field


# ==================== Conversation API ====================
class CreateConversationRequest(BaseModel):
    """创建对话请求"""

    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)


class ConversationResponse(BaseModel):
    """对话响应"""

    id: str
    title: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class ListConversationsResponse(BaseModel):
    """列出对话响应"""

    conversations: List[ConversationResponse]
    total: int
    skip: int
    limit: int


# ==================== Message API ====================
class SendMessageRequest(BaseModel):
    """发送消息请求"""

    content: str = Field(..., min_length=1, max_length=100000)
    message_type: str = Field("text", regex="^(text|file|artifact)$")
    file_ids: Optional[List[str]] = None
    metadata: Optional[dict] = None


class MessageResponse(BaseModel):
    """消息响应"""

    id: str
    role: str  # "user", "assistant"
    content: str
    type: str
    created_at: datetime
    metadata: Optional[dict]


class ListMessagesResponse(BaseModel):
    """列出消息响应"""

    messages: List[MessageResponse]
    total: int
    skip: int
    limit: int


# ==================== Task API ====================
class CreateTaskRequest(BaseModel):
    """创建任务请求"""

    conversation_id: str
    input_text: str = Field(..., min_length=1, max_length=100000)


class TaskResponse(BaseModel):
    """任务响应"""

    id: str
    conversation_id: str
    status: str
    input_text: str
    result: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime
    trace_id: Optional[str]


class TaskStatusResponse(BaseModel):
    """任务状态响应"""

    id: str
    status: str
    state_description: str
    progress_percent: int  # 0-100
    current_step: Optional[dict]
    metadata: Optional[dict]


# ==================== File API ====================
class UploadFileRequest(BaseModel):
    """上传文件请求

    实际上需要使用 multipart/form-data，此处仅作说明。
    """

    conversation_id: str


class FileResponse(BaseModel):
    """文件响应"""

    id: str
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime
    url: Optional[str]


# ==================== Artifact API ====================
class ArtifactResponse(BaseModel):
    """Artifact 响应"""

    id: str
    task_id: str
    artifact_type: str  # "text", "code", "table", "markdown", "pdf"
    content: Optional[str]
    url: Optional[str]
    created_at: datetime


# ==================== Memory API ====================
class MemoryPreferenceRequest(BaseModel):
    """记忆偏好请求"""

    key: str
    value: Any
    category: str  # "style", "domain_knowledge", "preferences"


class MemorySegmentResponse(BaseModel):
    """记忆段响应"""

    id: str
    conversation_id: str
    summary: str
    source_message_ids: List[str]
    created_at: datetime


# ==================== 错误响应 ====================
class ErrorDetail(BaseModel):
    """错误详情"""

    code: str
    message: str
    severity: str  # "info", "warning", "error", "critical"
    category: str  # "client", "retryable", "permission", "security", etc.
    details: Optional[dict]


class ErrorResponse(BaseModel):
    """错误响应"""

    error: ErrorDetail


# ==================== 健康检查 ====================
class HealthResponse(BaseModel):
    """健康检查响应"""

    status: str  # "healthy", "degraded", "unhealthy"
    timestamp: datetime
    version: str
    dependencies: dict = Field(default_factory=dict)


# ==================== 分页参数 ====================
class PaginationParams(BaseModel):
    """分页参数"""

    skip: int = Field(0, ge=0)
    limit: int = Field(50, ge=1, le=500)
