"""Explicitly disabled executor for deployments without a real sandbox."""

from core.errors import ErrorCode, ProjectError
from core.ports.processing import SandboxExecutor


class DisabledSandboxExecutor(SandboxExecutor):
    """Never executes generated code or LaTeX in a normal Worker."""

    async def execute_code(
        self,
        code: str,
        language: str = "python",
        timeout_seconds: int = 30,
    ) -> dict:
        raise ProjectError(
            ErrorCode.SANDBOX_EXECUTION_NOT_SUPPORTED,
            "Code execution is disabled because no isolated SandboxExecutor is configured",
            {
                "language": language,
                "requested_timeout_seconds": timeout_seconds,
                "network": "disabled",
                "inputs": "read_only_if_enabled",
                "lifecycle": "one_shot_if_enabled",
            },
        )

    async def render_latex(self, latex_code: str) -> bytes:
        raise ProjectError(
            ErrorCode.SANDBOX_EXECUTION_NOT_SUPPORTED,
            "LaTeX execution is disabled because no isolated SandboxExecutor is configured",
            {
                "network": "disabled",
                "inputs": "read_only_if_enabled",
                "lifecycle": "one_shot_if_enabled",
            },
        )
