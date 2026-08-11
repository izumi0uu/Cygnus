from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from cygnus.governance.signals import (
    GovernanceSignalInput,
    governance_signal_to_pressure_record,
)
from cygnus.governance.ticket_import import (
    MAX_IMPORT_DIAGNOSTICS,
    TicketExportFormat,
    TicketImportValidationError,
    build_ticket_import_plan,
    import_resolved_ticket_export,
    parse_resolved_ticket_export,
)
from cygnus.review.intake import compile_pressure_intake
from cygnus.runtime.database.models import GovernanceSignal


_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_SOURCE_REF = "sanitized-helpdesk-export/2026-w32"
_ACTOR_ID = uuid.uuid4()
_NOW = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)


def _fixture(name: str) -> bytes:
    return (_FIXTURE_DIR / name).read_bytes()


def _signal_from_input(signal_input: GovernanceSignalInput) -> GovernanceSignal:
    observed_at = signal_input.observed_at or _NOW
    evidence_source_type = signal_input.evidence_source_type
    assert evidence_source_type is not None
    return GovernanceSignal(
        id=uuid.uuid4(),
        signal_ref=signal_input.signal_ref,
        signal_type=signal_input.signal_type.value,
        object_ref=signal_input.object_ref,
        title=signal_input.title,
        object_type=signal_input.object_type.value,
        page_id=signal_input.page_id,
        source_id=signal_input.source_id,
        audience_binding_ref=signal_input.audience_binding_ref,
        audience_filter=(
            signal_input.audience_filter.to_dict()
            if signal_input.audience_filter is not None
            else None
        ),
        affected_surfaces=list(signal_input.affected_surfaces),
        trigger_signals=list(signal_input.trigger_signals),
        evidence_source_type=evidence_source_type.value,
        freshness=signal_input.freshness.value,
        summary=signal_input.summary,
        reason=signal_input.reason,
        evidence_excerpt=signal_input.evidence_excerpt,
        evidence_refs=[item.to_dict() for item in signal_input.evidence_refs],
        status="active",
        observed_at=observed_at,
        resolved_at=None,
        created_by_id=_ACTOR_ID,
        created_at=_NOW,
        updated_at=_NOW,
        version=1,
    )


class TicketImportContractTests(unittest.TestCase):
    def test_csv_and_jsonl_have_identical_normalized_clusters(self) -> None:
        csv_records = parse_resolved_ticket_export(
            _fixture("resolved_ticket_export.csv"),
            export_format=TicketExportFormat.CSV,
        )
        jsonl_records = parse_resolved_ticket_export(
            _fixture("resolved_ticket_export.jsonl"),
            export_format=TicketExportFormat.JSONL,
        )
        csv_plan = build_ticket_import_plan(
            csv_records,
            source_ref=_SOURCE_REF,
            export_format=TicketExportFormat.CSV,
        )
        jsonl_plan = build_ticket_import_plan(
            jsonl_records,
            source_ref=_SOURCE_REF,
            export_format=TicketExportFormat.JSONL,
        )

        self.assertEqual(csv_plan.import_digest, jsonl_plan.import_digest)
        self.assertEqual(csv_plan.record_count, 4)
        self.assertEqual(len(csv_plan.candidates), 2)
        self.assertEqual(len(csv_plan.qualifying_candidates), 1)
        self.assertEqual(
            [item.to_dict() for item in csv_plan.candidates],
            [item.to_dict() for item in jsonl_plan.candidates],
        )
        qualifying = csv_plan.qualifying_candidates[0]
        self.assertEqual(qualifying.issue_signature, "session-resume-loop")
        self.assertEqual(qualifying.member_count, 3)
        self.assertEqual(len(qualifying.evidence_refs), 3)
        self.assertTrue(
            all("#ticket=" in item.source_ref for item in qualifying.evidence_refs)
        )

    def test_reordered_jsonl_is_an_exact_plan_replay(self) -> None:
        lines = _fixture("resolved_ticket_export.jsonl").decode().splitlines()
        reordered = ("\n".join(reversed(lines)) + "\n").encode()
        original_records = parse_resolved_ticket_export(
            _fixture("resolved_ticket_export.jsonl"),
            export_format=TicketExportFormat.JSONL,
        )
        replay_records = parse_resolved_ticket_export(
            reordered,
            export_format=TicketExportFormat.JSONL,
        )
        original = build_ticket_import_plan(
            original_records,
            source_ref=_SOURCE_REF,
            export_format=TicketExportFormat.JSONL,
        )
        replay = build_ticket_import_plan(
            replay_records,
            source_ref=_SOURCE_REF,
            export_format=TicketExportFormat.JSONL,
        )

        self.assertEqual(original.import_digest, replay.import_digest)
        self.assertEqual(
            [item.to_dict() for item in original.candidates],
            [item.to_dict() for item in replay.candidates],
        )

    def test_invalid_jsonl_reports_bounded_diagnostics_before_any_write(self) -> None:
        invalid = b"\n".join(
            json.dumps({"ticket_id": f"invalid-{index}"}).encode()
            for index in range(25)
        )

        async def exercise() -> None:
            with patch(
                "cygnus.governance.ticket_import.create_governance_signal",
                AsyncMock(),
            ) as create_signal:
                with self.assertRaises(TicketImportValidationError) as context:
                    await import_resolved_ticket_export(
                        AsyncMock(),
                        invalid,
                        export_format=TicketExportFormat.JSONL,
                        source_ref=_SOURCE_REF,
                        minimum_cluster_size=3,
                        created_by_id=_ACTOR_ID,
                    )
                create_signal.assert_not_awaited()
            error = context.exception
            self.assertEqual(len(error.diagnostics), MAX_IMPORT_DIAGNOSTICS)
            self.assertGreater(error.total_errors, MAX_IMPORT_DIAGNOSTICS)
            self.assertTrue(error.to_dict()["diagnostics_truncated"])

        asyncio.run(exercise())

    def test_duplicate_ticket_ids_are_rejected(self) -> None:
        csv_text = _fixture("resolved_ticket_export.csv").decode()
        first_data_row = csv_text.splitlines()[1]
        with self.assertRaises(TicketImportValidationError) as context:
            parse_resolved_ticket_export(
                (csv_text + first_data_row + "\n").encode(),
                export_format=TicketExportFormat.CSV,
            )

        self.assertIn(
            "duplicate_ticket_id",
            {item.code for item in context.exception.diagnostics},
        )


