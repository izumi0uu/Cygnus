from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.domain import AudienceFilter, Visibility
from cygnus.governance.audience_bindings import (
    AudienceBindingConflict,
    AudienceBindingCreate,
    AudienceBindingLifecycle,
    audience_filters_overlap,
    create_audience_binding,
    detect_audience_binding_conflicts,
    list_audience_bindings,
    publish_conflicts_from_records,
    update_audience_binding_lifecycle,
)
from cygnus.publish import persisted_publish_candidate_for_signal
from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import (
    GovernanceAudienceBinding,
    GovernanceSignal,
    WikiPage,
)
from cygnus.runtime.main import app
from cygnus.runtime.routers.governance import audience_bindings as bindings_router
from cygnus.runtime.services.auth_service import require_admin


_NOW = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
_PAGE_ID = uuid.uuid4()
_ACTOR_ID = uuid.uuid4()


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self.value: object = value

    def scalar_one_or_none(self) -> object:
        return self.value

    def scalars(self) -> _ScalarResult:
        return self

    def all(self) -> list[object]:
        return list(cast(tuple[object, ...], self.value))


def _binding(
    *,
    variant_ref: str,
    binding_key: str,
    visibility: str = "external",
    channel: str = "help_center",
    plans: tuple[str, ...] = (),
    regions: tuple[str, ...] = ("eu",),
    lifecycle_state: str = "active",
) -> GovernanceAudienceBinding:
    return GovernanceAudienceBinding(
        id=uuid.uuid4(),
        page_id=_PAGE_ID,
        object_ref="ko-billing-policy",
        variant_ref=variant_ref,
        channel=channel,
        visibility=visibility,
        brands=[],
        product_lines=["billing"],
        plans=list(plans),
        regions=list(regions),
        languages=[],
        product_versions=[],
        lifecycle_state=lifecycle_state,
        binding_key=binding_key,
        created_by_id=_ACTOR_ID,
        created_at=_NOW,
        updated_at=_NOW,
        version=1,
    )


def _session(*, execute_value: object, page: object | None = None) -> AsyncSession:
    fake = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(execute_value)),
        get=AsyncMock(return_value=page),
        add=MagicMock(),
        flush=AsyncMock(),
    )
    return cast(AsyncSession, cast(object, fake))


