"""Focused tests for MRP compile-completeness governance (CYG-130 slice).

Covers the compiler write-path governance contract:

- A failed/missing MAP or REFINE unit keeps the plan non-done and the source
  non-ready, with structured (machine-actionable) failures.
- No incomplete/placeholder draft can exist: writer failures produce no
  placeholder body, and the commit gate refuses to draft incomplete plans
  through the shared write service.
- Successful generation stays deterministic: validation output is sorted and
  pure.
"""

from __future__ import annotations

import types
import unittest
import uuid
from typing import Any, cast
from unittest.mock import AsyncMock

from cygnus.runtime.ai.mrp.pipeline import (
    CompileIncompleteError,
    is_placeholder_content,
    validate_compile_completeness,
)
from cygnus.runtime.ai.mrp.writer import PageWriteResult, _failed_page_result


def _plan_dict(pages: list[dict], claims: list[dict] | None = None) -> dict:
    return {"pages": pages, "_claims": claims or []}


def _page_spec(slug: str, entity_names: list[str] | None = None) -> dict:
    return {
        "slug": slug,
        "title": slug.title(),
        "page_type": "concept",
        "action": "CREATE",
        "entity_names": entity_names if entity_names is not None else [slug],
        "priority": 1,
    }


def _ok_result(
    slug: str, content: str = "# Alpha\n\nReal facts about alpha.\n"
) -> PageWriteResult:
    return PageWriteResult(
        slug=slug,
        title=slug.title(),
        page_type="concept",
        action="CREATE",
        content_md=content,
        summary="Real facts.",
        entity_names=[slug],
    )


class PlaceholderDetectionTests(unittest.TestCase):
    def test_empty_body_is_placeholder(self) -> None:
        self.assertTrue(is_placeholder_content(""))
        self.assertTrue(is_placeholder_content("   \n  "))

    def test_generation_failed_marker_is_placeholder(self) -> None:
        body = "# Alpha\n\n(Page generation failed: TimeoutError: llm timed out)"
        self.assertTrue(is_placeholder_content(body))

    def test_content_incomplete_marker_is_placeholder(self) -> None:
        body = "# Alpha\n\n(content generation incomplete)"
        self.assertTrue(is_placeholder_content(body))

    def test_real_content_is_not_placeholder(self) -> None:
        body = "# Alpha\n\nAlpha is a governed knowledge object with evidence."
        self.assertFalse(is_placeholder_content(body))


class CompileIncompleteErrorTests(unittest.TestCase):
    def test_error_carries_structured_failures_and_summary(self) -> None:
        failures = [
            {
                "unit": "map:chunk:1",
                "phase": "map",
                "status": "error",
                "error_type": "generation_failed",
                "message": "llm error",
                "retryable": True,
            }
        ]
        exc = CompileIncompleteError(failures)

        self.assertEqual(exc.failures, failures)
        self.assertIn("map:chunk:1", str(exc))
        self.assertIn("1 failed/missing unit", str(exc))


class PageWriteResultFailureTests(unittest.TestCase):
    def test_failure_round_trips_through_dict(self) -> None:
        failure = {
            "unit": "refine:page:alpha",
            "phase": "refine",
            "status": "error",
            "error_type": "generation_failed",
            "message": "boom",
            "retryable": True,
        }
        result = PageWriteResult(
            slug="alpha",
            title="Alpha",
            page_type="concept",
            action="CREATE",
            content_md="",
            summary="",
            failure=failure,
        )

        restored = PageWriteResult.from_dict(result.to_dict())

        self.assertTrue(restored.is_failed)
        self.assertEqual(restored.failure, failure)
        self.assertEqual(restored.content_md, "")

    def test_failed_page_result_never_carries_placeholder_body(self) -> None:
        result = _failed_page_result(
            _page_spec("alpha"),
            error_type="generation_failed",
            message="TimeoutError: llm timed out",
            retryable=True,
        )

        self.assertTrue(result.is_failed)
        self.assertEqual(result.content_md, "")
        self.assertEqual(result.summary, "")
        failure = result.failure
        assert failure is not None
        self.assertEqual(failure["unit"], "refine:page:alpha")
        self.assertEqual(failure["phase"], "refine")
        self.assertEqual(failure["status"], "error")
        self.assertEqual(failure["error_type"], "generation_failed")
        self.assertTrue(failure["retryable"])


