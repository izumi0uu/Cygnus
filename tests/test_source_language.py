"""Focused tests for the Source.language slice (20260812_08_source_language).

Covers the acceptance surface:
  - One shared helper validates/normalizes the supported language tags
    (``en`` | ``zh``) and rejects invalid input BEFORE any mutation.
  - Every Source row carries an explicit tag: ORM column is NOT NULL with an
    ``en`` default/server default, legacy rows migrate to ``en``, and the
    response projects the persisted tag.
  - Canonical lookups always filter a normalized language: a zh and an en
    page under the same scope/path stay separate, and ``language=None``
    resolves to the legacy ``en`` default instead of an ambiguous row.
  - The MRP commit phase writes pages under the source's language tag; retry
    preserves the tag because it is persisted on the row the worker reloads.
  - The migration is linear (``20260812_08`` → ``20260812_07``) and
    reversible (downgrade drops the column).
"""

from __future__ import annotations

import asyncio
import datetime
import importlib.util
import io
import types
import unittest
import uuid
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.datastructures import UploadFile
from pydantic import ValidationError

from cygnus.substrate.source_language import (
    DEFAULT_SOURCE_LANGUAGE,
    SUPPORTED_SOURCE_LANGUAGES,
    SourceLanguageError,
    normalize_source_language,
    resolve_source_language,
)

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _run(coro):
    return asyncio.run(coro)


