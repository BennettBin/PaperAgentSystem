import pytest

from core.errors import ErrorCode, ProjectError
from infrastructure.sandbox import DisabledSandboxExecutor


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["python", "shell", "bash", "powershell"])
async def test_disabled_sandbox_never_executes_code(language: str, tmp_path) -> None:
    marker = tmp_path / "executed.txt"
    executor = DisabledSandboxExecutor()

    with pytest.raises(ProjectError) as exc:
        await executor.execute_code(
            f"open(r'{marker}', 'w').write('executed')",
            language=language,
        )

    assert exc.value.code is ErrorCode.SANDBOX_EXECUTION_NOT_SUPPORTED
    assert exc.value.details["network"] == "disabled"
    assert not marker.exists()


@pytest.mark.asyncio
async def test_disabled_sandbox_never_invokes_latex() -> None:
    executor = DisabledSandboxExecutor()

    with pytest.raises(ProjectError) as exc:
        await executor.render_latex(r"\write18{touch escaped}")

    assert exc.value.code is ErrorCode.SANDBOX_EXECUTION_NOT_SUPPORTED
    assert exc.value.details["lifecycle"] == "one_shot_if_enabled"
