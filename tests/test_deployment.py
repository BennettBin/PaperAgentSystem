from pathlib import Path

import yaml

from deploy.service_runtime import deployment_status

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SERVICES = {
    "web",
    "api",
    "worker",
    "postgres",
    "redis",
    "minio",
    "model-router",
    "model-1-7b",
    "model-4b",
    "observability",
}


def test_compose_defines_all_services_with_health_checks() -> None:
    payload = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = payload["services"]

    assert REQUIRED_SERVICES <= services.keys()
    for name in REQUIRED_SERVICES:
        assert services[name].get("healthcheck"), f"{name} must define a healthcheck"


def test_model_services_expose_explicit_unavailable_degradation() -> None:
    router = deployment_status("model-router", model_available=False)
    model = deployment_status("model-1-7b", model_available=False)

    assert router["status"] == "degraded"
    assert router["model_available"] is False
    assert router["error"]["code"] == "model_not_available"
    assert model["status"] == "unavailable"
    assert model["error"]["retryable"] is True


def test_readme_contains_fresh_environment_startup_command() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "docker compose up --build" in readme
    assert "docker compose ps" in readme
