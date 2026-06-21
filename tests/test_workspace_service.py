import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.errors import ProjectError
from infrastructure.fake.adapters import FakeObjectStore
from infrastructure.postgres.models import Base
from workspace.service import WorkspaceService


@pytest.fixture
def service(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'workspace.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    return WorkspaceService(tmp_path / "mount", factory, FakeObjectStore())


@pytest.mark.asyncio
async def test_layout_manifest_promote_cleanup_and_recovery(service):
    conversation = service.create_conversation("ws", "conv")
    assert {"uploads", "shared", "tasks", "artifacts"} <= {
        item.name for item in conversation.iterdir()
    }
    task = service.create_task("ws", "conv", "task")
    assert {"inputs", "scratch", "scripts", "outputs", "logs"} <= {
        item.name for item in task.iterdir()
    }
    entry = await service.write_entry(
        "ws",
        "conv",
        "scripts/analyze.py",
        b"print('safe')",
        "text/x-python",
        task_id="task",
        source_type="tool",
        source_id="tool-1",
    )
    assert service.read_entry(entry.entry_id, "ws", "conv", "task") == b"print('safe')"
    assert not entry.executable
    assert os.stat(task / "scripts" / "analyze.py").st_mode & 0o111 == 0
    promoted = service.promote(entry.entry_id, "ws")
    assert promoted.source_id == entry.entry_id
    assert (conversation / promoted.relative_path).exists()
    temporary = await service.write_entry(
        "ws",
        "conv",
        "scratch/temp.txt",
        b"temp",
        "text/plain",
        task_id="task",
        retention="temporary",
    )
    service.cleanup_task("ws", "conv", "task")
    with pytest.raises(ProjectError):
        service.read_entry(temporary.entry_id, "ws", "conv", "task")
    assert service.recover("ws", "conv", "task").joinpath("manifest.json").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["../escape", "/absolute", "scripts\\bad.py"])
async def test_path_escape_blocked(service, path):
    with pytest.raises(ProjectError):
        await service.write_entry(
            "ws", "conv", path, b"x", "text/plain", task_id="task"
        )


@pytest.mark.asyncio
async def test_task_and_conversation_isolation_and_file_type(service):
    first = await service.write_entry(
        "ws", "conv", "outputs/result.md", b"one", "text/markdown", task_id="task-1"
    )
    await service.write_entry(
        "ws", "conv", "outputs/result.md", b"two", "text/markdown", task_id="task-2"
    )
    with pytest.raises(ProjectError):
        service.read_entry(first.entry_id, "ws", "conv", "task-2")
    with pytest.raises(ProjectError):
        await service.write_entry(
            "ws", "conv", "inputs/binary.exe", b"MZ", "application/x-msdownload"
        )
