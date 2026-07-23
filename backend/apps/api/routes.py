import hmac
from typing import Any, Literal, cast

from fastapi import APIRouter, Header, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from backend.apps.api.dependencies import ApiContainer
from backend.apps.api.product_service import PaperAgentApplicationPort
from backend.core.errors import ErrorCode, ProjectError
from backend.models.runtime import ModelRuntimeService
from evaluation.dashboard import DashboardFilters, OfflineEvaluationDashboard
from evaluation.hitl import HumanReview, ReviewDecision, StagingRegistry

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


class RetrievalPreviewRequest(BaseModel):
    conversation_id: str
    question: str
    file_ids: list[str] = Field(default_factory=list)


class HumanReviewRequest(BaseModel):
    reviewer_id: str = Field(min_length=1)
    decision: ReviewDecision
    rationale: str = Field(min_length=1)


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


def _hitl_registry(request: Request, admin_token: str | None) -> StagingRegistry:
    expected = request.app.state.settings.admin_api_token
    if not expected:
        raise ProjectError(ErrorCode.UNAVAILABLE, "HITL admin interface is disabled")
    if not admin_token or not hmac.compare_digest(admin_token, expected):
        raise ProjectError(ErrorCode.UNAUTHENTICATED, "Invalid admin credential")
    container = cast(ApiContainer, request.app.state.container)
    if container.hitl_registry is None:
        raise ProjectError(ErrorCode.UNAVAILABLE, "HITL staging registry is unavailable")
    return container.hitl_registry


def _evaluation_dashboard(
    request: Request, admin_token: str | None
) -> OfflineEvaluationDashboard:
    expected = request.app.state.settings.admin_api_token
    if not expected:
        raise ProjectError(ErrorCode.UNAVAILABLE, "Evaluation dashboard is disabled")
    if not admin_token or not hmac.compare_digest(admin_token, expected):
        raise ProjectError(ErrorCode.UNAUTHENTICATED, "Invalid admin credential")
    container = cast(ApiContainer, request.app.state.container)
    if container.evaluation_dashboard is None:
        raise ProjectError(ErrorCode.UNAVAILABLE, "Evaluation dashboard data is unavailable")
    return container.evaluation_dashboard


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


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    request: Request, conversation_id: str
) -> dict[str, Any]:
    return await _paper_agent(request).delete_conversation(conversation_id)


@router.get("/conversations/{conversation_id}/usage")
async def get_conversation_usage(
    request: Request, conversation_id: str
) -> dict[str, Any]:
    return await _paper_agent(request).conversation_usage(conversation_id)


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


@router.get("/visual-artifacts/{artifact_id}/image")
async def get_visual_artifact_image(request: Request, artifact_id: str) -> Response:
    artifact = await _paper_agent(request).get_visual_artifact(artifact_id)
    return Response(
        content=artifact["data"],
        media_type=artifact["content_type"],
        headers={"Cache-Control": "private, max-age=3600"},
    )


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


@router.get("/product-tasks/{task_id}/monitor")
async def get_product_task_monitor(request: Request, task_id: str) -> dict[str, Any]:
    return await _paper_agent(request).get_task_monitor(task_id)


@router.get("/debug/files/{file_id}/parse")
async def debug_parse_result(request: Request, file_id: str) -> dict[str, Any]:
    return await _paper_agent(request).debug_parse_result(file_id)


@router.post("/debug/retrieval/preview")
async def debug_retrieval_preview(
    request: Request, body: RetrievalPreviewRequest
) -> dict[str, Any]:
    return await _paper_agent(request).debug_retrieval_preview(
        body.conversation_id,
        body.question,
        body.file_ids,
    )


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


@router.get("/admin/hitl/candidates")
async def list_hitl_candidates(
    request: Request,
    admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    registry = _hitl_registry(request, admin_token)
    return {
        "items": [item.model_dump(mode="json") for item in registry.list_candidates()]
    }


@router.post("/admin/hitl/candidates/{candidate_id}/review")
async def review_hitl_candidate(
    request: Request,
    candidate_id: str,
    body: HumanReviewRequest,
    admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    registry = _hitl_registry(request, admin_token)
    try:
        reviewed = registry.review(
            candidate_id,
            HumanReview(
                reviewer_id=body.reviewer_id,
                decision=body.decision,
                rationale=body.rationale,
            ),
        )
    except KeyError as exc:
        raise ProjectError(ErrorCode.NOT_FOUND, "HITL candidate not found") from exc
    return reviewed.model_dump(mode="json")


@router.get("/admin/evaluation/metrics")
async def get_evaluation_metrics(
    request: Request,
    task_family: str | None = None,
    difficulty: str | None = None,
    language: Literal["zh", "en", "mixed"] | None = None,
    model: str | None = None,
    error_category: str | None = None,
    system_id: str | None = None,
    admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    dashboard = _evaluation_dashboard(request, admin_token)
    return dashboard.query(
        DashboardFilters(
            task_family=task_family,
            difficulty=difficulty,
            language=language,
            model=model,
            error_category=error_category,
            system_id=system_id,
        )
    ).model_dump(mode="json")


@router.get("/admin/evaluation/compare")
async def compare_evaluation_systems(
    request: Request,
    baseline_id: str,
    candidate_id: str,
    admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    dashboard = _evaluation_dashboard(request, admin_token)
    try:
        comparison = dashboard.compare(baseline_id, candidate_id)
    except ValueError as exc:
        raise ProjectError(ErrorCode.INVALID_ARGUMENT, str(exc)) from exc
    return comparison.model_dump(mode="json")


@router.get("/admin/evaluation/cases/{system_id}/{case_id}")
async def get_evaluation_case(
    request: Request,
    system_id: str,
    case_id: str,
    admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    dashboard = _evaluation_dashboard(request, admin_token)
    try:
        detail = dashboard.case_detail(case_id, system_id)
    except KeyError as exc:
        raise ProjectError(ErrorCode.NOT_FOUND, "Evaluation case not found") from exc
    return detail.model_dump(mode="json")


@router.post("/tasks")
async def create_task(request: Request, body: TaskCreateRequest) -> dict:
    container: ApiContainer = request.app.state.container
    task_id = await container.task_queue.enqueue(
        task_type=body.task_type,
        payload=body.payload,
        idempotency_key=body.idempotency_key,
    )
    return {"task_id": task_id, "status": "pending"}


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