class ValidateCompileCompletenessTests(unittest.TestCase):
    def test_complete_plan_passes(self) -> None:
        plan = _plan_dict(
            [_page_spec("alpha"), _page_spec("beta")],
            claims=[
                {
                    "statement": "Alpha governs evidence.",
                    "subject": "alpha",
                    "confidence": "explicit",
                    "absolute_offset": 0,
                    "evidence_length": 200,
                },
                {
                    "statement": "Beta tracks publication state.",
                    "subject": "beta",
                    "confidence": "explicit",
                    "absolute_offset": 300,
                    "evidence_length": 200,
                },
            ],
        )
        results = [
            _ok_result("alpha"),
            _ok_result("beta", content="# Beta\n\nBeta is real content.\n"),
        ]

        self.assertEqual(
            validate_compile_completeness(plan, results, full_text="x" * 500), []
        )

    def test_missing_planned_page_is_a_failure(self) -> None:
        plan = _plan_dict(
            [_page_spec("alpha"), _page_spec("beta")],
            claims=[
                {
                    "statement": "Alpha governs evidence.",
                    "subject": "alpha",
                    "confidence": "explicit",
                    "absolute_offset": 0,
                    "evidence_length": 200,
                }
            ],
        )
        results = [_ok_result("alpha")]

        failures = validate_compile_completeness(plan, results, full_text="x" * 500)

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["unit"], "refine:page:beta")
        self.assertEqual(failures[0]["error_type"], "missing_unit")

    def test_failed_unit_is_passed_through(self) -> None:
        plan = _plan_dict([_page_spec("alpha")])
        failed = _failed_page_result(
            _page_spec("alpha"),
            error_type="generation_failed",
            message="llm error",
            retryable=True,
        )

        failures = validate_compile_completeness(plan, [failed], full_text="x" * 500)

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["unit"], "refine:page:alpha")
        self.assertEqual(failures[0]["error_type"], "generation_failed")
        self.assertEqual(failures[0]["status"], "error")

    def test_placeholder_result_is_a_failure(self) -> None:
        plan = _plan_dict([_page_spec("alpha")])
        placeholder = PageWriteResult(
            slug="alpha",
            title="Alpha",
            page_type="concept",
            action="CREATE",
            content_md="# Alpha\n\n(Page generation failed: TimeoutError: x)",
            summary="Alpha",
        )

        failures = validate_compile_completeness(
            plan, [placeholder], full_text="x" * 500
        )

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["unit"], "refine:page:alpha")
        self.assertEqual(failures[0]["error_type"], "placeholder_content")

    def test_empty_result_is_a_failure(self) -> None:
        plan = _plan_dict([_page_spec("alpha")])
        empty = PageWriteResult(
            slug="alpha",
            title="Alpha",
            page_type="concept",
            action="CREATE",
            content_md="",
            summary="",
        )

        failures = validate_compile_completeness(plan, [empty], full_text="x" * 500)

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["error_type"], "placeholder_content")

    def test_page_without_evidence_is_a_failure(self) -> None:
        # Page entity "alpha" matches NO claim subject, so no evidence backs it.
        plan = _plan_dict(
            [_page_spec("alpha")],
            claims=[
                {
                    "statement": "Something else entirely.",
                    "subject": "gamma",
                    "confidence": "explicit",
                    "absolute_offset": 0,
                    "evidence_length": 200,
                }
            ],
        )
        results = [_ok_result("alpha")]

        failures = validate_compile_completeness(plan, results, full_text="x" * 500)

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["unit"], "refine:page:alpha")
        self.assertEqual(failures[0]["error_type"], "no_evidence")
        self.assertFalse(failures[0]["retryable"])

    def test_map_chunk_failures_are_included(self) -> None:
        plan = _plan_dict(
            [_page_spec("alpha")],
            claims=[
                {
                    "statement": "Alpha governs evidence.",
                    "subject": "alpha",
                    "confidence": "explicit",
                    "absolute_offset": 0,
                    "evidence_length": 200,
                }
            ],
        )
        results = [_ok_result("alpha")]
        chunk_failures = [
            {
                "unit": "map:chunk:2",
                "phase": "map",
                "status": "error",
                "error_type": "generation_failed",
                "message": "extraction failed",
                "retryable": True,
            }
        ]

        failures = validate_compile_completeness(
            plan, results, full_text="x" * 500, chunk_failures=chunk_failures
        )

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["unit"], "map:chunk:2")
        self.assertEqual(failures[0]["error_type"], "generation_failed")

    def test_output_is_sorted_deterministically(self) -> None:
        # Two failing pages + one failing chunk, fed in shuffled order.
        plan = _plan_dict([_page_spec("zeta"), _page_spec("alpha")])
        results = [
            _failed_page_result(
                _page_spec("zeta"),
                error_type="generation_failed",
                message="err",
                retryable=True,
            ),
            _failed_page_result(
                _page_spec("alpha"),
                error_type="generation_failed",
                message="err",
                retryable=True,
            ),
        ]
        chunk_failures = [
            {
                "unit": "map:chunk:1",
                "phase": "map",
                "status": "error",
                "error_type": "generation_failed",
                "message": "err",
                "retryable": True,
            }
        ]

        first = validate_compile_completeness(
            plan, results, full_text="x" * 500, chunk_failures=chunk_failures
        )
        second = validate_compile_completeness(
            plan,
            list(reversed(results)),
            full_text="x" * 500,
            chunk_failures=list(reversed(chunk_failures)),
        )

        self.assertEqual(first, second)
        self.assertEqual(
            [f["unit"] for f in first],
            ["map:chunk:1", "refine:page:alpha", "refine:page:zeta"],
        )


class CommitGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_commit_phase_blocks_incomplete_plan_before_any_write(
        self,
    ) -> None:
        from cygnus.runtime.ai.mrp import pipeline as pipeline_module

        plan = types.SimpleNamespace(
            plan_json=_plan_dict(
                [_page_spec("alpha")],
                claims=[
                    {
                        "statement": "Alpha governs evidence.",
                        "subject": "alpha",
                        "confidence": "explicit",
                        "absolute_offset": 0,
                        "evidence_length": 200,
                    }
                ],
            ),
            status="in_progress",
        )
        # The writer unit failed — no placeholder body, only a structured failure.
        failed = _failed_page_result(
            _page_spec("alpha"),
            error_type="generation_failed",
            message="TimeoutError: llm timed out",
            retryable=True,
        )
        source = types.SimpleNamespace(
            id=uuid.uuid4(),
            scope_type="global",
            scope_id=None,
            title="Source",
            file_name="source.md",
        )
        session = types.SimpleNamespace(commit=AsyncMock())
        tracker = object()

        with self.assertRaises(CompileIncompleteError) as ctx:
            await pipeline_module.run_commit_phase(
                session=cast(Any, session),
                source=source,
                page_results=[failed],
                plan=plan,
                embedding_provider=None,
                embedding_spec=None,
                kt_slug=None,
                tracker=cast(Any, tracker),
                full_text="x" * 500,
            )

        self.assertEqual(ctx.exception.failures[0]["unit"], "refine:page:alpha")
        self.assertEqual(ctx.exception.failures[0]["error_type"], "generation_failed")
        # Structured failures are persisted on the plan; the plan is NOT done.
        self.assertEqual(plan.plan_json["_failures"], ctx.exception.failures)
        self.assertEqual(plan.status, "in_progress")
        session.commit.assert_awaited_once()

    async def test_run_commit_phase_stages_a_verified_plan_as_a_draft(self) -> None:
        """A complete, evidence-backed plan stages one deterministic draft."""
        from cygnus.review import contributions as contributions_module
        from cygnus.runtime.ai import registry as registry_module
        from cygnus.runtime.ai.mrp import merger as merger_module
        from cygnus.runtime.ai.mrp import pipeline as pipeline_module
        from cygnus.runtime.services import wiki_service

        plan = types.SimpleNamespace(
            plan_json=_plan_dict(
                [_page_spec("alpha")],
                claims=[
                    {
                        "statement": "Alpha governs evidence.",
                        "subject": "alpha",
                        "confidence": "explicit",
                        "absolute_offset": 0,
                        "evidence_length": 200,
                    }
                ],
            ),
            status="in_progress",
        )
        result = _ok_result("alpha")
        source = types.SimpleNamespace(
            id=uuid.uuid4(),
            scope_type="global",
            scope_id=None,
            language="en",
            dispatch_generation=3,
            contributed_by_employee_id=None,
            title="Source",
            file_name="source.md",
        )

        session = types.SimpleNamespace(
            commit=AsyncMock(),
            flush=AsyncMock(),
            rollback=AsyncMock(),
            # AsyncSession.execute is a coroutine that resolves to a synchronous
            # Result. The scope resolver consumes one row, then a row sequence.
            execute=AsyncMock(
                return_value=types.SimpleNamespace(
                    one_or_none=lambda: ("global", None),
                    all=lambda: [],
                )
            ),
            get=AsyncMock(return_value=None),
        )
        fake_registry = types.SimpleNamespace(get_llm=AsyncMock(return_value=None))
        get_page_by_slug = AsyncMock(return_value=None)
        draft_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            "cygnus:test:compiler-draft:alpha",
        )
        stage_draft = AsyncMock(return_value=(types.SimpleNamespace(id=draft_id), True))

        with (
            unittest.mock.patch.object(
                wiki_service, "get_page_by_slug", get_page_by_slug
            ),
            unittest.mock.patch.object(
                contributions_module,
                "stage_compilation_wiki_draft",
                stage_draft,
            ),
            unittest.mock.patch.object(
                merger_module,
                "merge_page_content",
                AsyncMock(return_value=result.content_md),
            ),
            unittest.mock.patch.object(
                registry_module, "ProviderRegistry", lambda _session: fake_registry
            ),
        ):
            outcome = await pipeline_module.run_commit_phase(
                session=cast(Any, session),
                source=source,
                page_results=[result],
                plan=plan,
                embedding_provider=None,
                embedding_spec=None,
                kt_slug=None,
                tracker=cast(Any, types.SimpleNamespace(update=AsyncMock())),
                full_text="x" * 500,
            )

        self.assertEqual(
            outcome,
            {
                "drafts_created": 1,
                "edit_drafts_created": 0,
                "drafts_replayed": 0,
            },
        )
        self.assertEqual(plan.status, "done")
        self.assertEqual(plan.plan_json["_compiler_draft_ids"], [str(draft_id)])
        get_page_by_slug.assert_awaited_once_with(
            session,
            "alpha",
            scope_type="global",
            scope_id=None,
            language="en",
        )
        stage_draft.assert_awaited_once()
        stage_call = stage_draft.await_args
        assert stage_call is not None
        self.assertIs(stage_call.kwargs["source"], source)
        self.assertIsNone(stage_call.kwargs["page"])
        self.assertEqual(stage_call.kwargs["scope_type"], "global")
        self.assertIsNone(stage_call.kwargs["scope_id"])
        self.assertEqual(stage_call.kwargs["language"], "en")
        self.assertEqual(stage_call.kwargs["compiler"], "mrp")
        session.rollback.assert_not_awaited()