class AudienceBindingServiceTests(unittest.TestCase):
    def test_binding_command_canonicalizes_dimensions_and_key(self) -> None:
        left = AudienceBindingCreate(
            page_id=_PAGE_ID,
            object_ref=" ko-billing-policy ",
            variant_ref=" enterprise-eu ",
            channel=" help_center ",
            audience_filter=AudienceFilter(
                visibility=Visibility.EXTERNAL,
                product_lines=("billing", " billing "),
                plans=("enterprise",),
                regions=("eu",),
            ),
        )
        right = AudienceBindingCreate(
            page_id=_PAGE_ID,
            object_ref="ko-billing-policy",
            variant_ref="enterprise-eu",
            channel="help_center",
            audience_filter=AudienceFilter(
                visibility=Visibility.EXTERNAL,
                product_lines=("billing",),
                plans=("enterprise",),
                regions=("eu",),
            ),
        )

        self.assertEqual(left, right)
        self.assertEqual(left.binding_key, right.binding_key)
        self.assertEqual(left.audience_filter.product_lines, ("billing",))

    def test_create_persists_exact_binding_and_replays_same_key(self) -> None:
        command = AudienceBindingCreate(
            page_id=_PAGE_ID,
            object_ref="ko-billing-policy",
            variant_ref="enterprise-eu",
            channel="help_center",
            audience_filter=AudienceFilter(
                visibility=Visibility.EXTERNAL,
                product_lines=("billing",),
                plans=("enterprise",),
                regions=("eu",),
            ),
        )
        session = _session(
            execute_value=None,
            page=SimpleNamespace(id=_PAGE_ID, slug="billing-policy"),
        )

        with patch(
            "cygnus.governance.audience_bindings.lock_governance_command",
            AsyncMock(return_value=None),
        ):
            record, replayed = asyncio.run(
                create_audience_binding(
                    session,
                    command=command,
                    actor_id=_ACTOR_ID,
                )
            )

        self.assertFalse(replayed)
        self.assertEqual(record.binding_key, command.binding_key)
        self.assertEqual(record.plans, ["enterprise"])
        cast(MagicMock, session.add).assert_called_once_with(record)
        cast(AsyncMock, session.flush).assert_awaited_once()

        replay_session = _session(execute_value=record)
        with patch(
            "cygnus.governance.audience_bindings.lock_governance_command",
            AsyncMock(return_value=None),
        ):
            replay, replayed = asyncio.run(
                create_audience_binding(
                    replay_session,
                    command=command,
                    actor_id=uuid.uuid4(),
                )
            )
        self.assertIs(replay, record)
        self.assertTrue(replayed)
        cast(MagicMock, replay_session.add).assert_not_called()

    def test_create_rejects_object_ref_that_does_not_identify_page(self) -> None:
        command = AudienceBindingCreate(
            page_id=_PAGE_ID,
            object_ref="ko-other-page",
            variant_ref="enterprise-eu",
            channel="help_center",
            audience_filter=AudienceFilter(visibility=Visibility.EXTERNAL),
        )
        session = _session(
            execute_value=None,
            page=SimpleNamespace(id=_PAGE_ID, slug="billing-policy"),
        )

        with patch(
            "cygnus.governance.audience_bindings.lock_governance_command",
            AsyncMock(return_value=None),
        ):
            with self.assertRaises(AudienceBindingConflict):
                asyncio.run(
                    create_audience_binding(
                        session,
                        command=command,
                        actor_id=_ACTOR_ID,
                    )
                )

    def test_overlap_detection_uses_wildcards_and_ignores_inactive_bindings(self) -> None:
        broad = _binding(variant_ref="broad", binding_key="broad")
        enterprise = _binding(
            variant_ref="enterprise",
            binding_key="enterprise",
            plans=("enterprise",),
        )
        other_region = _binding(
            variant_ref="us",
            binding_key="us",
            regions=("us",),
        )
        internal = _binding(
            variant_ref="internal",
            binding_key="internal",
            visibility="internal",
        )
        held = _binding(
            variant_ref="held",
            binding_key="held",
            plans=("enterprise",),
            lifecycle_state="held",
        )

        self.assertTrue(
            audience_filters_overlap(
                AudienceFilter(visibility=Visibility.EXTERNAL),
                AudienceFilter(
                    visibility=Visibility.EXTERNAL,
                    plans=("enterprise",),
                ),
            )
        )
        conflicts = detect_audience_binding_conflicts(
            (broad, enterprise, other_region, internal, held)
        )
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(
            {conflicts[0].left.variant_ref, conflicts[0].right.variant_ref},
            {"broad", "enterprise"},
        )
        blocked = publish_conflicts_from_records((broad, enterprise))
        self.assertEqual(len(blocked), 2)
        self.assertEqual({item.channel for item in blocked}, {"help_center"})

    def test_lifecycle_update_is_versioned_and_exact_retry_is_idempotent(self) -> None:
        record = _binding(variant_ref="enterprise", binding_key="enterprise")
        session = _session(execute_value=record)

        updated, replayed = asyncio.run(
            update_audience_binding_lifecycle(
                session,
                binding_id=record.id,
                lifecycle_state=AudienceBindingLifecycle.HELD,
                expected_version=1,
            )
        )
        self.assertIs(updated, record)
        self.assertFalse(replayed)
        self.assertEqual(record.lifecycle_state, "held")
        self.assertEqual(record.version, 2)

        replay, replayed = asyncio.run(
            update_audience_binding_lifecycle(
                session,
                binding_id=record.id,
                lifecycle_state=AudienceBindingLifecycle.HELD,
                expected_version=1,
            )
        )
        self.assertIs(replay, record)
        self.assertTrue(replayed)
        with self.assertRaises(AudienceBindingConflict):
            asyncio.run(
                update_audience_binding_lifecycle(
                    session,
                    binding_id=record.id,
                    lifecycle_state=AudienceBindingLifecycle.REMOVED,
                    expected_version=1,
                )
            )

    def test_list_applies_wiki_scope_inside_sql(self) -> None:
        session = _session(execute_value=())
        rows = asyncio.run(
            list_audience_bindings(
                session,
                object_ref="ko-billing-policy",
                page_scope_clause=WikiPage.id.is_(None),
            )
        )
        await_args = cast(AsyncMock, session.execute).await_args
        if await_args is None:
            raise AssertionError("binding list did not execute a scoped query")
        statement = await_args.args[0]
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertEqual(rows, ())
        self.assertIn("JOIN wiki_pages", sql)
        self.assertIn("wiki_pages.id IS NULL", sql)
        self.assertIn("ko-billing-policy", sql)

    def test_publish_candidate_comes_only_from_persisted_active_bindings(self) -> None:
        binding = _binding(
            variant_ref="enterprise",
            binding_key="enterprise",
            plans=("enterprise",),
        )
        page = SimpleNamespace(
            id=_PAGE_ID,
            slug="billing-policy",
            title="Billing policy",
            summary="Governed billing policy.",
            content_md="# Billing policy\n\nGoverned billing policy.",
            knowledge_type_slugs=["answer_card"],
            status="approved",
        )
        signal = cast(
            GovernanceSignal,
            cast(
                object,
                SimpleNamespace(
                    page_id=_PAGE_ID,
                    status="active",
                    object_ref="ko-billing-policy",
                ),
            ),
        )
        session = _session(execute_value=(), page=page)
        with (
            patch(
                "cygnus.publish.durable.list_audience_bindings",
                AsyncMock(return_value=(binding,)),
            ),
            patch(
                "cygnus.publish.durable.latest_publication_for_object",
                AsyncMock(return_value=None),
            ),
        ):
            candidate = asyncio.run(
                persisted_publish_candidate_for_signal(
                    session,
                    signal=signal,
                )
            )
        if candidate is None:
            raise AssertionError("active persisted binding must produce a candidate")
        self.assertEqual(candidate.action_type.value, "publish")
        self.assertEqual(candidate.target_channels, ("help_center",))
        self.assertEqual(candidate.target_audiences[0].plans, ("enterprise",))

        with patch(
            "cygnus.publish.durable.list_audience_bindings",
            AsyncMock(return_value=()),
        ):
            missing = asyncio.run(
                persisted_publish_candidate_for_signal(
                    session,
                    signal=signal,
                )
            )
        self.assertIsNone(missing)


