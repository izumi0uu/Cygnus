"""
Admin model-selection router for LLM and Vision capabilities.

Endpoints:
  GET  /api/settings/llm/catalog       — supported LLM models + active spec
  POST /api/settings/llm/switch        — set the active LLM spec
  GET  /api/settings/vision/catalog    — supported vision models + active spec
  POST /api/settings/vision/switch     — set the active vision spec

Mirrors the embedding catalog endpoints in admin_embeddings.py so the
settings UI can use the same dropdown pattern for all three capabilities.
"""

from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.backend.database import get_db
from cygnus.backend.database.models import Employee
from cygnus.backend.services.audit_service import log_audit
from cygnus.backend.services.auth_service import require_permission

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class LLMSpecOut(BaseModel):
    id: str
    provider: str
    model_id: str
    context_window_tokens: int
    max_output_tokens: int
    supports_tools: bool
    supports_vision: bool
    label: str
    cost_per_1m_input_tokens: Optional[float]
    cost_per_1m_output_tokens: Optional[float]
    notes: Optional[str]
    api_key_configured: bool


class CustomLLMConfigOut(BaseModel):
    enabled: bool
    provider: str
    model_id: str
    base_url: str
    api_key_configured: bool
    context_window_tokens: int
    max_output_tokens: int
    reasoning_effort: Optional[str]
    has_any_value: bool


class LLMCatalogOut(BaseModel):
    active_spec_id: Optional[str]
    active_mode: str
    specs: list[LLMSpecOut]
    custom: CustomLLMConfigOut


class VisionSpecOut(BaseModel):
    id: str
    provider: str
    model_id: str
    max_image_size_mb: int
    label: str
    cost_per_1m_input_tokens: Optional[float]
    cost_per_image: Optional[float]
    notes: Optional[str]
    api_key_configured: bool


class VisionCatalogOut(BaseModel):
    active_spec_id: Optional[str]
    specs: list[VisionSpecOut]


class SwitchBody(BaseModel):
    model_spec_id: str


class CustomLLMBody(BaseModel):
    provider: str
    model_id: str
    base_url: str
    api_key: str = ""
    context_window_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    reasoning_effort: Optional[str] = None


class CustomLLMTestBody(BaseModel):
    provider: str
    base_url: str
    api_key: str = ""
    model_id: Optional[str] = None
    reasoning_effort: Optional[str] = None


class CustomLLMTestResult(BaseModel):
    success: bool
    message: str
    normalized_base_url: str
    models: list[str]


def _looks_like_saved_secret_mask(value: str) -> bool:
    return value.startswith("••••")


def _supports_reasoning_effort(provider: str, model_id: str) -> bool:
    return provider == "openai" and model_id.strip().lower().startswith("gpt")


def _normalize_custom_base_url(base_url: str, provider: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        raise HTTPException(status_code=400, detail="Base URL is required.")

    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(
            status_code=400,
            detail="Base URL must be a valid http:// or https:// URL.",
        )
    if provider in {"openai", "anthropic"} and parsed.path in {"", "/"}:
        normalized = f"{normalized}/v1"
    return normalized


def _normalize_reasoning_effort(
    provider: str,
    model_id: str,
    reasoning_effort: Optional[str],
    *,
    strict: bool,
) -> Optional[str]:
    from cygnus.backend.ai.registry import CUSTOM_LLM_REASONING_EFFORTS

    if reasoning_effort is None:
        return None

    normalized = reasoning_effort.strip().lower()
    if not normalized:
        return None

    if normalized not in CUSTOM_LLM_REASONING_EFFORTS:
        raise HTTPException(
            status_code=400,
            detail=(
                "Reasoning effort must be one of: "
                "none, minimal, low, medium, high, xhigh."
            ),
        )

    if _supports_reasoning_effort(provider, model_id):
        return normalized

    if strict:
        raise HTTPException(
            status_code=400,
            detail="Reasoning effort is only supported for GPT custom relays.",
        )
    return None


def _custom_llm_out(custom) -> CustomLLMConfigOut:
    return CustomLLMConfigOut(
        enabled=custom.enabled,
        provider=custom.provider,
        model_id=custom.model_id,
        base_url=custom.base_url,
        api_key_configured=bool(custom.api_key),
        context_window_tokens=custom.context_window_tokens,
        max_output_tokens=custom.max_output_tokens,
        reasoning_effort=custom.reasoning_effort,
        has_any_value=custom.has_any_value,
    )


async def _list_openai_compatible_models(base_url: str, api_key: str) -> list[str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f"{base_url}/models", headers=headers)
        response.raise_for_status()
        payload = response.json()

    models = payload.get("data", [])
    out = sorted(
        {
            item.get("id", "").strip()
            for item in models
            if isinstance(item, dict) and item.get("id")
        }
    )
    return [model_id for model_id in out if model_id]


async def _list_anthropic_compatible_models(base_url: str, api_key: str) -> list[str]:
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    if api_key:
        headers["x-api-key"] = api_key

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f"{base_url}/models", headers=headers)
        response.raise_for_status()
        payload = response.json()

    models = payload.get("data", [])
    out = sorted(
        {
            item.get("id", "").strip()
            for item in models
            if isinstance(item, dict) and item.get("id")
        }
    )
    return [model_id for model_id in out if model_id]


