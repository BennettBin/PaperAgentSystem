from pathlib import Path

import yaml

from infrastructure.docker.service_runtime import deployment_status

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
    payload = yaml.safe_load((ROOT / "infrastructure" / "docker" / "compose.yaml").read_text(encoding="utf-8"))
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

    assert "docker compose -f infrastructure/docker/compose.yaml up --build" in readme
    assert "docker compose -f infrastructure/docker/compose.yaml ps" in readme


def test_web_image_builds_rewrites_with_compose_api_address() -> None:
    dockerfile = (ROOT / "infrastructure" / "docker" / "Dockerfile.web").read_text(encoding="utf-8")
    payload = yaml.safe_load((ROOT / "infrastructure" / "docker" / "compose.yaml").read_text(encoding="utf-8"))
    web = payload["services"]["web"]

    build_command = "RUN npm run build"
    assert "ARG API_INTERNAL_URL=http://api:8000" in dockerfile
    assert "ENV API_INTERNAL_URL=$API_INTERNAL_URL" in dockerfile
    assert dockerfile.index("ENV API_INTERNAL_URL=$API_INTERNAL_URL") < dockerfile.index(
        build_command
    )
    assert web["build"]["args"]["API_INTERNAL_URL"] == web["environment"][
        "API_INTERNAL_URL"
    ]
    assert "/api/v1/conversations" in web["healthcheck"]["test"][-1]


def test_docker_build_context_never_contains_local_environment_files() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in dockerignore
    assert ".env.*" in dockerignore