class AudienceBindingApiTests(unittest.TestCase):
    startup_patches: list[Any]
    client: TestClient
    admin: SimpleNamespace
    def setUp(self) -> None:
        self.startup_patches = [
            patch(
                "cygnus.runtime.main.seed_default_admin",
                AsyncMock(return_value=None),
            ),
            patch(
                "cygnus.runtime.services.storage_service.storage_service.ensure_bucket",
                AsyncMock(return_value=None),
            ),
            patch(
                "cygnus.runtime.bootstrap.seed_builtin_skills.seed_builtin_skills",
                AsyncMock(return_value=None),
            ),
        ]
        for patcher in self.startup_patches:
            patcher.start()
        self.client = TestClient(app)
        self.admin = SimpleNamespace(id=_ACTOR_ID, role="admin")
        app.dependency_overrides[get_db] = lambda: AsyncMock()

    def tearDown(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()
        for patcher in reversed(self.startup_patches):
            patcher.stop()

    def enable_admin(self) -> None:
        app.dependency_overrides[require_admin] = lambda: self.admin

    def test_binding_api_is_admin_gated(self) -> None:
        payload = {
            "page_id": str(_PAGE_ID),
            "object_ref": "ko-billing-policy",
            "variant_ref": "enterprise-eu",
            "channel": "help_center",
            "visibility": "external",
            "product_lines": ["billing"],
            "plans": ["enterprise"],
            "regions": ["eu"],
        }
        self.assertEqual(
            self.client.get("/api/governance/audience-bindings").status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                "/api/governance/audience-bindings",
                json=payload,
            ).status_code,
            401,
        )

    def test_create_and_list_expose_conflict_provider_truth(self) -> None:
        self.enable_admin()
        broad = _binding(variant_ref="broad", binding_key="broad")
        enterprise = _binding(
            variant_ref="enterprise",
            binding_key="enterprise",
            plans=("enterprise",),
        )
        payload = {
            "page_id": str(_PAGE_ID),
            "object_ref": "ko-billing-policy",
            "variant_ref": "broad",
            "channel": "help_center",
            "visibility": "external",
            "product_lines": ["billing"],
            "regions": ["eu"],
        }
        with (
            patch.object(
                bindings_router,
                "create_audience_binding",
                AsyncMock(return_value=(broad, False)),
            ),
            patch.object(
                bindings_router,
                "list_audience_bindings",
                AsyncMock(return_value=(broad, enterprise)),
            ),
        ):
            created = self.client.post(
                "/api/governance/audience-bindings",
                json=payload,
            )
            listed = self.client.get("/api/governance/audience-bindings")

        self.assertEqual(created.status_code, 201)
        self.assertFalse(created.json()["replayed"])
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["observed_count"], 1)
        self.assertEqual(listed.json()["covered_signals"], ["audience_conflict"])
        self.assertEqual(len(listed.json()["conflicts"]), 1)


if __name__ == "__main__":
    unittest.main()
