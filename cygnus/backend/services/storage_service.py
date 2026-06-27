"""
MinIO storage service — file upload, download, presigned URLs.
"""

import io
from collections.abc import Callable
from datetime import timedelta
from typing import IO, Optional

from loguru import logger
from minio import Minio
from minio.error import S3Error

from cygnus.backend.config import Settings, get_settings


class StorageService:
    """S3-compatible object storage via MinIO."""

    def __init__(
        self,
        *,
        settings_provider: Callable[[], Settings] = get_settings,
        client_factory: Callable[..., Minio] = Minio,
    ):
        self._settings_provider = settings_provider
        self._client_factory = client_factory
        self._client: Optional[Minio] = None
        self._presign_client: Optional[Minio] = None

    def _settings(self) -> Settings:
        return self._settings_provider()

    def reset_clients(self) -> None:
        """Drop cached clients so updated wiring is picked up on next access."""
        self._client = None
        self._presign_client = None

    @property
    def client(self) -> Minio:
        if self._client is None:
            resolved_settings = self._settings()
            self._client = self._client_factory(
                endpoint=resolved_settings.minio_endpoint,
                access_key=resolved_settings.minio_access_key,
                secret_key=resolved_settings.minio_secret_key,
                secure=resolved_settings.minio_secure,
            )
        return self._client

    @property
    def presign_client(self) -> Minio:
        """Separate client using the public endpoint so presigned URL signatures match.

        Pre-seeds the bucket region to avoid a connectivity check against the public
        endpoint (which may be unreachable from inside the Docker container).
        MinIO always uses us-east-1 by default.
        """
        if self._presign_client is None:
            resolved_settings = self._settings()
            public = resolved_settings.minio_public_endpoint or resolved_settings.minio_endpoint
            # When a public endpoint is explicitly set, we're behind a reverse
            # proxy that terminates TLS — presigned URLs must use https://.
            presign_secure = (
                True if resolved_settings.minio_public_endpoint else resolved_settings.minio_secure
            )
            client = self._client_factory(
                endpoint=public,
                access_key=resolved_settings.minio_access_key,
                secret_key=resolved_settings.minio_secret_key,
                secure=presign_secure,
            )
            client._region_map[resolved_settings.minio_bucket] = "us-east-1"
            self._presign_client = client
        return self._presign_client

    async def ensure_bucket(self):
        """Create the default bucket if it doesn't exist."""
        bucket = self._settings().minio_bucket
        try:
            if not self.client.bucket_exists(bucket):
                self.client.make_bucket(bucket)
                logger.info(f"Created MinIO bucket: {bucket}")
            else:
                logger.debug(f"MinIO bucket already exists: {bucket}")
        except S3Error as e:
            logger.error(f"Failed to ensure MinIO bucket: {e}")
            raise

    def upload_file(
        self,
        object_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload a file to MinIO. Returns the object key."""
        bucket = self._settings().minio_bucket
        self.client.put_object(
            bucket_name=bucket,
            object_name=object_name,
            data=io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        logger.debug(f"Uploaded {object_name} to MinIO ({len(data)} bytes)")
        return object_name

    def download_file(self, object_name: str) -> bytes:
        """Download a file from MinIO and return its bytes."""
        bucket = self._settings().minio_bucket
        response = None
        try:
            response = self.client.get_object(bucket, object_name)
            return response.read()
        finally:
            if response:
                response.close()
                response.release_conn()

    def upload_stream(
        self,
        object_name: str,
        stream: IO[bytes],
        length: int,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload from a stream."""
        bucket = self._settings().minio_bucket
        self.client.put_object(
            bucket_name=bucket,
            object_name=object_name,
            data=stream,  # type: ignore[arg-type]
            length=length,
            content_type=content_type,
        )
        return object_name

    async def upload_stream_async(
        self,
        object_name: str,
        stream: IO[bytes],
        length: int,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Non-blocking wrapper for upload_stream using asyncio.to_thread."""
        import asyncio
        return await asyncio.to_thread(
            self.upload_stream, object_name, stream, length, content_type
        )

    def get_presigned_url(
        self,
        object_name: str,
        expiry_hours: Optional[int] = None,
    ) -> str:
        """Generate a presigned download URL using the public-facing endpoint.

        Uses a dedicated client configured with minio_public_endpoint so the
        HMAC signature is computed against the browser-accessible hostname.
        """
        resolved_settings = self._settings()
        hours = expiry_hours or resolved_settings.minio_presign_expiry_hours
        return self.presign_client.presigned_get_object(
            bucket_name=resolved_settings.minio_bucket,
            object_name=object_name,
            expires=timedelta(hours=hours),
        )

    def delete_object(self, object_name: str):
        """Delete a file from MinIO."""
        self.client.remove_object(self._settings().minio_bucket, object_name)
        logger.debug(f"Deleted {object_name} from MinIO")

    def list_objects(self, prefix: str, recursive: bool = True):
        """List all objects under a given prefix."""
        return self.client.list_objects(self._settings().minio_bucket, prefix=prefix, recursive=recursive)

    def delete_prefix(self, prefix: str):
        """Delete all objects with a given prefix (e.g. a source's files)."""
        bucket = self._settings().minio_bucket
        objects = self.client.list_objects(bucket, prefix=prefix, recursive=True)
        for obj in objects:
            if obj.object_name:
                self.client.remove_object(bucket, obj.object_name)
        logger.debug(f"Deleted all objects with prefix: {prefix}")

    def copy_object(self, src_key: str, dest_key: str):
        """Copy a single object within the same bucket."""
        from minio.commonconfig import CopySource
        bucket = self._settings().minio_bucket
        self.client.copy_object(
            bucket,
            dest_key,
            CopySource(bucket, src_key),
        )

    def copy_prefix(self, src_prefix: str, dest_prefix: str):
        """Copy all objects from one prefix to another (recursively)."""
        bucket = self._settings().minio_bucket
        
        # Check if src_prefix is a specific file using stat_object (more reliable)
        is_file = False
        try:
            self.client.stat_object(bucket, src_prefix)
            is_file = True
        except Exception:
            is_file = False
        
        if is_file:
            # Single file copy - do NOT add slashes
            self.copy_object(src_prefix, dest_prefix)
            logger.debug(f"Copied file {src_prefix} to {dest_prefix}")
            return

        # Directory copy - MUST ensure trailing slashes to avoid partial matches
        src_p = src_prefix if src_prefix.endswith("/") else f"{src_prefix}/"
        dest_p = dest_prefix if dest_prefix.endswith("/") else f"{dest_prefix}/"
        
        # List all objects under the folder prefix
        objects = self.client.list_objects(bucket, prefix=src_p, recursive=True)
        count = 0
        for obj in objects:
            rel_path = obj.object_name.replace(src_p, "", 1)
            dest_key = f"{dest_p}{rel_path}"
            self.copy_object(obj.object_name, dest_key)
            count += 1
        
        logger.info(f"Copied folder content ({count} objects) from {src_p} to {dest_p}")
    
    def move_prefix(self, src_prefix: str, dest_prefix: str):
        """Move all objects from one prefix to another (recursively), then delete source."""
        bucket = self._settings().minio_bucket
        
        # Determine if it's a file or folder before moving
        is_file = False
        try:
            self.client.stat_object(bucket, src_prefix)
            is_file = True
        except Exception:
            is_file = False

        self.copy_prefix(src_prefix, dest_prefix)
        
        if is_file:
            self.delete_object(src_prefix)
        else:
            # Delete folder with trailing slash to be safe
            src_p = src_prefix if src_prefix.endswith("/") else f"{src_prefix}/"
            self.delete_prefix(src_p)
            
        logger.info(f"Moved {src_prefix} to {dest_prefix}")

    def calculate_prefix_hash(self, prefix: str) -> str:
        """
        Calculate a unique hash for all objects under a prefix.
        Uses object names and ETags to detect any content or structure change.
        """
        import hashlib
        bucket = self._settings().minio_bucket
        p = prefix if prefix.endswith("/") else f"{prefix}/"
        
        objects = self.client.list_objects(bucket, prefix=p, recursive=True)
        # Sort objects by name to ensure stable hash
        sorted_objects = sorted(objects, key=lambda x: x.object_name)
        
        hasher = hashlib.sha256()
        for obj in sorted_objects:
            rel_path = obj.object_name.replace(p, "", 1)
            # Combine path and etag
            hasher.update(rel_path.encode("utf-8"))
            hasher.update(obj.etag.encode("utf-8"))
            
        return hasher.hexdigest()


# Singleton
storage_service = StorageService()
