"""Drain controls for retiring queued document tasks with V1/V2 snapshots."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.core.ports.storage import TaskQueue
from backend.infrastructure.postgres.models import QueueJobModel


class LegacyDocumentDrainPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    intake_frozen: bool
    queued_legacy_ids: tuple[str, ...]
    running_legacy_ids: tuple[str, ...]
    safe_for_v2_only_deploy: bool
    next_action: str


class LegacyDocumentCancelResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cancelled_ids: tuple[str, ...]
    running_legacy_ids: tuple[str, ...]
    next_action: str


class LegacyDocumentTaskDrainService:
    """Classify old snapshot tasks without mutating or reinterpreting payloads."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def inspect(self, *, intake_frozen: bool) -> LegacyDocumentDrainPlan:
        with self._sessions() as session:
            jobs = session.scalars(
                select(QueueJobModel).where(
                    QueueJobModel.task_type == "document_parse",
                    QueueJobModel.status.in_(("queued", "running")),
                )
            ).all()
        legacy = [
            job
            for job in jobs
            if "document_pipeline_snapshot" in (job.payload or {})
        ]
        queued = tuple(sorted(job.id for job in legacy if job.status == "queued"))
        running = tuple(sorted(job.id for job in legacy if job.status == "running"))
        safe = intake_frozen and not queued and not running
        return LegacyDocumentDrainPlan(
            intake_frozen=intake_frozen,
            queued_legacy_ids=queued,
            running_legacy_ids=running,
            safe_for_v2_only_deploy=safe,
            next_action=(
                "deploy_v2_only"
                if safe
                else "cancel_queued_and_wait_for_running_legacy_tasks"
            ),
        )

    async def cancel_queued_legacy(
        self, queue: TaskQueue, *, intake_frozen: bool
    ) -> LegacyDocumentCancelResult:
        if not intake_frozen:
            raise ValueError("freeze document-parse intake before cancelling legacy tasks")
        plan = self.inspect(intake_frozen=True)
        cancelled_ids: list[str] = []
        for task_id in plan.queued_legacy_ids:
            if await queue.cancel(task_id):
                cancelled_ids.append(task_id)
        return LegacyDocumentCancelResult(
            cancelled_ids=tuple(cancelled_ids),
            running_legacy_ids=plan.running_legacy_ids,
            next_action=(
                "wait_for_running_legacy_tasks"
                if plan.running_legacy_ids
                else "deploy_v2_only"
            ),
        )
