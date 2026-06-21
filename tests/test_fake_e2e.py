import pytest
from fastapi.testclient import TestClient

from apps.api.config import ApiSettings
from apps.api.dependencies import build_fake_container
from apps.api.main import create_app

SCENARIOS = [
    "direct_execution",
    "clarification_resume",
    "subagents_partial_failure",
    "verification_replan",
    "cancel_retry",
    "memory_recall",
    "workspace_recall",
    "deletion_invalidation",
    "writing_artifact",
]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_stage_b_fake_e2e_scenarios(scenario):
    app = create_app(ApiSettings(_env_file=None), build_fake_container())
    response = TestClient(app).post(f"/api/v1/demo/{scenario}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario"] == scenario
    assert payload["trace"]
    assert [event["sequence"] for event in payload["events"]] == list(
        range(1, len(payload["events"]) + 1)
    )


def test_clarification_resumes_original_task():
    app = create_app(ApiSettings(_env_file=None), build_fake_container())
    payload = TestClient(app).post("/api/v1/demo/clarification_resume").json()
    assert payload["details"]["resumed_original_task"] is True


def test_deletion_invalidates_fake_search():
    app = create_app(ApiSettings(_env_file=None), build_fake_container())
    payload = TestClient(app).post("/api/v1/demo/deletion_invalidation").json()
    assert payload["details"]["search_results"] == []


def test_writing_produces_reviewable_artifact():
    app = create_app(ApiSettings(_env_file=None), build_fake_container())
    payload = TestClient(app).post("/api/v1/demo/writing_artifact").json()
    assert payload["details"]["artifact_id"]
    assert payload["details"]["review_required"] is True