async def _ping_openai_compatible_model(
    base_url: str,
    api_key: str,
    model_id: str,
    reasoning_effort: Optional[str],
) -> str:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body: dict = {
        "model": model_id,
        "messages": [{"role": "user", "content": "Reply with OK"}],
        "max_tokens": 16,
        "temperature": 0,
    }
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=body,
        )
        response.raise_for_status()
        payload = response.json()

    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    return str(message.get("content") or "").strip()


async def _ping_anthropic_compatible_model(
    base_url: str,
    api_key: str,
    model_id: str,
) -> str:
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    if api_key:
        headers["x-api-key"] = api_key

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{base_url}/messages",
            headers=headers,
            json={
                "model": model_id,
                "max_tokens": 16,
                "temperature": 0,
                "messages": [{"role": "user", "content": "Reply with OK"}],
            },
        )
        response.raise_for_status()
        payload = response.json()

    content = payload.get("content") or []
    if not content:
        return ""
    first = content[0]
    if isinstance(first, dict):
        return str(first.get("text") or "").strip()
    return ""


# ---------------------------------------------------------------------------
# LLM endpoints
# ---------------------------------------------------------------------------

@router.get("/settings/llm/catalog", response_model=LLMCatalogOut)
async def get_llm_catalog(
    db: AsyncSession = Depends(get_db),
    _user: Employee = require_permission("org:settings:manage"),
):
    from cygnus.backend.ai.llm_catalog import list_specs
    from cygnus.backend.ai.registry import ProviderRegistry
    from cygnus.backend.services.config_service import ConfigService

    registry = ProviderRegistry(db)
    active = await registry.get_active_llm_spec_id()
    custom = await registry.get_custom_llm_settings()
    svc = ConfigService(db)
    api_key_configured = bool(await svc.get("llm_api_key"))

    specs = [
        LLMSpecOut(
            id=s.id,
            provider=s.provider,
            model_id=s.model_id,
            context_window_tokens=s.context_window_tokens,
            max_output_tokens=s.max_output_tokens,
            supports_tools=s.supports_tools,
            supports_vision=s.supports_vision,
            label=s.label,
            cost_per_1m_input_tokens=s.cost_per_1m_input_tokens,
            cost_per_1m_output_tokens=s.cost_per_1m_output_tokens,
            notes=s.notes,
            api_key_configured=api_key_configured,
        )
        for s in list_specs()
    ]
    return LLMCatalogOut(
        active_spec_id=active,
        active_mode="custom" if custom.enabled else "catalog",
        specs=specs,
        custom=_custom_llm_out(custom),
    )


@router.post("/settings/llm/switch")
async def switch_llm_model(
    body: SwitchBody,
    db: AsyncSession = Depends(get_db),
    _user: Employee = require_permission("org:settings:manage"),
):
    from cygnus.backend.ai.llm_catalog import UnknownLLMModel, get_spec
    from cygnus.backend.services.config_service import (
        ACTIVE_LLM_MODEL_KEY,
        LLM_CUSTOM_ENABLED_KEY,
        ConfigService,
    )

    try:
        spec = get_spec(body.model_spec_id)
    except UnknownLLMModel as e:
        raise HTTPException(status_code=400, detail=str(e))

    svc = ConfigService(db)
    if not await svc.get("llm_api_key"):
        raise HTTPException(
            status_code=400,
            detail="No LLM API key configured. Save the API key first, then switch.",
        )

    await svc.set(ACTIVE_LLM_MODEL_KEY, spec.id)
    await svc.set(LLM_CUSTOM_ENABLED_KEY, "false")
    await log_audit(
        db, _user, "switch_llm_model", "settings", "global",
        reason=f"Switching active LLM to {spec.id}",
    )
    await db.commit()
    return {"active_spec_id": spec.id}