def _load_source_language_migration() -> Any:
    """Load the digit-prefixed migration module via importlib."""
    path = MIGRATIONS_DIR / "20260812_08_source_language.py"
    spec = importlib.util.spec_from_file_location(
        "migration_20260812_08_source_language", path
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader = spec.loader
    assert loader is not None
    loader.exec_module(module)
    return module


class _BoomDB:
    """Fails the test the instant any lasting mutation is attempted."""

    async def execute(self, *args, **kwargs):
        raise AssertionError("db touched on rejected input")

    def add(self, *args, **kwargs):
        raise AssertionError("db touched on rejected input")


class SourceLanguageHelperTests(unittest.TestCase):
    def test_supported_set_is_the_product_locales(self) -> None:
        self.assertEqual(SUPPORTED_SOURCE_LANGUAGES, frozenset({"en", "zh"}))
        self.assertEqual(DEFAULT_SOURCE_LANGUAGE, "en")

    def test_accepts_and_normalizes_supported_tags(self) -> None:
        self.assertEqual(normalize_source_language("en"), "en")
        self.assertEqual(normalize_source_language("zh"), "zh")
        self.assertEqual(normalize_source_language(" ZH "), "zh")
        self.assertEqual(normalize_source_language("En"), "en")

    def test_rejects_missing_or_blank_tags(self) -> None:
        for bad in (None, "", "   "):
            with self.subTest(value=bad):
                with self.assertRaises(SourceLanguageError):
                    normalize_source_language(bad)

    def test_rejects_unsupported_and_malformed_tags(self) -> None:
        for bad in ("fr", "en-us", "de", "x" * 20, 123, ["zh"]):
            with self.subTest(value=bad):
                with self.assertRaises(SourceLanguageError):
                    normalize_source_language(cast(Any, bad))

    def test_resolve_source_language_uses_persisted_tag_or_default(self) -> None:
        # Explicit persisted tag wins and is normalized.
        self.assertEqual(
            resolve_source_language(types.SimpleNamespace(language="ZH")), "zh"
        )
        # Legacy/pre-migration rows (or test doubles) without the attribute
        # resolve to the default — never auto-detected from content.
        self.assertEqual(resolve_source_language(types.SimpleNamespace()), "en")
        self.assertEqual(
            resolve_source_language(types.SimpleNamespace(language="")), "en"
        )
        # A present-but-invalid tag fails loudly instead of writing pages under
        # a wrong canonical identity.
        with self.assertRaises(SourceLanguageError):
            resolve_source_language(types.SimpleNamespace(language="fr"))


class SourceModelContractTests(unittest.TestCase):
    def test_language_column_is_not_null_with_en_defaults(self) -> None:
        from sqlalchemy import String

        from cygnus.runtime.database.models import Source

        column = Source.__table__.c.language
        self.assertFalse(column.nullable)
        column_type = column.type
        assert isinstance(column_type, String)
        self.assertEqual(column_type.length, 10)
        # Python-side default + server default: legacy rows backfill to 'en'
        # and bare inserts never produce a language-less row.
        self.assertEqual(column.default.arg, "en")
        self.assertIn("'en'", str(column.server_default.arg))


class CanonicalLookupLanguageSeparationTests(unittest.TestCase):
    """A (scope, slug) lookup MUST always filter a normalized language.

    en/zh pages may legally coexist under one scope/path (canonical identity
    includes language), so a language-less lookup would be nondeterministic.
    ``None`` resolves to the legacy ``en`` default for non-source callers.
    """

    class _CaptureSession:
        def __init__(self) -> None:
            self.stmt: Any = None

        async def execute(self, stmt):
            self.stmt = stmt
            return types.SimpleNamespace(
                scalars=lambda: types.SimpleNamespace(first=lambda: None)
            )

    def _compiled_language_param(self, session: "_CaptureSession") -> object:
        return session.stmt.compile().params.get("language_1")

    def test_get_page_by_slug_defaults_to_en_when_no_language_given(self) -> None:
        from cygnus.runtime.services import wiki_service

        session = self._CaptureSession()
        _run(wiki_service.get_page_by_slug(cast(Any, session), "concept/x"))
        self.assertEqual(self._compiled_language_param(session), "en")

    def test_get_page_by_slug_filters_the_requested_language(self) -> None:
        from cygnus.runtime.services import wiki_service

        session = self._CaptureSession()
        _run(
            wiki_service.get_page_by_slug(
                cast(Any, session), "concept/x", language="zh"
            )
        )
        self.assertEqual(self._compiled_language_param(session), "zh")

    def test_any_scope_lookup_also_filters_a_normalized_language(self) -> None:
        from cygnus.runtime.services import wiki_service

        session = self._CaptureSession()
        _run(wiki_service.get_page_by_slug_any_scope(cast(Any, session), "concept/x"))
        self.assertEqual(self._compiled_language_param(session), "en")

        session = self._CaptureSession()
        _run(
            wiki_service.get_page_by_slug_any_scope(
                cast(Any, session), "concept/x", language="zh"
            )
        )
        self.assertEqual(self._compiled_language_param(session), "zh")

    def test_apply_create_threads_language_into_the_canonical_write_path(self) -> None:
        from cygnus.runtime.services import wiki_service
        from cygnus.runtime.services.wiki_service import PageWriteOutcome

        write_page = AsyncMock(
            return_value=PageWriteOutcome(
                page=cast(Any, types.SimpleNamespace(id=uuid.uuid4())),
                inserted=True,
                applied=True,
            )
        )
        with patch.object(wiki_service, "write_page", write_page):
            _run(
                wiki_service.apply_create(
                    session=cast(Any, object()),
                    slug="concept/x",
                    title="X",
                    page_type="concept",
                    content_md="# X\n\nBody.",
                    summary="X summary",
                    knowledge_type_slugs=["faq"],
                    source_ids=[uuid.uuid4()],
                    scope_type="global",
                    scope_id=None,
                    language="zh",
                )
            )
        call = write_page.await_args
        assert call is not None
        self.assertEqual(call.kwargs["language"], "zh")

    def test_apply_update_selects_the_same_language_identity(self) -> None:
        from cygnus.runtime.services import wiki_service

        session = self._CaptureSession()
        # No existing page in the zh identity → returns None (never touches en).
        with patch.object(
            wiki_service, "get_page_by_slug", AsyncMock(return_value=None)
        ):
            result = _run(
                wiki_service.apply_update(
                    session=cast(Any, session),
                    slug="concept/x",
                    new_content_md="# X\n\nUpdated zh body.",
                    scope_type="global",
                    scope_id=None,
                    language="zh",
                )
            )
        self.assertIsNone(result)
        self.assertEqual(self._compiled_language_param(session), "zh")


class SourceRouterContractTests(unittest.TestCase):
    def setUp(self) -> None:
        from cygnus.runtime.routers import sources as sources_router

        self.sources_router = sources_router
        self.user = types.SimpleNamespace(
            role="employee",
            global_role="contributor",
            department_ids=[],
            id=uuid.uuid4(),
        )

    def test_url_create_requires_language(self) -> None:
        with self.assertRaises(ValidationError):
            self.sources_router.SourceCreateURL(
                **cast(Any, {"url": "http://example.com/x"})
            )

    def test_update_keeps_language_optional(self) -> None:
        update = self.sources_router.SourceUpdate(title="New title")
        self.assertIsNone(update.language)
        self.assertEqual(self.sources_router.SourceUpdate(language="zh").language, "zh")

    def test_invalid_upload_language_rejected_before_any_mutation(self) -> None:
        upload = UploadFile(file=io.BytesIO(b"x" * 10), filename="doc.txt")
        with self.assertRaises(HTTPException) as ctx:
            _run(
                self.sources_router.upload_source(
                    file=upload,
                    title=None,
                    knowledge_type_id=None,
                    department_ids=None,
                    scope_type=None,
                    scope_id=None,
                    preserve_verbatim=False,
                    language="fr",
                    db=cast(Any, _BoomDB()),
                    user=cast(Any, self.user),
                )
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("not supported", str(ctx.exception.detail))

    def test_invalid_url_language_rejected_before_any_mutation(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            _run(
                self.sources_router.add_url_source(
                    self.sources_router.SourceCreateURL(
                        url="http://example.com/x", language="fr"
                    ),
                    db=cast(Any, _BoomDB()),
                    user=cast(Any, self.user),
                )
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("not supported", str(ctx.exception.detail))

    def test_response_projects_the_persisted_language_tag(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        source = types.SimpleNamespace(
            id=uuid.uuid4(),
            title="文档",
            source_type="file",
            file_name="doc.md",
            url=None,
            file_size=10,
            status="ready",
            error_message=None,
            progress=100,
            progress_message=None,
            job_id=None,
            page_offsets=[],
            extracted_token_count=10,
            auto_recover_count=0,
            knowledge_type=None,
            knowledge_type_id=None,
            departments=[],
            contributor=None,
            contributed_by_employee_id=None,
            scope_type="global",
            scope_id=None,
            language="zh",
            preserve_verbatim=False,
            created_at=now,
            updated_at=now,
        )
        response = self.sources_router._to_response(cast(Any, source))
        self.assertEqual(response.language, "zh")


class CommitPhaseLanguageTests(unittest.IsolatedAsyncioTestCase):
    """The MRP commit phase stages drafts under the source language."""

    def _plan_dict(self, pages: list[dict], claims: list[dict]) -> dict:
        return {"pages": pages, "_claims": claims}

    def _page_spec(self, slug: str) -> dict:
        return {
            "slug": slug,
            "title": slug.title(),
            "page_type": "concept",
            "action": "CREATE",
            "entity_names": [slug],
            "priority": 1,
        }

    def _ok_result(self, slug: str):
        from cygnus.runtime.ai.mrp.writer import PageWriteResult

        return PageWriteResult(
            slug=slug,
            title=slug.title(),
            page_type="concept",
            action="CREATE",
            content_md=f"# {slug.title()}\n\nReal facts.\n",
            summary="Real facts.",
            entity_names=[slug],
        )

    async def _run_commit(self, *, language: str | None, expect_language: str) -> dict:
        from cygnus.review import contributions as contributions_module
        from cygnus.runtime.ai import registry as registry_module
        from cygnus.runtime.ai.mrp import merger as merger_module
        from cygnus.runtime.ai.mrp import pipeline as pipeline_module
        from cygnus.runtime.services import wiki_service

        source = types.SimpleNamespace(
            id=uuid.uuid4(),
            scope_type="global",
            scope_id=None,
            dispatch_generation=2,
            contributed_by_employee_id=None,
            title="Src",
            file_name="src.md",
        )
        if language is not None:
            source.language = language

        plan = types.SimpleNamespace(
            plan_json=self._plan_dict(
                [self._page_spec("alpha")],
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
        session = types.SimpleNamespace(
            commit=AsyncMock(),
            flush=AsyncMock(),
            rollback=AsyncMock(),
            # AsyncSession.execute is awaited, while Result access stays sync.
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
            f"cygnus:test:compiler-draft:alpha:{expect_language}",
        )
        stage_draft = AsyncMock(return_value=(types.SimpleNamespace(id=draft_id), True))

        with (
            patch.object(wiki_service, "get_page_by_slug", get_page_by_slug),
            patch.object(
                contributions_module,
                "stage_compilation_wiki_draft",
                stage_draft,
            ),
            patch.object(
                merger_module, "merge_page_content", AsyncMock(return_value="")
            ),
            patch.object(
                registry_module, "ProviderRegistry", lambda _session: fake_registry
            ),
        ):
            outcome = await pipeline_module.run_commit_phase(
                session=cast(Any, session),
                source=source,
                page_results=[self._ok_result("alpha")],
                plan=plan,
                embedding_provider=None,
                embedding_spec=None,
                kt_slug=None,
                tracker=cast(Any, types.SimpleNamespace(update=AsyncMock())),
                full_text="x" * 500,
            )

        self.assertEqual(outcome["drafts_created"], 1)
        self.assertEqual(outcome["edit_drafts_created"], 0)
        self.assertEqual(plan.status, "done")
        self.assertEqual(plan.plan_json["_compiler_draft_ids"], [str(draft_id)])
        # Both the canonical lookup and durable draft carry resolved language.
        get_page_by_slug.assert_awaited_once()
        lookup_call = get_page_by_slug.await_args
        assert lookup_call is not None
        self.assertEqual(lookup_call.kwargs["language"], expect_language)
        stage_draft.assert_awaited_once()
        stage_call = stage_draft.await_args
        assert stage_call is not None
        self.assertEqual(stage_call.kwargs["language"], expect_language)
        self.assertEqual(stage_call.kwargs["scope_type"], "global")
        self.assertIsNone(stage_call.kwargs["scope_id"])
        session.rollback.assert_not_awaited()
        return outcome

    async def test_zh_source_stages_zh_draft(self) -> None:
        await self._run_commit(language="zh", expect_language="zh")

    async def test_legacy_source_without_tag_defaults_to_en(self) -> None:
        # Pre-migration rows carry no attribute; the pipeline must preserve
        # the legacy en behavior (this is what a retry of a migrated row hits:
        # the worker reloads the row — language "en" — and re-runs the same
        # commit path below).
        await self._run_commit(language=None, expect_language="en")


class SourceLanguageMigrationTests(unittest.TestCase):
    def test_revision_chain_is_linear(self) -> None:
        migration = _load_source_language_migration()
        self.assertEqual(migration.revision, "20260812_08")
        self.assertEqual(migration.down_revision, "20260812_07")

    def test_upgrade_backfills_then_not_nulls_and_downgrade_drops(self) -> None:
        migration = _load_source_language_migration()

        calls: list[tuple] = []
        executed: list[tuple[str, dict]] = []

        def _fake_add_column(table: str, column) -> None:
            calls.append(("add_column", table, str(column.type), column.nullable))

        def _fake_alter_column(table: str, column_name: str, **kwargs) -> None:
            # The migration passes server_default=sa.text("'en'"), a TextClause
            # whose .text is the rendered SQL literal.
            server_default = kwargs["server_default"]
            default_text = getattr(server_default, "text", None) or str(server_default)
            calls.append(
                (
                    "alter_column",
                    table,
                    kwargs["nullable"],
                    str(default_text),
                )
            )

        def _fake_execute(text) -> None:
            compiled = text.compile()
            executed.append((str(compiled), dict(compiled.params)))

        def _fake_drop_column(table: str, column: str) -> None:
            calls.append(("drop_column", table, column))

        with (
            patch.object(migration.op, "add_column", _fake_add_column),
            patch.object(migration.op, "alter_column", _fake_alter_column),
            patch.object(migration.op, "drop_column", _fake_drop_column),
            patch.object(
                migration.op,
                "get_bind",
                lambda: types.SimpleNamespace(execute=_fake_execute),
            ),
        ):
            migration.upgrade()
            migration.downgrade()

        add = [c for c in calls if c[0] == "add_column"]
        alter = [c for c in calls if c[0] == "alter_column"]
        drops = [c for c in calls if c[0] == "drop_column"]

        self.assertEqual(len(add), 1)
        self.assertEqual(add[0][1], "sources")
        self.assertTrue(add[0][2].startswith("VARCHAR"))
        # Add is nullable, then the backfill UPDATE runs with the 'en' tag,
        # then NOT NULL + server default are applied.
        self.assertTrue(add[0][3])
        backfills = [
            (sql, params)
            for sql, params in executed
            if "language" in sql and "UPDATE sources" in sql
        ]
        self.assertEqual(len(backfills), 1)
        self.assertEqual(backfills[0][1], {"lang": "en"})
        self.assertEqual(alter[0][1], "sources")
        self.assertFalse(alter[0][2])
        self.assertIn("'en'", alter[0][3])
        self.assertEqual(drops, [("drop_column", "sources", "language")])


if __name__ == "__main__":
    unittest.main()
