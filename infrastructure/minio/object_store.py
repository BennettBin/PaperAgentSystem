import hashlib
import io
from datetime import timedelta
from pathlib import PurePosixPath
from typing import BinaryIO
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.errors import ErrorCode, ProjectError
from core.ports.storage import ObjectStore
from infrastructure.postgres.models import ObjectBlobModel
from minio import Minio
from minio.commonconfig import CopySource

ALLOWED_BUCKETS = {"uploads", "workspace", "artifacts"}


class MinioObjectStore(ObjectStore):
    def __init__(
        self,
        client: Minio,
        session_factory: sessionmaker[Session],
        workspace_id: str,
        bucket_prefix: str = "paperagent",
    ) -> None:
        self.client = client
        self.session_factory = session_factory
        self.workspace_id = workspace_id
        self.bucket_prefix = bucket_prefix
        for logical_bucket in ALLOWED_BUCKETS:
            bucket = self._bucket(logical_bucket)
            if not self.client.bucket_exists(bucket):
                self.client.make_bucket(bucket)

    async def upload(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        return await self.upload_stream(key, io.BytesIO(data), content_type)

    async def upload_stream(
        self,
        key: str,
        stream: BinaryIO,
        content_type: str = "application/octet-stream",
    ) -> str:
        logical_bucket, logical_name = self._parse_key(key)
        payload = self._read_stream(stream)
        self._verify_signature(payload, content_type)
        checksum = hashlib.sha256(payload).hexdigest()
        with self.session_factory() as session:
            existing = session.scalar(
                select(ObjectBlobModel).where(
                    ObjectBlobModel.workspace_id == self.workspace_id,
                    ObjectBlobModel.bucket == logical_bucket,
                    ObjectBlobModel.checksum == checksum,
                    ObjectBlobModel.deleted_at.is_(None),
                    ObjectBlobModel.upload_complete.is_(True),
                )
            )
            if existing is not None:
                existing.reference_count += 1
                session.commit()
                return f"{logical_bucket}/{self.workspace_id}/{existing.object_name}"

            object_name = (
                f"{self.workspace_id}/{checksum[:2]}/{checksum}-{PurePosixPath(logical_name).name}"
            )
            temporary = f"{self.workspace_id}/.tmp/{uuid4().hex}"
            bucket = self._bucket(logical_bucket)
            record = ObjectBlobModel(
                id=uuid4().hex,
                workspace_id=self.workspace_id,
                bucket=logical_bucket,
                object_name=object_name,
                checksum=checksum,
                content_type=content_type,
                size_bytes=len(payload),
                reference_count=1,
                upload_complete=False,
            )
            session.add(record)
            session.commit()
            try:
                self.client.put_object(
                    bucket,
                    temporary,
                    io.BytesIO(payload),
                    length=len(payload),
                    content_type=content_type,
                )
                self.client.copy_object(bucket, object_name, CopySource(bucket, temporary))
                self.client.remove_object(bucket, temporary)
                record.upload_complete = True
                session.commit()
            except Exception:
                self.client.remove_object(bucket, temporary)
                session.delete(record)
                session.commit()
                raise
        return f"{logical_bucket}/{self.workspace_id}/{object_name}"

    async def download(self, key: str) -> bytes:
        stream = await self.download_stream(key)
        return stream.read()

    async def download_stream(self, key: str) -> io.BytesIO:
        logical_bucket, object_name = self._authorized_object(key)
        response = self.client.get_object(self._bucket(logical_bucket), object_name)
        try:
            return io.BytesIO(response.read())
        finally:
            response.close()
            response.release_conn()

    async def delete(self, key: str) -> None:
        logical_bucket, object_name = self._authorized_object(key)
        with self.session_factory() as session:
            record = session.scalar(
                select(ObjectBlobModel).where(
                    ObjectBlobModel.workspace_id == self.workspace_id,
                    ObjectBlobModel.bucket == logical_bucket,
                    ObjectBlobModel.object_name == object_name,
                    ObjectBlobModel.deleted_at.is_(None),
                )
            )
            if record is None:
                return
            record.reference_count = max(0, record.reference_count - 1)
            if record.reference_count == 0:
                self.client.remove_object(self._bucket(logical_bucket), object_name)
                session.delete(record)
            session.commit()

    async def exists(self, key: str) -> bool:
        try:
            logical_bucket, object_name = self._authorized_object(key)
            self.client.stat_object(self._bucket(logical_bucket), object_name)
            return True
        except Exception:
            return False

    async def get_temporary_url(self, key: str, expires_in_seconds: int = 3600) -> str:
        logical_bucket, object_name = self._authorized_object(key)
        return self.client.presigned_get_object(
            self._bucket(logical_bucket),
            object_name,
            expires=timedelta(seconds=expires_in_seconds),
        )

    def _bucket(self, logical_bucket: str) -> str:
        return f"{self.bucket_prefix}-{logical_bucket}"

    def _parse_key(self, key: str) -> tuple[str, str]:
        path = PurePosixPath(key)
        if path.is_absolute() or ".." in path.parts or len(path.parts) < 2:
            raise ProjectError(ErrorCode.INVALID_ARGUMENT, "Invalid object key")
        bucket = path.parts[0]
        if bucket not in ALLOWED_BUCKETS:
            raise ProjectError(ErrorCode.INVALID_ARGUMENT, "Invalid object bucket")
        return bucket, "/".join(path.parts[1:])

    def _authorized_object(self, key: str) -> tuple[str, str]:
        bucket, remainder = self._parse_key(key)
        prefix = f"{self.workspace_id}/"
        if not remainder.startswith(prefix):
            raise ProjectError(ErrorCode.PERMISSION_DENIED, "Cross-workspace object access")
        object_name = remainder[len(prefix) :]
        if not object_name.startswith(f"{self.workspace_id}/"):
            raise ProjectError(ErrorCode.PERMISSION_DENIED, "Invalid object ownership")
        return bucket, object_name

    @staticmethod
    def _read_stream(stream: BinaryIO) -> bytes:
        chunks: list[bytes] = []
        while chunk := stream.read(1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _verify_signature(data: bytes, content_type: str) -> None:
        signatures = {
            "application/pdf": b"%PDF",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": b"PK",
        }
        required = signatures.get(content_type)
        if required is not None and not data.startswith(required):
            raise ProjectError(ErrorCode.UNSAFE_FILE_TYPE, "File signature does not match MIME")
        if content_type.startswith("text/"):
            try:
                data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ProjectError(
                    ErrorCode.UNSAFE_FILE_TYPE, "Text file is not valid UTF-8"
                ) from exc
