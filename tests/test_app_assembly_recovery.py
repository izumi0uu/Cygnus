from __future__ import annotations

from fastapi.routing import APIRoute, Mount

from cygnus.runtime.config import Settings, get_settings
from cygnus.runtime.main import app, create_app


def test_backend_settings_provider_is_cached_and_parses_cors_list(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://boot:boot@localhost:5432/boot")
    monkeypatch.setenv("CORS_ORIGINS", "https://ops.cygnus.local, https://review.cygnus.local")

    get_settings.cache_clear()
    resolved = get_settings()

    assert resolved.database_url == "postgresql+asyncpg://boot:boot@localhost:5432/boot"
    assert resolved.cors_origin_list == [
        "https://ops.cygnus.local",
        "https://review.cygnus.local",
    ]
    assert get_settings() is resolved

    get_settings.cache_clear()


def test_backend_app_factory_exposes_boot_entry_with_settings_state() -> None:
    assembled = create_app()

    assert assembled.title == "Cygnus API"
    assert assembled.state.settings is not None

    http_routes = {route.path for route in assembled.routes if isinstance(route, APIRoute)}
    mount_routes = {route.path for route in assembled.routes if isinstance(route, Mount)}
    openapi_paths = set(assembled.openapi()["paths"])

    assert "/" in http_routes
    assert "/health" in http_routes
    assert "/api/health" in http_routes
    assert "/mcp" in mount_routes
    assert "/healthz" in openapi_paths
    assert "/api/command-center" in openapi_paths
    assert "/api/publish/apply" in openapi_paths
    assert "/api/auth/login" in openapi_paths
    assert "/api/auth/me" in openapi_paths


def test_module_level_app_uses_same_boot_contract() -> None:
    assert isinstance(app.state.settings, Settings)
    assert app.state.settings.database_url
    assert app.state.settings.cors_origin_list
