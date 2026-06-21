import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from apps.api.config import ApiSettings
from apps.api.dependencies import StaticUUIDGenerator, SystemClock, build_fake_container
from apps.api.main import create_app
from core.errors import ErrorCode, ProjectError


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
