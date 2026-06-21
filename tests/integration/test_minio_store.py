import io

import pytest
from minio import Minio
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

from core.errors import ProjectError
from infrastructure.minio.object_store import MinioObjectStore
from infrastructure.postgres.models import Base, ObjectBlobModel

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def minio_client():
    container = (
        DockerContainer("minio/minio:RELEASE.2025-04-22T22-12-26Z")
        .with_env("MINIO_ROOT_USER", "minioadmin")
        .with_env("MINIO_ROOT_PASSWORD", "minioadmin")
        .with_command("server /data --console-address :9001")
        .with_exposed_ports(9000)
    )
    with container:
        wait_for_logs(container, "API:")
        endpoint = f"{container.get_container_host_ip()}:{container.get_exposed_port(9000)}"
        yield Minio(endpoint, access_key="minioadmin", secret_key="minioadmin", secure=False)


@pytest.fixture
def store(minio_client, tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'objects.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    return MinioObjectStore(minio_client, factory, "workspace-1", "test-paperagent"), factory


@pytest.mark.asyncio
async def test_upload_download_deduplicate_and_reference_delete(store):
    object_store, factory = store
    first = await object_store.upload(
        "uploads/paper.pdf", b"%PDF-test", "application/pdf"
    )
    second = await object_store.upload(
        "uploads/copy.pdf", b"%PDF-test", "application/pdf"
    )
    assert first == second
    assert await object_store.download(first) == b"%PDF-test"
    assert "X-Amz-Signature" in await object_store.get_temporary_url(first, 60)
    with factory() as session:
        record = session.scalar(select(ObjectBlobModel))
        assert record is not None and record.reference_count == 2
    await object_store.delete(first)
    assert await object_store.exists(first)
    await object_store.delete(first)
    assert not await object_store.exists(first)
    with factory() as session:
        assert session.scalar(select(ObjectBlobModel)) is None


@pytest.mark.asyncio
async def test_workspace_isolation_mime_signature_and_streaming(store):
    object_store, _ = store
    with pytest.raises(ProjectError):
        await object_store.download("uploads/other/path")
    with pytest.raises(ProjectError):
        await object_store.upload("uploads/fake.pdf", b"not-pdf", "application/pdf")
    content = b"x" * (2 * 1024 * 1024)
    key = await object_store.upload_stream(
        "workspace/large.txt", io.BytesIO(content), "text/plain"
    )
    assert await object_store.download(key) == content
