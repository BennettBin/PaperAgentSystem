from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import VECTOR  # type: ignore[import-untyped]
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class EmbeddingType(TypeDecorator[list[float]]):
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[no-untyped-def]
        if dialect.name == "postgresql":
            return dialect.type_descriptor(VECTOR(1024))
        return dialect.type_descriptor(JSON())


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class VersionedMixin:
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    @classmethod
    def __declare_last__(cls) -> None:
        cls.__mapper__.version_id_col = cls.__table__.c.version  # type: ignore[attr-defined]


class LifecycleMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserModel(Base, LifecycleMixin, VersionedMixin):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class WorkspaceModel(Base, LifecycleMixin, VersionedMixin):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ConversationModel(Base, LifecycleMixin, VersionedMixin):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (Index("ix_conversations_workspace_updated", "workspace_id", "updated_at"),)


class MessageModel(Base, LifecycleMixin, VersionedMixin):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    type: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )


class FileModel(Base, LifecycleMixin, VersionedMixin):
    __tablename__ = "files"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    filename: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(1024), unique=True)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    reference_count: Mapped[int] = mapped_column(Integer, default=1)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    __table_args__ = (
        UniqueConstraint("workspace_id", "checksum", name="uq_file_workspace_checksum"),
    )


class ConversationFileModel(Base, LifecycleMixin):
    __tablename__ = "conversation_files"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id"), index=True)
    uploaded_by_user: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class MessageFileModel(Base, LifecycleMixin):
    __tablename__ = "message_files"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"), index=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id"), index=True)
    __table_args__ = (
        UniqueConstraint("message_id", "file_id", name="uq_message_file"),
    )


class TaskModel(Base, LifecycleMixin, VersionedMixin):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    input_text: Mapped[str] = mapped_column(Text)
    result: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class SubAgentRunModel(Base, LifecycleMixin, VersionedMixin):
    __tablename__ = "subagent_runs"
    child_task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    parent_task_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    agent_name: Mapped[str] = mapped_column(String(200))
    file_id: Mapped[str] = mapped_column(String(64), index=True)
    depth: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), index=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)


class PlanModel(Base, LifecycleMixin, VersionedMixin):
    __tablename__ = "plans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class StepModel(Base, LifecycleMixin, VersionedMixin):
    __tablename__ = "steps"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    dependencies: Mapped[list[str]] = mapped_column(JSON, default=list)
    result: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class ToolCallModel(Base, LifecycleMixin):
    __tablename__ = "tool_calls"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    step_id: Mapped[str] = mapped_column(ForeignKey("steps.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(200), index=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class RequirementBriefModel(Base, LifecycleMixin):
    __tablename__ = "requirement_briefs"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(64))
    sufficient_info: Mapped[bool] = mapped_column(Boolean)
    missing_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    constraints: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    inferred_skill: Mapped[str | None] = mapped_column(String(200))
    confidence: Mapped[int] = mapped_column(Integer, default=0)


class ClarificationRoundModel(Base, LifecycleMixin):
    __tablename__ = "clarification_rounds"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    user_response: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClarificationQuestionModel(Base):
    __tablename__ = "clarification_questions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    round_id: Mapped[str] = mapped_column(ForeignKey("clarification_rounds.id"), index=True)
    type: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer)
    is_required: Mapped[bool] = mapped_column(Boolean)
    answer: Mapped[str | None] = mapped_column(Text)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QueueJobModel(Base, LifecycleMixin, VersionedMixin):
    __tablename__ = "queue_jobs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_type: Mapped[str] = mapped_column(String(64), index=True)
    queue_name: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ObjectBlobModel(Base, LifecycleMixin, VersionedMixin):
    __tablename__ = "object_blobs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    bucket: Mapped[str] = mapped_column(String(64), index=True)
    object_name: Mapped[str] = mapped_column(String(1024), unique=True)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    content_type: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    reference_count: Mapped[int] = mapped_column(Integer, default=1)
    upload_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "bucket", "checksum", name="uq_blob_workspace_bucket_checksum"
        ),
    )