class TicketImportGovernanceHandoffTests(unittest.TestCase):
    def test_only_qualifying_clusters_create_review_truth(self) -> None:
        fake_create = AsyncMock(
            side_effect=lambda _session, item, **_: _signal_from_input(item)
        )

        async def exercise() -> None:
            with patch(
                "cygnus.governance.ticket_import.create_governance_signal",
                fake_create,
            ):
                result = await import_resolved_ticket_export(
                    AsyncMock(),
                    _fixture("resolved_ticket_export.csv"),
                    export_format=TicketExportFormat.CSV,
                    source_ref=_SOURCE_REF,
                    minimum_cluster_size=3,
                    created_by_id=_ACTOR_ID,
                )

            self.assertEqual(len(result.plan.candidates), 2)
            self.assertEqual(len(result.governance_signals), 1)
            fake_create.assert_awaited_once()
            create_call = fake_create.await_args
            assert create_call is not None
            signal_input = create_call.args[1]
            self.assertEqual(signal_input.signal_type.value, "ticket_cluster")
            self.assertEqual(len(signal_input.evidence_refs), 3)
            self.assertIn("feature=session-resume", signal_input.summary)
            self.assertEqual(result.to_dict()["publication_state"], "not_published")
            self.assertEqual(
                result.to_dict()["next_step"], "review_qualifying_candidates"
            )

            with patch(
                "cygnus.governance.ticket_import.create_governance_signal",
                AsyncMock(),
            ) as no_create:
                below_threshold = await import_resolved_ticket_export(
                    AsyncMock(),
                    _fixture("resolved_ticket_export.csv"),
                    export_format=TicketExportFormat.CSV,
                    source_ref=_SOURCE_REF,
                    minimum_cluster_size=4,
                    created_by_id=_ACTOR_ID,
                )
            self.assertEqual(len(below_threshold.governance_signals), 0)
            no_create.assert_not_awaited()

        asyncio.run(exercise())

    def test_structured_ticket_evidence_reaches_review_bundle(self) -> None:
        records = parse_resolved_ticket_export(
            _fixture("resolved_ticket_export.csv"),
            export_format=TicketExportFormat.CSV,
        )
        plan = build_ticket_import_plan(
            records,
            source_ref=_SOURCE_REF,
            export_format=TicketExportFormat.CSV,
        )
        signal_input = plan.qualifying_candidates[0].to_signal_input()
        signal = _signal_from_input(signal_input)

        record = governance_signal_to_pressure_record(signal)
        bundle = compile_pressure_intake(record)

        self.assertEqual(
            tuple(item.evidence_id for item in bundle.evidence),
            tuple(item.evidence_id for item in signal_input.evidence_refs),
        )
        self.assertEqual(
            bundle.proposal.evidence_ids,
            tuple(item.evidence_id for item in signal_input.evidence_refs),
        )
        self.assertEqual(bundle.signal.risk_type.value, "ticket_pressure")
        self.assertEqual(bundle.proposal.action.value, "create")


if __name__ == "__main__":
    unittest.main()
