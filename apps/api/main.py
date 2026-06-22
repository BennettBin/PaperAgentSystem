from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware

from apps.api.config import ApiSettings
from apps.api.dependencies import (
    ApiContainer,
    build_fake_container,
    build_infrastructure_container,
)
from apps.api.routes import router
from core.errors import ErrorCode, ProjectError


def create_app(
    settings: ApiSettings,
    container: ApiContainer | None = None,
) -> FastAPI:
    if container is None:
        if settings.adapter_mode == "real":
            from apps.api.product_service import LOCAL_WORKSPACE_ID
            from infrastructure.config import InfrastructureSettings

            container = build_infrastructure_container(
                InfrastructureSettings(),
                LOCAL_WORKSPACE_ID,
            )
        else:
            container = build_fake_container()
    app = FastAPI(title="PaperAgentSystem API")
    app.state.container = container
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.middleware("http")
    async def add_request_trace_ids(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = container.request_id_generator.generate_request_id()
        trace_id = container.trace_id_generator.generate_trace_id()
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Trace-ID"] = trace_id
        return response

    @app.exception_handler(ProjectError)
    async def project_error_handler(request: Request, exc: ProjectError) -> JSONResponse:
        content = exc.to_dict()
        content["error"]["request_id"] = request.state.request_id
        content["error"]["trace_id"] = request.state.trace_id
        return JSONResponse(status_code=exc.http_status_code, content=content)

    @app.exception_handler(Exception)
    async def unexpected_error_handler(
        request: Request, _exc: Exception
    ) -> JSONResponse:
        error = ProjectError(
            code=ErrorCode.INTERNAL_ERROR,
            message="An unexpected error occurred",
        )
        content = error.to_dict()
        content["error"]["request_id"] = request.state.request_id
        content["error"]["trace_id"] = request.state.trace_id
        return JSONResponse(status_code=500, content=content)

    @app.get("/health/live")
    async def health_live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready")
    async def health_ready() -> dict[str, str]:
        if not await container.is_ready():
            raise ProjectError(ErrorCode.UNAVAILABLE, "Application is not ready")
        return {"status": "ready", "adapter_mode": settings.adapter_mode}

    @app.get("/health/config")
    async def health_config() -> dict[str, str | int | bool]:
        return {
            "api_host": settings.api_host,
            "api_port": settings.api_port,
            "api_debug": settings.api_debug,
        }

    return app


app = create_app(settings=ApiSettings())
