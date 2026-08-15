from __future__ import annotations

import asyncio
import uuid
import unittest
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.integrations.governed_publish_tools import (
    GovernedPublishTools,
    publish_tool_bindings,
    publish_tool_definitions,
)
from cygnus.publish import DurablePublishCommand
from cygnus.runtime.database.models import WikiPage, WikiPageDraft


class _PolicySession:
    def __init__(self, *, draft: object | None, page: object | None) -> None:
        self._draft = draft
        self._page = page

    async def get(self, model: object, _identifier: object) -> object | None:
        if model is WikiPageDraft:
            return self._draft
        if model is WikiPage:
            return self._page
        raise AssertionError(f"unexpected model lookup: {model}")


class GovernedPublishToolTests(unittest.TestCase):
    def _tools(
        self,
        *,
        draft: object | None = None,
        page: object | None = None,
        is_admin: bool = True,
        visible_object_ids: tuple[str, ...] = ("ko-visible",),
    ) -> GovernedPublishTools:
        return GovernedPublishTools(
            cast(AsyncSession, cast(object, _PolicySession(draft=draft, page=page))),
            actor_id=uuid.uuid4(),
            is_admin=is_admin,
            visible_object_ids=visible_object_ids,
        )

    def test_definitions_bind_only_the_ready_durable_write_slice(self) -> None:
        definitions = publish_tool_definitions()
        self.assertEqual(
            [(item.name, item.risk_level) for item in definitions],
            [
                ("validate_publish_policy", "R2"),
                ("publish_knowledge_object", "R3"),
            ],
        )
        bindings = publish_tool_bindings(self._tools())
        self.assertEqual(
            [definition.name for definition, _handler in bindings],
            ["validate_publish_policy", "publish_knowledge_object"],
        )

    def test_invalid_and_hidden_drafts_return_the_same_safe_shape(self) -> None:
        invalid = asyncio.run(
            self._tools().validate_publish_policy(
                draft_id="not-a-uuid",
                target_channel="internal-copilot",
            )
        )
        self.assertEqual(invalid["status"], "invalid")
        self.assertEqual(invalid["errors"], ["invalid_arguments"])

        draft_id = uuid.uuid4()
        page_id = uuid.uuid4()
        draft = SimpleNamespace(id=draft_id, page_id=page_id, status="approved")
        page = SimpleNamespace(id=page_id, version=3, source_ids=[])
        hidden_tools = self._tools(
            draft=draft,
            page=page,
            is_admin=False,
            visible_object_ids=(),
        )
        with patch(
            "cygnus.integrations.governed_publish_tools.wiki_page_to_knowledge_object",
            return_value=SimpleNamespace(object_id="ko-hidden"),
        ):
            hidden = asyncio.run(
                hidden_tools.validate_publish_policy(
                    draft_id=str(draft_id),
                    target_channel="internal-copilot",
                )
            )

        self.assertEqual(hidden["status"], "not_found")
        self.assertEqual(hidden["data"], {})
        self.assertNotIn("ko-hidden", hidden["summary"])

    def test_stale_version_and_unapproved_draft_are_structured(self) -> None:
        draft_id = uuid.uuid4()
        page_id = uuid.uuid4()
        page = SimpleNamespace(id=page_id, version=4, source_ids=[])
        knowledge_object = SimpleNamespace(object_id="ko-visible")

        approved = SimpleNamespace(id=draft_id, page_id=page_id, status="approved")
        with patch(
            "cygnus.integrations.governed_publish_tools.wiki_page_to_knowledge_object",
            return_value=knowledge_object,
        ):
            stale = asyncio.run(
                self._tools(draft=approved, page=page).validate_publish_policy(
                    draft_id=str(draft_id),
                    target_channel="internal-copilot",
                    expected_version=3,
                )
            )
        self.assertEqual(stale["status"], "conflict")
        self.assertEqual(stale["errors"], ["stale_version"])
        self.assertEqual(stale["data"]["object_version"], 4)

        pending = SimpleNamespace(id=draft_id, page_id=page_id, status="pending")
        with patch(
            "cygnus.integrations.governed_publish_tools.wiki_page_to_knowledge_object",
            return_value=knowledge_object,
        ):
            unapproved = asyncio.run(
                self._tools(draft=pending, page=page).validate_publish_policy(
                    draft_id=str(draft_id),
                    target_channel="internal-copilot",
                    expected_version=4,
                )
            )
        self.assertEqual(unapproved["status"], "approval_required")
        self.assertEqual(unapproved["errors"], ["approval_required"])

    def test_non_admin_publish_is_denied_before_resource_lookup(self) -> None:
        result = asyncio.run(
            self._tools(is_admin=False).publish_knowledge_object(
                draft_id=str(uuid.uuid4()),
                approval_ref=str(uuid.uuid4()),
                approval_digest="a" * 64,
                scope_digest="b" * 64,
                signal_id=str(uuid.uuid4()),
                signal_freshness="fresh",
                command_id="publish-command",
                action_key="publish",
                target_channels=["internal-copilot"],
                expected_version=1,
            )
        )
        self.assertEqual(result["status"], "denied")
        self.assertEqual(result["errors"], ["admin_required"])
        self.assertEqual(result["data"], {})

    def test_publish_preserves_durable_replay_and_propagation_truth(self) -> None:
        draft_id = uuid.uuid4()
        approval_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        durable_result = {
            "persisted": True,
            "rehearsal": False,
            "replayed": True,
            "publication_record_id": str(uuid.uuid4()),
            "ledger_event_id": str(uuid.uuid4()),
            "approval_ref": str(approval_id),
            "command_id": "publish-command",
            "object_ref": "ko-visible",
            "object_version": 7,
            "published_at": "2026-08-10T00:00:00+00:00",
            "propagation": {
                "summary": {"pending": 1},
                "records": [{"surface_id": "internal-copilot", "status": "pending"}],
            },
        }
        apply = AsyncMock(return_value=durable_result)
        tools = GovernedPublishTools(
            cast(AsyncSession, cast(object, _PolicySession(draft=None, page=None))),
            actor_id=actor_id,
            is_admin=True,
            visible_object_ids=("ko-visible",),
        )

        with patch(
            "cygnus.integrations.governed_publish_tools.apply_durable_publish",
            apply,
        ):
            result = asyncio.run(
                tools.publish_knowledge_object(
                    draft_id=str(draft_id),
                    approval_ref=str(approval_id),
                    approval_digest="a" * 64,
                    scope_digest="b" * 64,
                    signal_id=str(uuid.uuid4()),
                    signal_freshness="fresh",
                    command_id="publish-command",
                    action_key="publish",
                    target_channels=["internal-copilot"],
                    expected_version=7,
                )
            )

        self.assertTrue(result["persisted"])
        self.assertFalse(result["rehearsal"])
        self.assertTrue(result["replayed"])
        self.assertEqual(
            result["publication_record_id"], durable_result["publication_record_id"]
        )
        self.assertEqual(result["warnings"], ["downstream_propagation_pending"])
        call = apply.await_args
        self.assertIsNotNone(call)
        if call is None:
            raise AssertionError("durable publish was not called")
        command = cast(DurablePublishCommand, call.kwargs["command"])
        self.assertEqual(command.expected_version, 7)
        self.assertEqual(command.approval_ref, approval_id)
        self.assertEqual(command.approval_digest, "a" * 64)
        self.assertEqual(command.scope_digest, "b" * 64)
        self.assertEqual(command.signal_freshness, "fresh")
        self.assertEqual(call.kwargs["actor_id"], actor_id)


if __name__ == "__main__":
    unittest.main()
