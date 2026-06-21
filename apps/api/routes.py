from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from apps.api.dependencies import ApiContainer
from core.errors import ErrorCode, ProjectError

router = APIRouter(prefix="/api/v1")


class TaskCreateRequest(BaseModel):
    task_type: str = "main_agent"
    payload: dict = Field(default_factory=dict)
    idempotency_key: str


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