class TaskEventModel(Base):
    __tablename__ = "task_events"
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(300))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    __table_args__ = (
        UniqueConstraint("task_id", "sequence", name="uq_task_event_sequence"),
        Index("ix_task_events_task_sequence", "task_id", "sequence"),
    )


class TraceSpanModel(Base):
    __tablename__ = "trace_spans"
    span_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    task_id: Mapped[str | None] = mapped_column(String(64), index=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(64), index=True)
    span_name: Mapped[str] = mapped_column(String(200), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    __table_args__ = (
        UniqueConstraint("trace_id", "sequence", name="uq_trace_span_sequence"),
        Index("ix_trace_spans_task_sequence", "task_id", "sequence"),
    )


class WorkspaceEntryModel(Base, LifecycleMixin, VersionedMixin):
    __tablename__ = "workspace_entries"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    relative_path: Mapped[str] = mapped_column(String(1024))
    kind: Mapped[str] = mapped_column(String(32))
    retention: Mapped[str] = mapped_column(String(32))
    content_type: Mapped[str] = mapped_column(String(255))
    object_key: Mapped[str | None] = mapped_column(String(1024))
    source_type: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str | None] = mapped_column(String(64))
    executable: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "task_id", "relative_path", name="uq_workspace_entry_path"
        ),
    )


class WorkspaceSearchModel(Base, LifecycleMixin, VersionedMixin):
    __tablename__ = "workspace_search"
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("workspace_entries.id"), primary_key=True
    )
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    filename: Mapped[str] = mapped_column(String(512), index=True)
    extracted_text: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(JSON, default=list)
    embedding_fingerprint: Mapped[str] = mapped_column(String(512), default="")
    source_type: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str | None] = mapped_column(String(64))


class ParsedDocumentModel(Base, LifecycleMixin, VersionedMixin):
    __tablename__ = "parsed_documents"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    file_id: Mapped[str] = mapped_column(String(64), index=True)
    checksum: Mapped[str] = mapped_column(String(64))
    parser_name: Mapped[str] = mapped_column(String(100))
    parser_version: Mapped[str] = mapped_column(String(32))
    page_count: Mapped[int] = mapped_column(Integer)
    quality_score: Mapped[int] = mapped_column(Integer)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "file_id",
            "checksum",
            name="uq_parsed_document_content",
        ),
    )


class DocumentSectionModel(Base, LifecycleMixin, VersionedMixin):
    __tablename__ = "document_sections"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    file_id: Mapped[str] = mapped_column(String(64), index=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("parsed_documents.id"), index=True
    )
    section_id: Mapped[str] = mapped_column(String(64))
    number: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(300))
    normalized_title: Mapped[str] = mapped_column(String(300))
    level: Mapped[int] = mapped_column(Integer)
    parent_section_id: Mapped[str | None] = mapped_column(String(64), index=True)
    section_path: Mapped[list[str]] = mapped_column(JSON, default=list)
    ordinal: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    heading_block_id: Mapped[str] = mapped_column(String(64))
    block_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    descendant_block_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        UniqueConstraint("document_id", "section_id", name="uq_document_section"),
        Index(
            "ix_document_sections_workspace_file_number",
            "workspace_id",
            "file_id",
            "number",
        ),
        Index(
            "ix_document_sections_workspace_file_title",
            "workspace_id",
            "file_id",
            "normalized_title",
        ),
        Index("ix_document_sections_document_ordinal", "document_id", "ordinal"),
    )


