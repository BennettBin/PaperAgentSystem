"""
API 模块初始化

导出所有 API 相关的 Schema 和事件定义。
"""

from .schemas import (
    CreateConversationRequest,
    ConversationResponse,
    ListConversationsResponse,
    SendMessageRequest,
    MessageResponse,
    ListMessagesResponse,
    CreateTaskRequest,
    TaskResponse,
    TaskStatusResponse,
    UploadFileRequest,
    FileResponse,
    ArtifactResponse,
    MemoryPreferenceRequest,
    MemorySegmentResponse,
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    PaginationParams,
)

from .events import (
    TaskEventType,
    BaseTaskEvent,
    TaskQueuedEvent,
    TaskStartedEvent,
    SkillSelectedEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
    EventSender,
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
