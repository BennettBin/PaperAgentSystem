from typing import Any, Literal, cast

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from apps.api.dependencies import ApiContainer
from apps.api.product_service import PaperAgentApplicationPort
from core.errors import ErrorCode, ProjectError
from models.runtime import ModelRuntimeService

router = APIRouter(prefix="/api/v1")


class TaskCreateRequest(BaseModel):
    task_type: str = "main_agent"
    payload: dict = Field(default_factory=dict)
    idempotency_key: str


class ConversationCreateRequest(BaseModel):
    title: str = "新对话"


class MessageCreateRequest(BaseModel):
    content: str
    file_ids: list[str] = Field(default_factory=list)


class ModelSelectRequest(BaseModel):
    role: Literal["small", "large"]
    model_id: str


class ModelCheckRequest(BaseModel):
    role: Literal["small", "large"]
    model_name: str


def _paper_agent(request: Request) -> PaperAgentApplicationPort:
    container = cast(ApiContainer, request.app.state.container)
    service = container.paper_agent
    if service is None:
        raise ProjectError(
            ErrorCode.UNAVAILABLE,
            "产品 API 需要 ADAPTER_MODE=real 以及 PostgreSQL/Redis/MinIO",
        )
    return service


def _model_runtime(request: Request) -> ModelRuntimeService:
    container = cast(ApiContainer, request.app.state.container)
    if container.model_runtime is None:
        raise ProjectError(ErrorCode.UNAVAILABLE, "模型运行时不可用")
    return container.model_runtime


@router.post("/conversations")
async def create_conversation(
    request: Request, body: ConversationCreateRequest
) -> dict[str, Any]:
    return await _paper_agent(request).create_conversation(body.title)


@router.get("/conversations")
async def list_conversations(request: Request, q: str = "") -> dict[str, Any]:
    return {"items": await _paper_agent(request).list_conversations(q)}


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    request: Request, conversation_id: str
) -> dict[str, Any]:
    return await _paper_agent(request).get_conversation(conversation_id)


@router.post("/conversations/{conversation_id}/files")
async def upload_conversation_file(
    request: Request,
    conversation_id: str,
) -> dict[str, Any]:
    form = await request.form()
    file = form.get("file")
    if file is None or not hasattr(file, "read"):
        raise ProjectError(ErrorCode.INVALID_ARGUMENT, "缺少上传文件")
    upload = cast(Any, file)
    data = await upload.read()
    return await _paper_agent(request).upload_file(
        conversation_id,
        upload.filename or "paper.pdf",
        upload.content_type or "application/octet-stream",
        data,
    )


@router.get("/files")
async def list_files(request: Request) -> dict[str, Any]:
    return {"items": await _paper_agent(request).list_files()}


@router.post("/conversations/{conversation_id}/messages")
async def create_message(
    request: Request,
    conversation_id: str,
    body: MessageCreateRequest,
) -> dict[str, Any]:
    return await _paper_agent(request).submit_message(
        conversation_id, body.content, body.file_ids
    )


@router.get("/product-tasks/{task_id}")
async def get_product_task(request: Request, task_id: str) -> dict[str, Any]:
    return await _paper_agent(request).get_task(task_id)


@router.get("/model-settings")
async def get_model_settings(request: Request) -> dict[str, Any]:
    return await _model_runtime(request).get_settings()


@router.post("/model-settings/select")
async def select_model(
    request: Request, body: ModelSelectRequest
) -> dict[str, Any]:
    return await _model_runtime(request).select(body.role, body.model_id)


@router.post("/model-settings/check")
async def check_model(
    request: Request, body: ModelCheckRequest
) -> dict[str, Any]:
    return await _model_runtime(request).check_base_model(body.role, body.model_name)


@router.post("/model-settings/download")
async def download_model(
    request: Request, body: ModelCheckRequest
) -> dict[str, Any]:
    return await _model_runtime(request).download_and_select(
        body.role, body.model_name
    )


@router.post("/tasks")
async def create_task(request: Request, body: TaskCreateRequest) -> dict:
    container: ApiContainer = request.app.state.container
    task_id = await container.task_queue.enqueue(
        task_type=body.task_type,
        payload=body.payload,
        idempotency_key=body.idempotency_key,
    )
    return {"task_id": task_id, "status": "pending"}


@router.post("/demo/{scenario}")
async def run_fake_scenario(request: Request, scenario: str) -> dict:
    container: ApiContainer = request.app.state.container
    return await container.scenario_runner.run(scenario)


@router.get("/tasks/{task_id}/events")
async def stream_task_events(
    request: Request,
    task_id: str,
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
) -> StreamingResponse:
    container: ApiContainer = request.app.state.container
    if container.event_stream is None:
        raise ProjectError(ErrorCode.UNAVAILABLE, "Task event stream is unavailable")
    try:
        last_sequence = int(last_event_id or "0")
    except ValueError as exc:
        raise ProjectError(ErrorCode.INVALID_ARGUMENT, "Invalid Last-Event-ID") from exc
    return StreamingResponse(
        container.event_stream.sse(task_id, last_sequence),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