class DocumentChunkModel(Base, LifecycleMixin, VersionedMixin):
    __tablename__ = "document_chunks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    file_id: Mapped[str] = mapped_column(String(64), index=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("parsed_documents.id"), index=True
    )
    parent_chunk_id: Mapped[str | None] = mapped_column(String(64), index=True)
    level: Mapped[str] = mapped_column(String(16), index=True)
    section_id: Mapped[str | None] = mapped_column(String(64), index=True)
    section_number: Mapped[str | None] = mapped_column(String(32), index=True)
    section_title: Mapped[str | None] = mapped_column(String(300))
    section_path: Mapped[list[str]] = mapped_column(JSON, default=list)
    chunk_index_in_section: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    bbox_json: Mapped[list[float]] = mapped_column("bbox", JSON)
    source_block_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_spans: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    element_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    content_kind: Mapped[str] = mapped_column(String(32), default="body", index=True)
    contains_inferred_content: Mapped[bool] = mapped_column(Boolean, default=False)
    previous_chunk_id: Mapped[str | None] = mapped_column(String(64))
    next_chunk_id: Mapped[str | None] = mapped_column(String(64))
    embedding: Mapped[list[float]] = mapped_column(EmbeddingType())
    embedding_model: Mapped[str] = mapped_column(String(200))
    embedding_provider: Mapped[str] = mapped_column(String(32), default="legacy")
    embedding_version: Mapped[str] = mapped_column(String(200), default="unknown")
    embedding_dimension: Mapped[int] = mapped_column(Integer, default=1024)
    embedding_max_length: Mapped[int] = mapped_column(Integer, default=0)
    embedding_normalized: Mapped[bool] = mapped_column(Boolean, default=True)
    embedding_fingerprint: Mapped[str] = mapped_column(String(512), default="")
    embedding_status: Mapped[str] = mapped_column(String(32), default="ready")
    searchable_text: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        Index("ix_document_chunks_workspace_file", "workspace_id", "file_id"),
    )


class MemorySegmentModel(Base, LifecycleMixin, VersionedMixin):
    __tablename__ = "memory_segments"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    summary: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(JSON, default=list)
    embedding_fingerprint: Mapped[str] = mapped_column(String(512), default="")
    source_message_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationSummaryModel(Base, LifecycleMixin, VersionedMixin):
    __tablename__ = "conversation_summaries"
    conversation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    summary: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(JSON, default=list)
    embedding_fingerprint: Mapped[str] = mapped_column(String(512), default="")
    source_message_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MemoryPreferenceModel(Base, LifecycleMixin, VersionedMixin):
    __tablename__ = "memory_preferences"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    key: Mapped[str] = mapped_column(String(200))
    value: Mapped[Any] = mapped_column(JSON)
    category: Mapped[str] = mapped_column(String(64))
    explicitly_saved: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", "key", name="uq_memory_preference"),
    )


class ModelRuntimeConfigModel(Base, LifecycleMixin, VersionedMixin):
    __tablename__ = "model_runtime_configs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    small_model: Mapped[dict[str, Any]] = mapped_column(JSON)
    large_model: Mapped[dict[str, Any]] = mapped_column(JSON)


class ModelUsageModel(Base, LifecycleMixin):
    __tablename__ = "model_usage"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    model_role: Mapped[str] = mapped_column(String(16), index=True)
    model_name: Mapped[str] = mapped_column(String(200))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (
        Index("ix_model_usage_conversation_role", "conversation_id", "model_role"),
    )


class BlackboardEntryModel(Base, LifecycleMixin):
    __tablename__ = "blackboard_entries"
    entry_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    producer_role: Mapped[str] = mapped_column(String(32))
    entry_version: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column()
    payload_json: Mapped[dict[str, Any]] = mapped_column("payload", JSON)
    source_json: Mapped[dict[str, Any]] = mapped_column("source", JSON)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index("ix_blackboard_entries_workspace_task", "workspace_id", "task_id"),
    )


class BlackboardEventModel(Base):
    __tablename__ = "blackboard_events"
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    entry_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(16))
    entry_json: Mapped[dict[str, Any]] = mapped_column("entry", JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    __table_args__ = (
        Index("ix_blackboard_events_workspace_task_sequence", "workspace_id", "task_id", "sequence"),
    )
