"""Product-facing conversation, upload and paper-QA application services."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from core.errors import ErrorCode, ProjectError
from core.ports.llm_client import EmbeddingClient, LLMClient, RerankerClient
from core.ports.storage import ObjectStore, TaskQueue
from document_processing.pipeline import BasicPDFPipeline
from infrastructure.postgres.models import (
    ConversationFileModel,
    ConversationModel,
    FileModel,
    MessageFileModel,
    MessageModel,
    ParsedDocumentModel,
    QueueJobModel,
)
from infrastructure.sse.service import TaskEventStore
from rag.indexing import DocumentIndexer
from rag.retrieval import HybridRetriever, RetrievalHit

LOCAL_USER_ID = "local-user"
LOCAL_WORKSPACE_ID = "local-workspace"


class PaperAgentApplicationPort(Protocol):
    async def create_conversation(self, title: str = "新对话") -> dict[str, Any]: ...

    async def list_conversations(self, query: str = "") -> list[dict[str, Any]]: ...

    async def get_conversation(self, conversation_id: str) -> dict[str, Any]: ...

    async def upload_file(
        self,
        conversation_id: str,
        filename: str,
        content_type: str,
        data: bytes,
    ) -> dict[str, Any]: ...

    async def list_files(self) -> list[dict[str, Any]]: ...

    async def submit_message(
        self, conversation_id: str, content: str, file_ids: list[str]
    ) -> dict[str, Any]: ...

    async def get_task(self, task_id: str) -> dict[str, Any]: ...


class PaperAgentApplication:
    """Short HTTP operations. Long parsing and generation are queued for the worker."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        object_store: ObjectStore,
        task_queue: TaskQueue,
    ) -> None:
        self._sessions = sessions
        self._objects = object_store
        self._queue = task_queue

    async def create_conversation(self, title: str = "新对话") -> dict[str, Any]:
        model = ConversationModel(
            id=uuid4().hex,
            workspace_id=LOCAL_WORKSPACE_ID,
            user_id=LOCAL_USER_ID,
            title=(title.strip() or "新对话")[:200],
        )
        with self._sessions() as session:
            session.add(model)
            session.commit()
            session.refresh(model)
            return _conversation_dict(model, 0)

    async def list_conversations(self, query: str = "") -> list[dict[str, Any]]:
        with self._sessions() as session:
            statement = select(ConversationModel).where(
                ConversationModel.workspace_id == LOCAL_WORKSPACE_ID,
                ConversationModel.deleted_at.is_(None),
            )
            if query.strip():
                statement = statement.where(
                    func.lower(ConversationModel.title).like(
                        f"%{query.strip().casefold()}%"
                    )
                )
            conversations = session.scalars(
                statement.order_by(
                    ConversationModel.updated_at.desc(), ConversationModel.id.desc()
                )
            ).all()
            count_rows = session.execute(
                    select(
                        MessageModel.conversation_id,
                        func.count(MessageModel.id),
                    )
                    .where(
                        MessageModel.workspace_id == LOCAL_WORKSPACE_ID,
                        MessageModel.deleted_at.is_(None),
                    )
                    .group_by(MessageModel.conversation_id)
                ).all()
            counts: dict[str, int] = {
                str(conversation_id): int(count)
                for conversation_id, count in count_rows
            }
            return [
                _conversation_dict(item, int(counts.get(item.id, 0)))
                for item in conversations
            ]

    async def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        with self._sessions() as session:
            conversation = _conversation(session, conversation_id)
            messages = session.scalars(
                select(MessageModel)
                .where(
                    MessageModel.workspace_id == LOCAL_WORKSPACE_ID,
                    MessageModel.conversation_id == conversation_id,
                    MessageModel.deleted_at.is_(None),
                )
                .order_by(MessageModel.created_at, MessageModel.id)
            ).all()
            files = session.scalars(
                select(FileModel)
                .join(
                    ConversationFileModel,
                    ConversationFileModel.file_id == FileModel.id,
                )
                .where(
                    ConversationFileModel.workspace_id == LOCAL_WORKSPACE_ID,
                    ConversationFileModel.conversation_id == conversation_id,
                    ConversationFileModel.deleted_at.is_(None),
                    FileModel.deleted_at.is_(None),
                    FileModel.is_deleted.is_(False),
                )
                .order_by(FileModel.created_at)
            ).all()
            return {
                **_conversation_dict(conversation, len(messages)),
                "messages": [_message_dict(item) for item in messages],
                "files": [_file_dict(item) for item in files],
            }

    async def upload_file(
        self,
        conversation_id: str,
        filename: str,
        content_type: str,
        data: bytes,
    ) -> dict[str, Any]:
        if not data:
            raise ProjectError(ErrorCode.INVALID_ARGUMENT, "上传文件不能为空")
        if content_type != "application/pdf" and not filename.casefold().endswith(".pdf"):
            raise ProjectError(
                ErrorCode.UNSAFE_FILE_TYPE,
                "当前产品问答链路仅支持 PDF 论文",
            )
        with self._sessions() as session:
            _conversation(session, conversation_id)
        checksum = hashlib.sha256(data).hexdigest()
        object_key = await self._objects.upload(
            f"uploads/{uuid4().hex}-{filename}",
            data,
            "application/pdf",
        )
        with self._sessions() as session:
            existing = session.scalar(
                select(FileModel).where(
                    FileModel.workspace_id == LOCAL_WORKSPACE_ID,
                    FileModel.checksum == checksum,
                    FileModel.deleted_at.is_(None),
                    FileModel.is_deleted.is_(False),
                )
            )
            file_model = existing or FileModel(
                id=uuid4().hex,
                workspace_id=LOCAL_WORKSPACE_ID,
                filename=filename,
                content_type="application/pdf",
                size_bytes=len(data),
                storage_path=object_key,
                checksum=checksum,
                metadata_json={"parse_status": "queued"},
            )
            if existing is None:
                session.add(file_model)
            link = session.scalar(
                select(ConversationFileModel).where(
                    ConversationFileModel.conversation_id == conversation_id,
                    ConversationFileModel.file_id == file_model.id,
                    ConversationFileModel.deleted_at.is_(None),
                )
            )
            if link is None:
                session.add(
                    ConversationFileModel(
                        id=uuid4().hex,
                        workspace_id=LOCAL_WORKSPACE_ID,
                        conversation_id=conversation_id,
                        file_id=file_model.id,
                        uploaded_by_user=True,
                    )
                )
            session.commit()
            file_id = file_model.id
        task_id = await self._queue.enqueue(
            "document_parse",
            {"file_id": file_id},
            f"parse:{LOCAL_WORKSPACE_ID}:{file_id}:{checksum}",
        )
        result = _file_dict(file_model)
        result["task_id"] = task_id
        return result

    async def list_files(self) -> list[dict[str, Any]]:
        with self._sessions() as session:
            files = session.scalars(
                select(FileModel)
                .where(
                    FileModel.workspace_id == LOCAL_WORKSPACE_ID,
                    FileModel.deleted_at.is_(None),
                    FileModel.is_deleted.is_(False),
                )
                .order_by(FileModel.created_at.desc(), FileModel.id.desc())
            ).all()
            return [_file_dict(item) for item in files]

    async def submit_message(
        self, conversation_id: str, content: str, file_ids: list[str]
    ) -> dict[str, Any]:
        clean = content.strip()
        if not clean:
            raise ProjectError(ErrorCode.INVALID_ARGUMENT, "消息不能为空")
        with self._sessions() as session:
            conversation = _conversation(session, conversation_id)
            message = MessageModel(
                id=uuid4().hex,
                workspace_id=LOCAL_WORKSPACE_ID,
                conversation_id=conversation_id,
                role="user",
                type="text",
                content=clean,
                metadata_json={},
            )
            session.add(message)
            for file_id in file_ids:
                file_model = session.scalar(
                    select(FileModel).where(
                        FileModel.id == file_id,
                        FileModel.workspace_id == LOCAL_WORKSPACE_ID,
                        FileModel.deleted_at.is_(None),
                        FileModel.is_deleted.is_(False),
                    )
                )
                if file_model is None:
                    raise ProjectError(
                        ErrorCode.NOT_FOUND, f"找不到上传文件：{file_id}"
                    )
                session.add(
                    MessageFileModel(
                        id=uuid4().hex,
                        workspace_id=LOCAL_WORKSPACE_ID,
                        message_id=message.id,
                        file_id=file_id,
                    )
                )
            if conversation.title == "新对话":
                conversation.title = clean[:40]
            conversation.updated_at = datetime.now(UTC)
            session.commit()
        task_id = await self._queue.enqueue(
            "main_agent",
            {
                "conversation_id": conversation_id,
                "message_id": message.id,
                "question": clean,
                "file_ids": file_ids,
            },
            f"message:{message.id}",
        )
        return {
            "message": _message_dict(message),
            "task_id": task_id,
            "status": "queued",
        }

    async def get_task(self, task_id: str) -> dict[str, Any]:
        with self._sessions() as session:
            task = session.get(QueueJobModel, task_id)
            if task is None:
                raise ProjectError(ErrorCode.NOT_FOUND, "任务不存在")
            return {
                "task_id": task.id,
                "status": task.status,
                "result": task.result,
                "error": task.error,
            }