class ComplexWriterNoPlaceholderTests(unittest.IsolatedAsyncioTestCase):
    async def test_complex_writer_raises_instead_of_fabricating_placeholder(
        self,
    ) -> None:
        """A writer that finishes without content is a failure, never a draft."""
        import types as _types

        from cygnus.runtime.ai.mrp import writer as writer_module
        from cygnus.substrate.agent_protocol import AssistantTurn

        class EmptyTurnLLM:
            config = _types.SimpleNamespace(spec=None)

            async def generate_with_tools(self, **kwargs):  # noqa: ANN001
                return AssistantTurn(text=None, tool_calls=())

        source = _types.SimpleNamespace(scope_type="global", scope_id=None)

        with self.assertRaises(RuntimeError):
            await writer_module._write_page_complex(
                llm=cast(Any, EmptyTurnLLM()),
                plan_item=_page_spec("alpha"),
                evidence=[
                    {
                        "statement": "Alpha governs evidence.",
                        "subject": "alpha",
                        "confidence": "explicit",
                        "absolute_offset": 0,
                        "evidence_length": 100,
                    }
                ],
                existing_content=None,
                full_text="x" * 500,
                session=cast(Any, object()),
                source=source,
                all_plan_slugs=["alpha"],
            )


class _FakeSessionCM:
    """Async context manager wrapping a fake session (async_sessionmaker shape)."""

    def __init__(self, session) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc) -> bool:
        return False