@router.post("/settings/llm/custom/test", response_model=CustomLLMTestResult)
async def test_custom_llm(
    body: CustomLLMTestBody,
    db: AsyncSession = Depends(get_db),
    _user: Employee = require_permission("org:settings:manage"),
):
    from cygnus.backend.ai.registry import CUSTOM_LLM_PROVIDER_IDS
    from cygnus.backend.services.config_service import LLM_CUSTOM_API_KEY, ConfigService

    provider = body.provider.strip().lower()
    if provider not in CUSTOM_LLM_PROVIDER_IDS:
        raise HTTPException(
            status_code=400,
            detail="Custom LLM provider must be openai or anthropic.",
        )

    normalized_base_url = _normalize_custom_base_url(body.base_url, provider)
    svc = ConfigService(db)
    raw_api_key = body.api_key.strip()
    api_key = (
        await svc.get(LLM_CUSTOM_API_KEY)
        if _looks_like_saved_secret_mask(raw_api_key)
        else raw_api_key
    ) or ""

    model_id = (body.model_id or "").strip()
    reasoning_effort = _normalize_reasoning_effort(
        provider,
        model_id,
        body.reasoning_effort,
        strict=False,
    )

    try:
        if provider == "openai":
            models = await _list_openai_compatible_models(normalized_base_url, api_key)
            if model_id:
                preview = await _ping_openai_compatible_model(
                    normalized_base_url,
                    api_key,
                    model_id,
                    reasoning_effort,
                )
                message = (
                    f"Connection OK. Found {len(models)} models. "
                    f"{model_id} replied with: {preview or 'OK'}"
                )
            else:
                message = f"Connection OK. Found {len(models)} models."
        else:
            models = await _list_anthropic_compatible_models(normalized_base_url, api_key)
            if model_id:
                preview = await _ping_anthropic_compatible_model(
                    normalized_base_url,
                    api_key,
                    model_id,
                )
                message = (
                    f"Connection OK. Found {len(models)} models. "
                    f"{model_id} replied with: {preview or 'OK'}"
                )
            else:
                message = f"Connection OK. Found {len(models)} models."
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text.strip() or str(exc)
        raise HTTPException(
            status_code=400,
            detail=f"Custom relay test failed: {detail}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Custom relay test failed: {exc}",
        ) from exc

    return CustomLLMTestResult(
        success=True,
        message=message,
        normalized_base_url=normalized_base_url,
        models=models,
    )


@router.post("/settings/llm/custom", response_model=CustomLLMConfigOut)
async def save_custom_llm(
    body: CustomLLMBody,
    db: AsyncSession = Depends(get_db),
    _user: Employee = require_permission("org:settings:manage"),
):
    from cygnus.backend.ai.registry import (
        CUSTOM_LLM_PROVIDER_IDS,
        DEFAULT_CUSTOM_LLM_CONTEXT_WINDOW_TOKENS,
        DEFAULT_CUSTOM_LLM_MAX_OUTPUT_TOKENS,
        ProviderRegistry,
    )
    from cygnus.backend.services.config_service import (
        LLM_CUSTOM_API_KEY,
        LLM_CUSTOM_BASE_URL_KEY,
        LLM_CUSTOM_CONTEXT_WINDOW_KEY,
        LLM_CUSTOM_ENABLED_KEY,
        LLM_CUSTOM_MAX_OUTPUT_KEY,
        LLM_CUSTOM_MODEL_ID_KEY,
        LLM_CUSTOM_PROVIDER_KEY,
        LLM_CUSTOM_REASONING_EFFORT_KEY,
        ConfigService,
    )

    provider = body.provider.strip().lower()
    if provider not in CUSTOM_LLM_PROVIDER_IDS:
        raise HTTPException(
            status_code=400,
            detail="Custom LLM provider must be openai or anthropic.",
        )

    model_id = body.model_id.strip()
    if not model_id:
        raise HTTPException(status_code=400, detail="Model ID is required.")

    base_url = _normalize_custom_base_url(body.base_url, provider)
    context_window_tokens = body.context_window_tokens or DEFAULT_CUSTOM_LLM_CONTEXT_WINDOW_TOKENS
    max_output_tokens = body.max_output_tokens or DEFAULT_CUSTOM_LLM_MAX_OUTPUT_TOKENS
    reasoning_effort = _normalize_reasoning_effort(
        provider,
        model_id,
        body.reasoning_effort,
        strict=True,
    )

    if context_window_tokens <= 0 or max_output_tokens <= 0:
        raise HTTPException(
            status_code=400,
            detail="Context window and max output tokens must be positive integers.",
        )

    svc = ConfigService(db)
    raw_api_key = body.api_key.strip()
    api_key = (
        await svc.get(LLM_CUSTOM_API_KEY)
        if _looks_like_saved_secret_mask(raw_api_key)
        else raw_api_key
    ) or ""

    await svc.set(LLM_CUSTOM_PROVIDER_KEY, provider)
    await svc.set(LLM_CUSTOM_MODEL_ID_KEY, model_id)
    await svc.set(LLM_CUSTOM_BASE_URL_KEY, base_url)
    await svc.set(LLM_CUSTOM_API_KEY, api_key)
    await svc.set(LLM_CUSTOM_CONTEXT_WINDOW_KEY, str(context_window_tokens))
    await svc.set(LLM_CUSTOM_MAX_OUTPUT_KEY, str(max_output_tokens))
    await svc.set(LLM_CUSTOM_REASONING_EFFORT_KEY, reasoning_effort or "")
    await svc.set(LLM_CUSTOM_ENABLED_KEY, "true")

    await log_audit(
        db,
        _user,
        "activate_custom_llm",
        "settings",
        "global",
        reason=f"Activated custom LLM relay {provider}:{model_id} via {base_url}",
    )
    await db.commit()

    registry = ProviderRegistry(db)
    custom = await registry.get_custom_llm_settings()
    return _custom_llm_out(custom)


