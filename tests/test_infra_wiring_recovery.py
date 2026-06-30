from __future__ import annotations

import hashlib
import hmac
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.config import Settings


class DatabaseWiringRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_database_runtime_provider_builds_engine_and_session_factory(self) -> None:
        import cygnus.runtime.database as database_module

        runtime_settings = Settings(
            database_url="postgresql+asyncpg://infra:secret@localhost:5432/cygnus_infra",
        )

        runtime_engine = database_module.create_engine_from_settings(runtime_settings)
        try:
            self.assertEqual(
                runtime_engine.url.render_as_string(hide_password=False),
                runtime_settings.database_url,
            )
            session_factory = database_module.create_session_factory(runtime_engine)
            self.assertIs(session_factory.kw["bind"], runtime_engine)
            self.assertIs(session_factory.class_, AsyncSession)
            self.assertIs(database_module.get_async_session_factory(), database_module.async_session_factory)
        finally:
            await runtime_engine.dispose()


class RedisWiringRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_sources_delegate_to_shared_worker_arq_pool(self) -> None:
        import cygnus.runtime.routers.sources as sources_module
        import cygnus.runtime.worker as worker_module

        fake_pool = object()
        fake_create_pool = AsyncMock(return_value=fake_pool)

        with (
            patch.object(worker_module, "_arq_pool", None),
            patch.object(worker_module, "create_pool", fake_create_pool),
        ):
            worker_pool = await worker_module.get_arq_pool()
            source_pool = await sources_module.get_arq_pool()

        self.assertIs(worker_pool, fake_pool)
        self.assertIs(source_pool, fake_pool)
        fake_create_pool.assert_awaited_once()


class StorageWiringRecoveryTests(unittest.TestCase):
    def test_storage_service_rebuilds_clients_from_explicit_settings_provider(self) -> None:
        from cygnus.runtime.services.storage_service import StorageService

        class _FakeMinio:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self._region_map: dict[str, str] = {}

        current_settings = Settings(
            minio_endpoint="minio.internal:9000",
            minio_public_endpoint="assets.cygnus.local",
            minio_access_key="infra-key",
            minio_secret_key="infra-secret",
            minio_bucket="cygnus-assets",
            minio_secure=False,
        )

        service = StorageService(
            settings_provider=lambda: current_settings,
            client_factory=_FakeMinio,
        )

        internal_client = service.client
        presign_client = service.presign_client

        self.assertEqual(internal_client.kwargs["endpoint"], "minio.internal:9000")
        self.assertFalse(internal_client.kwargs["secure"])
        self.assertEqual(presign_client.kwargs["endpoint"], "assets.cygnus.local")
        self.assertTrue(presign_client.kwargs["secure"])
        self.assertEqual(presign_client._region_map["cygnus-assets"], "us-east-1")

        current_settings = Settings(
            minio_endpoint="localhost:9000",
            minio_access_key="rotated-key",
            minio_secret_key="rotated-secret",
            minio_bucket="cygnus-files",
            minio_secure=False,
        )
        service.reset_clients()
        rebuilt_client = service.client

        self.assertIsNot(rebuilt_client, internal_client)
        self.assertEqual(rebuilt_client.kwargs["endpoint"], "localhost:9000")
        self.assertEqual(rebuilt_client.kwargs["access_key"], "rotated-key")


class OAuthAndNotificationWiringRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_notification_dispatch_pending_uses_database_session_provider(self) -> None:
        import cygnus.runtime.services.notification_service as notification_service

        staged = [object()]
        fake_session = object()

        class _SessionScope:
            async def __aenter__(self):
                return fake_session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class _SessionFactory:
            def __call__(self):
                return _SessionScope()

        with (
            patch.object(notification_service, "take_pending_dispatch", return_value=staged),
            patch("cygnus.runtime.database.get_async_session_factory", return_value=_SessionFactory()),
            patch("cygnus.integrations.notification_dispatch.dispatch_external", AsyncMock()) as dispatch_external,
        ):
            await notification_service.dispatch_pending()

        dispatch_external.assert_awaited_once_with(fake_session, staged)

    async def test_app_state_exposes_recovered_infra_wiring_contract(self) -> None:
        from cygnus.runtime.database import get_async_session_factory
        from cygnus.runtime.main import app
        from cygnus.runtime.services.storage_service import storage_service
        from cygnus.runtime.worker import get_arq_pool, get_redis_settings

        self.assertIs(app.state.session_factory, get_async_session_factory())
        self.assertIs(app.state.storage_service, storage_service)
        self.assertIs(app.state.get_arq_pool, get_arq_pool)
        self.assertEqual(app.state.redis_settings.host, get_redis_settings().host)

    async def test_mcp_token_hash_uses_runtime_settings_provider(self) -> None:
        from cygnus.runtime.services.mcp_auth_service import hash_token

        runtime_settings = Settings(mcp_token_pepper="pepper-cyg-54")
        token = "ark-runtime-token"
        expected = hmac.new(
            runtime_settings.mcp_token_pepper.encode("utf-8"),
            token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        with patch("cygnus.runtime.services.mcp_auth_service.get_settings", return_value=runtime_settings):
            self.assertEqual(hash_token(token), expected)


if __name__ == "__main__":
    unittest.main()