class AutoTriggerRefineDispatchTests(unittest.IsolatedAsyncioTestCase):
    """Cross-agent contract with the source-dispatch outbox (DurableDispatch):

    - auto-approval + refine handoff are recorded transactionally;
    - the deterministic dispatch job id is returned when enqueue succeeds;
    - a tombstoned/missing source falls back to the raw arq enqueue;
    - an enqueue rejection yields job_id=None so the dispatch sweeper recovers.
    """

    async def test_outbox_record_and_enqueue_return_deterministic_job_id(self) -> None:
        from cygnus.runtime.ai.mrp import pipeline as pipeline_module

        sid = uuid.uuid4()
        plan = types.SimpleNamespace(id=uuid.uuid4())
        row = types.SimpleNamespace(job_id=f"source-dispatch:{sid}:refine:1")
        session = types.SimpleNamespace(
            get=AsyncMock(
                side_effect=lambda _model, pk: (
                    types.SimpleNamespace(status="pending_review")
                    if pk == plan.id
                    else types.SimpleNamespace(id=sid, dispatch_generation=0)
                )
            ),
            commit=AsyncMock(),
            execute=AsyncMock(),
        )

        with (
            unittest.mock.patch(
                "cygnus.runtime.database.async_session_factory",
                lambda: _FakeSessionCM(session),
            ),
            unittest.mock.patch(
                "cygnus.review.auto_approve_source_compilation_plan",
                lambda _p, _s: None,
            ),
            unittest.mock.patch(
                "cygnus.runtime.source_dispatch.record_source_dispatch",
                AsyncMock(return_value=(row, 1, row.job_id)),
            ),
            unittest.mock.patch(
                "cygnus.runtime.source_dispatch.enqueue_dispatch_execution",
                AsyncMock(return_value=True),
            ),
            unittest.mock.patch("cygnus.runtime.worker.get_arq_pool", AsyncMock()),
        ):
            result = await pipeline_module._auto_trigger_refine(sid, plan)

        self.assertEqual(result, {"status": "plan_auto_approved", "job_id": row.job_id})

    async def test_missing_source_falls_back_to_raw_enqueue(self) -> None:
        from cygnus.runtime.ai.mrp import pipeline as pipeline_module

        sid = uuid.uuid4()
        plan = types.SimpleNamespace(id=uuid.uuid4())
        raw_job = types.SimpleNamespace(job_id="arq:raw")
        session = types.SimpleNamespace(
            get=AsyncMock(return_value=None),
            commit=AsyncMock(),
            execute=AsyncMock(),
        )

        with (
            unittest.mock.patch(
                "cygnus.runtime.database.async_session_factory",
                lambda: _FakeSessionCM(session),
            ),
            unittest.mock.patch(
                "cygnus.runtime.worker.get_arq_pool",
                AsyncMock(
                    return_value=types.SimpleNamespace(
                        enqueue_job=AsyncMock(return_value=raw_job)
                    )
                ),
            ),
        ):
            result = await pipeline_module._auto_trigger_refine(sid, plan)

        self.assertEqual(result, {"status": "plan_auto_approved", "job_id": "arq:raw"})

    async def test_enqueue_rejection_returns_none_for_sweep_recovery(self) -> None:
        from cygnus.runtime.ai.mrp import pipeline as pipeline_module

        sid = uuid.uuid4()
        plan = types.SimpleNamespace(id=uuid.uuid4())
        row = types.SimpleNamespace(job_id=f"source-dispatch:{sid}:refine:1")
        session = types.SimpleNamespace(
            get=AsyncMock(
                side_effect=lambda _model, pk: types.SimpleNamespace(
                    id=sid, dispatch_generation=1
                )
            ),
            commit=AsyncMock(),
            execute=AsyncMock(),
        )

        with (
            unittest.mock.patch(
                "cygnus.runtime.database.async_session_factory",
                lambda: _FakeSessionCM(session),
            ),
            unittest.mock.patch(
                "cygnus.review.auto_approve_source_compilation_plan",
                lambda _p, _s: None,
            ),
            unittest.mock.patch(
                "cygnus.runtime.source_dispatch.record_source_dispatch",
                AsyncMock(return_value=(row, 1, row.job_id)),
            ),
            unittest.mock.patch(
                "cygnus.runtime.source_dispatch.enqueue_dispatch_execution",
                AsyncMock(return_value=False),
            ),
        ):
            result = await pipeline_module._auto_trigger_refine(sid, plan)

        self.assertEqual(result, {"status": "plan_auto_approved", "job_id": None})


