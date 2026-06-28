from __future__ import annotations

import importlib
import inspect
import unittest
from pathlib import Path

SERVICE_BASELINE_FILES = [
    "cygnus/runtime/services/__init__.py",
    "cygnus/runtime/services/ai_review/__init__.py",
    "cygnus/runtime/services/ai_review/llm_checks.py",
    "cygnus/runtime/services/ai_review/regex_checks.py",
    "cygnus/runtime/services/ai_review/runner.py",
    "cygnus/runtime/services/ai_review/semantic_checks.py",
    "cygnus/runtime/services/ai_review/structural_checks.py",
    "cygnus/runtime/services/audit_service.py",
    "cygnus/runtime/services/auth_service.py",
    "cygnus/runtime/services/config_service.py",
    "cygnus/runtime/services/contribution_service.py",
    "cygnus/runtime/services/embedding_storage.py",
    "cygnus/runtime/services/image_service.py",
    "cygnus/runtime/services/kb_service.py",
    "cygnus/runtime/services/mcp_auth_service.py",
    "cygnus/runtime/services/notification_dispatch.py",
    "cygnus/runtime/services/notification_service.py",
    "cygnus/runtime/services/oauth_service.py",
    "cygnus/runtime/services/permission_engine.py",
    "cygnus/runtime/services/permissions.py",
    "cygnus/runtime/services/policy_engine.py",
    "cygnus/runtime/services/skill_service.py",
    "cygnus/runtime/services/source_outline.py",
    "cygnus/runtime/services/stats_aggregator.py",
    "cygnus/runtime/services/storage_service.py",
    "cygnus/runtime/services/verbatim_service.py",
    "cygnus/runtime/services/wiki_service.py",
]

SERVICE_BASELINE_MODULES = {
    "cygnus.runtime.services.audit_service": ["log_audit"],
    "cygnus.runtime.services.auth_service": [
        "hash_password",
        "verify_password",
        "create_access_token",
        "decode_access_token",
        "authenticate_employee",
        "get_current_user",
        "require_admin",
        "require_permission",
    ],
    "cygnus.runtime.services.config_service": ["ConfigService", "get_effective_config"],
    "cygnus.runtime.services.contribution_service": [
        "ContributionAdapter",
        "WikiDraftAdapter",
        "SkillContributionAdapter",
        "notify_submitted",
        "request_changes",
        "resubmit_wiki_draft",
        "resubmit_skill_contribution",
        "withdraw",
        "notify_approved",
        "notify_rejected",
    ],
    "cygnus.runtime.services.embedding_storage": [
        "compute_content_hash",
        "embedding_input_text",
        "upsert_page_embedding",
        "cleanup_stale_embeddings",
        "chunk_content_hash",
        "upsert_chunk_embedding",
        "delete_source_chunk_embeddings",
    ],
    "cygnus.runtime.services.image_service": ["ImageInfo", "extract_images_from_pdf", "extract_images_from_docx", "extract_images"],
    "cygnus.runtime.services.kb_service": ["ingest_source"],
    "cygnus.runtime.services.mcp_auth_service": ["ResolvedIdentity", "MCPAuthService", "apply_scope_filter"],
    "cygnus.runtime.services.notification_dispatch": ["dispatch_external"],
    "cygnus.runtime.services.notification_service": [
        "NotificationType",
        "notify",
        "notify_each",
        "notify_many",
        "dispatch_pending",
        "get_reviewers_for_scope",
    ],
    "cygnus.runtime.services.oauth_service": ["OAuthService"],
    "cygnus.runtime.services.permission_engine": [
        "parse_permission",
        "has_permission",
        "has_any_permission",
        "can_access_document",
        "build_document_filter",
        "can_access_skill",
        "build_skill_filter",
        "get_effective_permissions",
    ],
    "cygnus.runtime.services.policy_engine": ["PolicyDecision", "PolicyEngine"],
    "cygnus.runtime.services.skill_service": ["SkillService"],
    "cygnus.runtime.services.source_outline": [
        "assemble_full_text",
        "slice_pages_by_range",
        "parse_page_range",
        "build_outline",
        "flatten_outline",
    ],
    "cygnus.runtime.services.stats_aggregator": ["run_daily_rollup"],
    "cygnus.runtime.services.storage_service": ["StorageService"],
    "cygnus.runtime.services.verbatim_service": ["VerbatimChunk", "build_verbatim_chunks", "index_verbatim_source"],
    "cygnus.runtime.services.wiki_service": [
        "extract_wikilinks",
        "refresh_links",
        "get_backlinks",
        "get_outlinks",
        "get_neighborhood",
        "get_page_by_slug",
        "list_pages",
        "search_pages_semantic",
        "search_source_chunks_semantic",
        "apply_create",
        "apply_update",
        "upsert_page",
        "regenerate_index",
        "append_log",
        "delete_page_cascade",
    ],
    "cygnus.runtime.services.ai_review.llm_checks": ["run"],
    "cygnus.runtime.services.ai_review.regex_checks": ["run"],
    "cygnus.runtime.services.ai_review.runner": [
        "CheckResult",
        "run_sync_checks",
        "run_async_checks",
        "merge_results",
    ],
    "cygnus.runtime.services.ai_review.semantic_checks": ["run"],
    "cygnus.runtime.services.ai_review.structural_checks": ["run"],
}


class ServicesBaselineImportTests(unittest.TestCase):
    def test_services_baseline_files_exist(self) -> None:
        for relative_path in SERVICE_BASELINE_FILES:
            self.assertTrue(Path(relative_path).is_file(), f"missing mirrored service file: {relative_path}")

    def test_services_baseline_files_are_syntax_valid(self) -> None:
        for relative_path in SERVICE_BASELINE_FILES:
            source = Path(relative_path).read_text(encoding="utf-8")
            compile(source, relative_path, "exec")

    def test_services_baseline_topology_is_exactly_the_upstream_module_family(self) -> None:
        expected = {Path(path).relative_to("cygnus/runtime/services") for path in SERVICE_BASELINE_FILES}
        actual = {
            path.relative_to("cygnus/runtime/services")
            for path in Path("cygnus/runtime/services").rglob("*.py")
            if "__pycache__" not in path.parts
        }

        self.assertEqual(expected, actual)

    def test_service_modules_import_and_expose_upstream_entrypoints(self) -> None:
        for module_name, symbols in SERVICE_BASELINE_MODULES.items():
            module = importlib.import_module(module_name)

            for symbol in symbols:
                value = getattr(module, symbol, None)
                self.assertIsNotNone(value, f"{module_name} missing upstream service symbol: {symbol}")
                self.assertTrue(
                    inspect.isclass(value) or callable(value),
                    f"{module_name}.{symbol} should remain an importable service entrypoint",
                )

    def test_services_baseline_has_no_legacy_app_namespace_imports(self) -> None:
        for relative_path in SERVICE_BASELINE_FILES:
            source = Path(relative_path).read_text(encoding="utf-8")

            self.assertNotIn("from app.", source)
            self.assertNotIn("import app.", source)
            self.assertNotIn(" app.", source)

    def test_service_baseline_keeps_runtime_substrate_not_support_only_facade(self) -> None:
        services = {Path(path).name for path in SERVICE_BASELINE_FILES}

        for filename in [
            "audit_service.py",
            "auth_service.py",
            "config_service.py",
            "kb_service.py",
            "permission_engine.py",
            "permissions.py",
            "policy_engine.py",
            "storage_service.py",
            "wiki_service.py",
        ]:
            self.assertIn(filename, services)


if __name__ == "__main__":
    unittest.main()
