from __future__ import annotations

import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from cygnus.runtime.database.models import SkillContributionStatus


class SkillContributionLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_skill_contribution_promotes_contributor_draft_to_pending(self) -> None:
        import cygnus.review.contributions as contribution_module

        contribution = types.SimpleNamespace(
            id=uuid.uuid4(),
            status=SkillContributionStatus.DRAFT.value,
            contributor_id=uuid.uuid4(),
            title="Billing escalation macro",
            revision_round=0,
            last_returned_note=None,
        )
        author = types.SimpleNamespace(
            id=contribution.contributor_id,
            role="member",
            name="Author",
            email="author@example.com",
        )

        with patch.object(contribution_module, "log_audit", AsyncMock()) as log_audit:
            await contribution_module.submit_skill_contribution(object(), contribution, author)

        self.assertEqual(contribution.status, SkillContributionStatus.PENDING.value)
        log_audit.assert_awaited_once()

    async def test_submit_skill_contribution_rejects_non_author(self) -> None:
        import cygnus.review.contributions as contribution_module

        contribution = types.SimpleNamespace(
            id=uuid.uuid4(),
            status=SkillContributionStatus.DRAFT.value,
            contributor_id=uuid.uuid4(),
            title="Billing escalation macro",
            revision_round=0,
            last_returned_note=None,
        )
        other_user = types.SimpleNamespace(
            id=uuid.uuid4(),
            role="member",
            name="Other",
            email="other@example.com",
        )

        with self.assertRaises(contribution_module.InvalidTransition):
            await contribution_module.submit_skill_contribution(object(), contribution, other_user)

    async def test_approve_skill_contribution_marks_terminal_approved(self) -> None:
        import cygnus.review.contributions as contribution_module

        contribution = types.SimpleNamespace(
            id=uuid.uuid4(),
            status=SkillContributionStatus.PENDING.value,
            contributor_id=uuid.uuid4(),
            title="Billing escalation macro",
            skill_id=None,
            revision_round=0,
            last_returned_note=None,
        )
        reviewer = types.SimpleNamespace(
            id=uuid.uuid4(),
            role="admin",
            name="Reviewer",
            email="reviewer@example.com",
        )
        skill = types.SimpleNamespace(id=uuid.uuid4(), current_version=3)

        with (
            patch("cygnus.runtime.services.skill_service.SkillService.materialize_approved_contribution", AsyncMock(return_value=skill)) as materialize,
            patch.object(contribution_module, "log_audit", AsyncMock()) as log_audit,
        ):
            result = await contribution_module.approve_skill_contribution(object(), contribution, reviewer)

        self.assertIs(result, skill)
        self.assertEqual(contribution.status, SkillContributionStatus.APPROVED.value)
        self.assertEqual(contribution.skill_id, skill.id)
        materialize.assert_awaited_once()
        log_audit.assert_awaited_once()

    async def test_reject_skill_contribution_marks_terminal_rejected(self) -> None:
        import cygnus.review.contributions as contribution_module

        contribution = types.SimpleNamespace(
            id=uuid.uuid4(),
            status=SkillContributionStatus.PENDING.value,
            contributor_id=uuid.uuid4(),
            title="Billing escalation macro",
            revision_round=0,
            last_returned_note=None,
        )
        reviewer = types.SimpleNamespace(
            id=uuid.uuid4(),
            role="admin",
            name="Reviewer",
            email="reviewer@example.com",
        )

        with patch.object(contribution_module, "log_audit", AsyncMock()) as log_audit:
            await contribution_module.reject_skill_contribution(object(), contribution, reviewer)

        self.assertEqual(contribution.status, SkillContributionStatus.REJECTED.value)
        log_audit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
