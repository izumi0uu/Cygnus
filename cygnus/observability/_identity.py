"""Runtime identity — sanitized release/build metadata.

Identity comes from environment variables and build-time labels, never from
hardcoded version strings:

- ``APP_RELEASE`` / ``CYGNUS_RELEASE`` — release/version (e.g. ``v1.2.3``)
- ``APP_COMMIT_SHA`` / ``CYGNUS_COMMIT_SHA`` / ``GIT_SHA`` — commit SHA
- ``APP_IMAGE_REF`` / ``CYGNUS_IMAGE_REF`` / ``IMAGE_REF`` — image digest/reference
- ``APP_ENVIRONMENT`` / ``CYGNUS_ENVIRONMENT`` — environment name
- ``APP_DEPLOYMENT_ID`` / ``CYGNUS_DEPLOYMENT_ID`` — deployment ID
- ``EXPECTED_ALEMBIC_HEAD`` — optional explicit override for the expected
  Alembic head; when absent the head is discovered from the migrations tree

Values are sanitized and truncated so they are safe as Prometheus labels and
audit metadata. The expected Alembic head is discovered via ``alembic`` so it
stays in sync with the migration chain instead of drifting.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from cygnus.observability._sanitize import sanitize_label_value

EXPECTED_ALEMBIC_HEAD_ENV = "EXPECTED_ALEMBIC_HEAD"

_IDENTITY_LABEL_MAX = 64


def _env(*names: str) -> Optional[str]:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _discover_alembic_head() -> Optional[str]:
    """Return the current head revision id from the runtime migration assets."""
    try:
        from pathlib import Path

        from alembic.config import Config
        from alembic.script import ScriptDirectory

        runtime_root = Path.cwd()
        source_root = Path(__file__).resolve().parents[2]
        for root in (runtime_root, source_root):
            config_path = root / "alembic.ini"
            migrations_path = root / "migrations"
            if not config_path.is_file() or not migrations_path.is_dir():
                continue
            config = Config(str(config_path))
            config.set_main_option("script_location", str(migrations_path))
            heads = ScriptDirectory.from_config(config).get_heads()
            if len(heads) == 1:
                return heads[0]
            return None  # ambiguous/branchy chain — do not guess
    except Exception:  # noqa: BLE001 — identity discovery must never raise
        return None
    return None


@lru_cache(maxsize=1)
def _cached_identity() -> dict[str, str]:
    release = _env("APP_RELEASE", "CYGNUS_RELEASE") or "unknown"
    commit_sha = _env("APP_COMMIT_SHA", "CYGNUS_COMMIT_SHA", "GIT_SHA") or "unknown"
    image_ref = _env("APP_IMAGE_REF", "CYGNUS_IMAGE_REF", "IMAGE_REF") or "unknown"
    environment = _env("APP_ENVIRONMENT", "CYGNUS_ENVIRONMENT") or "development"
    deployment_id = _env("APP_DEPLOYMENT_ID", "CYGNUS_DEPLOYMENT_ID") or "unknown"
    expected_head = _env(EXPECTED_ALEMBIC_HEAD_ENV) or _discover_alembic_head()
    if not expected_head:
        expected_head = "unknown"
    return {
        "release": sanitize_label_value(release, max_length=_IDENTITY_LABEL_MAX),
        "commit_sha": sanitize_label_value(commit_sha, max_length=_IDENTITY_LABEL_MAX),
        "image_ref": sanitize_label_value(image_ref, max_length=_IDENTITY_LABEL_MAX),
        "environment": sanitize_label_value(
            environment, max_length=_IDENTITY_LABEL_MAX
        ),
        "deployment_id": sanitize_label_value(
            deployment_id, max_length=_IDENTITY_LABEL_MAX
        ),
        "alembic_head": sanitize_label_value(
            expected_head, max_length=_IDENTITY_LABEL_MAX
        ),
    }


def runtime_identity(*, refresh: bool = False) -> dict[str, str]:
    """Return sanitized runtime identity.

    ``refresh=True`` clears the cache (useful in tests or after env changes).
    """
    if refresh:
        _cached_identity.cache_clear()
    return dict(_cached_identity())


def reset_runtime_identity_cache() -> None:
    """Test/ops helper: drop the cached identity so env changes apply."""
    _cached_identity.cache_clear()