class PaperAgentProcessor:
    """Worker-side PDF parsing, retrieval and evidence-grounded model invocation."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        object_store: ObjectStore,
        embeddings: EmbeddingClient,
        reranker: RerankerClient,
        llm: LLMClient,
        events: TaskEventStore | None = None,
    ) -> None:
        self._sessions = sessions
        self._objects = object_store
        self._parser = BasicPDFPipeline()
        self._indexer = DocumentIndexer(
            sessions, embeddings, embedding_model="development-embedding"
        )
        self._retriever = HybridRetriever(sessions, embeddings, reranker)
        self._llm = llm
        self._events = events

    async def parse(self, payload: dict[str, Any]) -> dict[str, Any]:
        file_id = str(payload["file_id"])
        task_id = str(payload.get("_task_id", ""))
        self._event(task_id, "step_started", "开始解析 PDF", {"file_id": file_id})
        try:
            with self._sessions() as session:
                file_model = _file(session, file_id)
                storage_path = file_model.storage_path
                filename = file_model.filename
            data = await self._objects.download(storage_path)
            document = await self._parser.parse(data, filename, trace_id=task_id)
            chunks = await self._indexer.index(
                LOCAL_WORKSPACE_ID, file_id, data, document
            )
            with self._sessions() as session:
                file_model = _file(session, file_id)
                file_model.metadata_json = {
                    **(file_model.metadata_json or {}),
                    "parse_status": "parsed",
                    "page_count": document.page_count,
                    "quality_score": document.quality.score,
                    "chunk_count": len(chunks),
                }
                session.commit()
            self._event(
                task_id,
                "tool_completed",
                "PDF 解析和索引完成",
                {"file_id": file_id, "chunk_count": len(chunks)},
            )
            return {"status": "parsed", "file_id": file_id, "chunks": len(chunks)}
        except Exception:
            with self._sessions() as session:
                failed_file = session.get(FileModel, file_id)
                if failed_file is not None:
                    failed_file.metadata_json = {
                        **(failed_file.metadata_json or {}),
                        "parse_status": "failed",
                    }
                    session.commit()
            raise

    async def answer(self, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = str(payload.get("_task_id", ""))
        conversation_id = str(payload["conversation_id"])
        question = str(payload["question"])
        file_ids = [str(value) for value in payload.get("file_ids", [])]
        self._event(task_id, "task_started", "任务开始", {})
        if not file_ids:
            with self._sessions() as session:
                file_ids = list(
                    session.scalars(
                        select(ConversationFileModel.file_id).where(
                            ConversationFileModel.workspace_id == LOCAL_WORKSPACE_ID,
                            ConversationFileModel.conversation_id == conversation_id,
                            ConversationFileModel.deleted_at.is_(None),
                        )
                    )
                )
        if not file_ids:
            raise ProjectError(
                ErrorCode.INVALID_ARGUMENT, "请先上传或选择至少一篇 PDF 论文"
            )
        for file_id in file_ids:
            with self._sessions() as session:
                indexed = session.scalar(
                    select(ParsedDocumentModel.id).where(
                        ParsedDocumentModel.workspace_id == LOCAL_WORKSPACE_ID,
                        ParsedDocumentModel.file_id == file_id,
                    )
                )
            if indexed is None:
                await self.parse({"_task_id": task_id, "file_id": file_id})
        self._event(task_id, "step_started", "检索论文证据", {})
        hits = await self._retriever.search(
            question,
            workspace_id=LOCAL_WORKSPACE_ID,
            file_ids=set(file_ids),
            limit=8,
        )
        if not hits:
            raise ProjectError(
                ErrorCode.INSUFFICIENT_EVIDENCE,
                "论文中没有检索到相关证据",
            )
        prompt = _answer_prompt(question, hits)
        self._event(
            task_id,
            "step_started",
            "调用论文问答模型",
            {"evidence_count": len(hits)},
        )
        answer = await self._llm.generate(
            prompt,
            system_prompt=(
                "你是论文问答助手。只能依据提供的证据回答；不得补造。"
                "每个事实后使用证据标签 [E1]、[E2]。证据不足时明确说明。"
            ),
            max_tokens=2048,
            temperature=0.1,
        )
        with self._sessions() as session:
            message = MessageModel(
                id=uuid4().hex,
                workspace_id=LOCAL_WORKSPACE_ID,
                conversation_id=conversation_id,
                role="assistant",
                type="text",
                content=answer,
                metadata_json={
                    "task_id": task_id,
                    "evidence": [_hit_dict(index, hit) for index, hit in enumerate(hits, 1)],
                },
            )
            session.add(message)
            conversation = _conversation(session, conversation_id)
            conversation.updated_at = datetime.now(UTC)
            session.commit()
        self._event(
            task_id,
            "task_completed",
            "回答生成完成",
            {"message_id": message.id},
        )
        return {
            "status": "completed",
            "message_id": message.id,
            "answer": answer,
        }

    def _event(
        self, task_id: str, event_type: str, title: str, data: dict[str, Any]
    ) -> None:
        if self._events is not None and task_id:
            self._events.append(task_id, event_type, title, data)


def _conversation(session: Session, conversation_id: str) -> ConversationModel:
    model = session.scalar(
        select(ConversationModel).where(
            ConversationModel.id == conversation_id,
            ConversationModel.workspace_id == LOCAL_WORKSPACE_ID,
            ConversationModel.deleted_at.is_(None),
        )
    )
    if model is None:
        raise ProjectError(ErrorCode.NOT_FOUND, "会话不存在")
    return model


def _file(session: Session, file_id: str) -> FileModel:
    model = session.scalar(
        select(FileModel).where(
            FileModel.id == file_id,
            FileModel.workspace_id == LOCAL_WORKSPACE_ID,
            FileModel.deleted_at.is_(None),
            FileModel.is_deleted.is_(False),
        )
    )
    if model is None:
        raise ProjectError(ErrorCode.NOT_FOUND, "文件不存在")
    return model


def _conversation_dict(model: ConversationModel, message_count: int) -> dict[str, Any]:
    return {
        "id": model.id,
        "title": model.title,
        "created_at": model.created_at.isoformat(),
        "updated_at": model.updated_at.isoformat(),
        "message_count": message_count,
    }


def _message_dict(model: MessageModel) -> dict[str, Any]:
    return {
        "id": model.id,
        "role": model.role,
        "content": model.content,
        "created_at": model.created_at.isoformat(),
        "metadata": model.metadata_json or {},
    }


def _file_dict(model: FileModel) -> dict[str, Any]:
    return {
        "id": model.id,
        "name": model.filename,
        "content_type": model.content_type,
        "size_bytes": model.size_bytes,
        "created_at": model.created_at.isoformat(),
        "parse_status": (model.metadata_json or {}).get("parse_status", "queued"),
    }


def _answer_prompt(question: str, hits: list[RetrievalHit]) -> str:
    evidence = "\n\n".join(
        f"[E{index}] 文件 {hit.file_id}，第 {hit.page_start} 页，"
        f"章节 {' / '.join(hit.section_path)}：\n{hit.text}"
        for index, hit in enumerate(hits, 1)
    )
    return f"用户问题：{question}\n\n可用论文证据：\n{evidence}\n\n请生成中文回答。"


def _hit_dict(index: int, hit: RetrievalHit) -> dict[str, Any]:
    return {
        "id": f"E{index}",
        "file_id": hit.file_id,
        "page": hit.page_start,
        "section": list(hit.section_path),
        "quote": hit.text[:800],
        "bbox": list(hit.bbox),
    }
