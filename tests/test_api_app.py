from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.apps.api.config import ApiSettings
from backend.apps.api.dependencies import StaticUUIDGenerator, SystemClock, build_fake_container
from backend.apps.api.main import create_app
from backend.core.errors import ErrorCode, ProjectError
from evaluation.dashboard import DashboardCase, OfflineEvaluationDashboard
from evaluation.datasets.schema import AuthorizationStatus
from evaluation.experiments import ErrorCategory as EvaluationErrorCategory
from evaluation.hitl import CandidateSource, StagingCandidate, StagingRegistry


def test_health_live_and_ready():
    settings = ApiSettings(
        api_host="0.0.0.0",
        api_port=8000,
        api_debug=True,
        api_workers=1,
        secret_key="test_secret",
        allowed_hosts="localhost",
        model_router_endpoint="http://localhost:8001",
    )
    app = create_app(
        settings=settings,
        container=build_fake_container(
            request_id_generator=StaticUUIDGenerator(),
            trace_id_generator=StaticUUIDGenerator(),
            clock=SystemClock(),
        ),
    )
    client = TestClient(app)

    response_live = client.get("/health/live")
    assert response_live.status_code == 200
    assert response_live.json() == {"status": "alive"}
    assert "X-Request-ID" in response_live.headers
    assert "X-Trace-ID" in response_live.headers

    response_ready = client.get("/health/ready")
    assert response_ready.status_code == 200
    assert response_ready.json() == {"status": "ready", "adapter_mode": "fake"}

    response_config = client.get("/health/config")
    assert response_config.status_code == 200
    assert response_config.json()["api_host"] == "0.0.0.0"
    assert response_config.json()["api_port"] == 8000


def test_project_error_uses_unified_shape_and_correlation_ids():
    settings = ApiSettings(_env_file=None)
    app = create_app(settings=settings, container=build_fake_container())

    @app.get("/boom")
    async def boom():
        raise ProjectError(ErrorCode.INVALID_ARGUMENT, "bad request")

    response = TestClient(app).get("/boom")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_argument"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert response.json()["error"]["trace_id"] == response.headers["X-Trace-ID"]


def test_unexpected_error_is_sanitized():
    settings = ApiSettings(_env_file=None)
    app = create_app(settings=settings, container=build_fake_container())

    @app.get("/unexpected")
    async def unexpected():
        raise RuntimeError("sensitive internals")

    response = TestClient(app, raise_server_exceptions=False).get("/unexpected")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "sensitive internals" not in response.text


def test_production_configuration_reports_missing_secrets():
    with pytest.raises(ValidationError):
        ApiSettings(environment="production", secret_key=None, _env_file=None)


def test_stub_route_does_not_require_real_infrastructure():
    app = create_app(
        settings=ApiSettings(_env_file=None),
        container=build_fake_container(),
    )
    response = TestClient(app).post(
        "/api/v1/tasks",
        json={
            "task_type": "main_agent",
            "payload": {"message": "hello"},
            "idempotency_key": "api-task-1",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"task_id": "api-task-1", "status": "pending"}


def test_demo_scenario_route_is_not_exposed():
    app = create_app(settings=ApiSettings(_env_file=None), container=build_fake_container())
    response = TestClient(app).post("/api/v1/demo/direct_execution")

    assert response.status_code == 404


def test_hitl_review_endpoints_are_admin_only_and_return_public_context(tmp_path):
    registry = StagingRegistry(tmp_path)
    registry.stage(
        StagingCandidate(
            candidate_id="candidate-1",
            failure_case_id="case-1",
            error_category=EvaluationErrorCategory.RETRIEVAL,
            source=CandidateSource(
                source_id="source-1",
                provenance_uri="evaluation/reports/run-1/case-1.json",
                authorization_status=AuthorizationStatus.PUBLIC,
                license="Apache-2.0",
                build_version="run-1",
                anonymized=True,
            ),
            public_context={"task_family": "qa", "difficulty": "L3"},
            proposed_change="reviewed retrieval example",
            created_by="reviewer-a",
        )
    )
    container = replace(build_fake_container(), hitl_registry=registry)
    app = create_app(
        settings=ApiSettings(admin_api_token="admin-test", _env_file=None),
        container=container,
    )
    client = TestClient(app)

    assert client.get("/api/v1/admin/hitl/candidates").status_code == 401
    response = client.get(
        "/api/v1/admin/hitl/candidates", headers={"X-Admin-Token": "admin-test"}
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["public_context"] == {
        "task_family": "qa",
        "difficulty": "L3",
    }
    assert "trace" not in response.text
    reviewed = client.post(
        "/api/v1/admin/hitl/candidates/candidate-1/review",
        headers={"X-Admin-Token": "admin-test"},
        json={
            "reviewer_id": "reviewer-b",
            "decision": "approved",
            "rationale": "authorized and useful",
        },
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["review"]["decision"] == "approved"


def test_evaluation_dashboard_is_admin_only_and_supports_metric_drilldown():
    dashboard = OfflineEvaluationDashboard(
        [
            DashboardCase(
                report_version="report-v1",
                case_id="case-1",
                system_id="candidate",
                task_family="qa",
                difficulty="L3",
                language="zh",
                model="qwen3.5:4b",
                task_success=True,
                claim_support=0.9,
                input_tokens=100,
                output_tokens=20,
                model_calls=1,
                four_b_calls=1,
                latency_ms=1000,
                monetary_cost=0.0,
            )
        ]
    )
    container = replace(build_fake_container(), evaluation_dashboard=dashboard)
    app = create_app(
        settings=ApiSettings(admin_api_token="admin-test", _env_file=None),
        container=container,
    )
    client = TestClient(app)

    assert client.get("/api/v1/admin/evaluation/metrics").status_code == 401
    headers = {"X-Admin-Token": "admin-test"}
    metrics = client.get(
        "/api/v1/admin/evaluation/metrics?task_family=qa", headers=headers
    )
    assert metrics.status_code == 200
    assert metrics.json()["metrics"]["task_success"]["case_ids"] == ["case-1"]
    detail = client.get(
        "/api/v1/admin/evaluation/cases/candidate/case-1", headers=headers
    )
    assert detail.status_code == 200
    assert detail.json()["report_version"] == "report-v1"