@router.post("/settings/llm/custom/disable", response_model=CustomLLMConfigOut)
async def disable_custom_llm(
    db: AsyncSession = Depends(get_db),
    _user: Employee = require_permission("org:settings:manage"),
):
    from cygnus.backend.ai.registry import ProviderRegistry
    from cygnus.backend.services.config_service import LLM_CUSTOM_ENABLED_KEY, ConfigService

    svc = ConfigService(db)
    await svc.set(LLM_CUSTOM_ENABLED_KEY, "false")
    await log_audit(
        db,
        _user,
        "disable_custom_llm",
        "settings",
        "global",
        reason="Disabled custom LLM relay and reverted to catalog mode.",
    )
    await db.commit()

    registry = ProviderRegistry(db)
    custom = await registry.get_custom_llm_settings()
    return _custom_llm_out(custom)


# ---------------------------------------------------------------------------
# Vision endpoints
# ---------------------------------------------------------------------------

@router.get("/settings/vision/catalog", response_model=VisionCatalogOut)
async def get_vision_catalog(
    db: AsyncSession = Depends(get_db),
    _user: Employee = require_permission("org:settings:manage"),
):
    from cygnus.backend.ai.registry import ProviderRegistry
    from cygnus.backend.ai.vision_catalog import list_specs
    from cygnus.backend.services.config_service import ConfigService

    registry = ProviderRegistry(db)
    active = await registry.get_active_vision_spec_id()
    svc = ConfigService(db)
    api_key_configured = bool(await svc.get("vision_api_key"))

    specs = [
        VisionSpecOut(
            id=s.id,
            provider=s.provider,
            model_id=s.model_id,
            max_image_size_mb=s.max_image_size_mb,
            label=s.label,
            cost_per_1m_input_tokens=s.cost_per_1m_input_tokens,
            cost_per_image=s.cost_per_image,
            notes=s.notes,
            api_key_configured=api_key_configured,
        )
        for s in list_specs()
    ]
    return VisionCatalogOut(active_spec_id=active, specs=specs)


@router.post("/settings/vision/switch")
async def switch_vision_model(
    body: SwitchBody,
    db: AsyncSession = Depends(get_db),
    _user: Employee = require_permission("org:settings:manage"),
):
    from cygnus.backend.ai.vision_catalog import UnknownVisionModel, get_spec
    from cygnus.backend.services.config_service import ACTIVE_VISION_MODEL_KEY, ConfigService

    try:
        spec = get_spec(body.model_spec_id)
    except UnknownVisionModel as e:
        raise HTTPException(status_code=400, detail=str(e))

    svc = ConfigService(db)
    if not await svc.get("vision_api_key"):
        raise HTTPException(
            status_code=400,
            detail="No vision API key configured. Save the API key first, then switch.",
        )

    await svc.set(ACTIVE_VISION_MODEL_KEY, spec.id)
    await log_audit(
        db, _user, "switch_vision_model", "settings", "global",
        reason=f"Switching active vision model to {spec.id}",
    )
    await db.commit()
    return {"active_spec_id": spec.id}
