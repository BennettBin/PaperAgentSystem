"""
API 模块初始化

导出所有 API 相关的 Schema 和事件定义。
"""

from .events import (
    BaseTaskEvent,
    EventSender,
    SkillSelectedEvent,
    TaskCompletedEvent,
    TaskEventType,
    TaskFailedEvent,
    TaskQueuedEvent,
    TaskStartedEvent,
)
from .schemas import (
    ArtifactResponse,
    ConversationResponse,
    CreateConversationRequest,
    CreateTaskRequest,
    ErrorDetail,
    ErrorResponse,
    FileResponse,
    HealthResponse,
    ListConversationsResponse,
    ListMessagesResponse,
    MemoryPreferenceRequest,
    MemorySegmentResponse,
    MessageResponse,
    PaginationParams,
    SendMessageRequest,
    TaskResponse,
    TaskStatusResponse,
    UploadFileRequest,
)

__all__ = [
    # Schemas
    "CreateConversationRequest",
    "ConversationResponse",
    "ListConversationsResponse",
    "SendMessageRequest",
    "MessageResponse",
    "ListMessagesResponse",
    "CreateTaskRequest",
    "TaskResponse",
    "TaskStatusResponse",
    "UploadFileRequest",
    "FileResponse",
    "ArtifactResponse",
    "MemoryPreferenceRequest",
    "MemorySegmentResponse",
    "ErrorDetail",
    "ErrorResponse",
    "HealthResponse",
    "PaginationParams",
    # Events
    "TaskEventType",
    "BaseTaskEvent",
    "TaskQueuedEvent",
    "TaskStartedEvent",
    "SkillSelectedEvent",
    "TaskCompletedEvent",
    "TaskFailedEvent",
    "EventSender",
]