class PlanFailureProjectionTests(unittest.IsolatedAsyncioTestCase):
    """get_compilation_plan must expose compile-completeness failures as a
    sanitized, typed contract (unit/page ref, phase, stable status/error_type,
    retryable, safe message) while keeping internal resume metadata private.
    """

    def test_sanitize_plan_failure_projects_typed_fields(self) -> None:
        from cygnus.runtime.routers import sources as sources_module

        projected = sources_module._sanitize_plan_failure(
            {
                "unit": "refine:page:alpha",
                "phase": "refine",
                "status": "error",
                "error_type": "generation_failed",
                "message": "TimeoutError: llm timed out",
                "retryable": True,
            }
        )

        self.assertEqual(projected.unit, "refine:page:alpha")
        self.assertEqual(projected.phase, "refine")
        self.assertEqual(projected.status, "error")
        self.assertEqual(projected.error_type, "generation_failed")
        self.assertTrue(projected.retryable)
        self.assertEqual(projected.message, "TimeoutError: llm timed out")

    def test_sanitize_plan_failure_handles_junk_and_truncates(self) -> None:
        from cygnus.runtime.routers import sources as sources_module

        junk = sources_module._sanitize_plan_failure("not a dict")
        self.assertEqual(junk.unit, "unknown")
        self.assertEqual(junk.error_type, "unknown")
        self.assertFalse(junk.retryable)

        long_message = "x" * 500
        projected = sources_module._sanitize_plan_failure(
            {
                "unit": "map:chunk:1",
                "phase": "map",
                "status": "error",
                "error_type": "generation_failed",
                "message": long_message,
                "retryable": True,
            }
        )
        self.assertEqual(len(projected.message), 200)

    async def test_get_compilation_plan_exposes_sanitized_failures(self) -> None:
        from datetime import datetime, timezone

        from cygnus.runtime.routers import sources as sources_module

        sid = uuid.uuid4()
        plan = types.SimpleNamespace(
            id=uuid.uuid4(),
            source_id=sid,
            status="in_progress",
            plan_json={
                "pages": [{"slug": "alpha", "action": "CREATE"}],
                "_claims": [{"secret-ish": "internal"}],
                "_page_drafts": [{"internal": "draft"}],
                "_failures": [
                    {
                        "unit": "refine:page:alpha",
                        "phase": "refine",
                        "status": "error",
                        "error_type": "generation_failed",
                        "message": "TimeoutError: llm timed out",
                        "retryable": True,
                    }
                ],
            },
            created_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
            reviewed_at=None,
            review_note=None,
        )
        db = types.SimpleNamespace(
            execute=AsyncMock(
                return_value=types.SimpleNamespace(scalar_one_or_none=lambda: plan)
            )
        )

        with unittest.mock.patch.object(
            sources_module, "_get_scoped_source", AsyncMock(return_value=None)
        ):
            payload = await sources_module.get_compilation_plan(
                source_id=sid, db=cast(Any, db), user=cast(Any, object())
            )

        self.assertEqual(payload["status"], "in_progress")
        self.assertEqual(len(payload["failures"]), 1)
        failure = payload["failures"][0]
        self.assertEqual(failure["unit"], "refine:page:alpha")
        self.assertEqual(failure["phase"], "refine")
        self.assertEqual(failure["status"], "error")
        self.assertEqual(failure["error_type"], "generation_failed")
        self.assertTrue(failure["retryable"])
        self.assertEqual(failure["message"], "TimeoutError: llm timed out")
        # Internal resume metadata stays private in the plan payload.
        self.assertNotIn("_claims", payload["plan"])
        self.assertNotIn("_page_drafts", payload["plan"])
        self.assertNotIn("_failures", payload["plan"])

    async def test_get_compilation_plan_returns_empty_failures_when_clean(self) -> None:
        from datetime import datetime, timezone

        from cygnus.runtime.routers import sources as sources_module

        sid = uuid.uuid4()
        plan = types.SimpleNamespace(
            id=uuid.uuid4(),
            source_id=sid,
            status="pending_review",
            plan_json={"pages": [{"slug": "alpha", "action": "CREATE"}]},
            created_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
            reviewed_at=None,
            review_note=None,
        )
        db = types.SimpleNamespace(
            execute=AsyncMock(
                return_value=types.SimpleNamespace(scalar_one_or_none=lambda: plan)
            )
        )

        with unittest.mock.patch.object(
            sources_module, "_get_scoped_source", AsyncMock(return_value=None)
        ):
            payload = await sources_module.get_compilation_plan(
                source_id=sid, db=cast(Any, db), user=cast(Any, object())
            )

        self.assertEqual(payload["failures"], [])


if __name__ == "__main__":
    unittest.main()
