from __future__ import annotations

import ast
from pathlib import Path


def test_internalization_docs_freeze_package_roles() -> None:
    checks = {
        "docs/zh/arkon-internalization-plan.md": [
            "Package boundary freeze",
            "`cygnus/runtime/*` = **runtime / app shell / imported upstream topology reference**",
            "`cygnus/substrate/*` = **Cygnus-owned substrate contracts**",
            "`cygnus/domain/*` = **support-domain contracts / object vocabulary**",
            "`cygnus/evidence/*` = **evidence normalization and record layer**",
            "`cygnus/retrieval/*` = **object/evidence retrieval and source-trace query layer**",
            "`cygnus/review/*` / `cygnus/publish/*` / `cygnus/recovery/*` = **governance control-plane modules**",
            "`cygnus/integrations/*` = **external/session-facing integration adapters**",
            "`cygnus/workflows/*` = **workflow composition layer, not generic runtime shell**",
            "`cygnus/api/*` = **removed legacy package**",
        ],
        "docs/en/arkon-internalization-plan.md": [
            "Package boundary freeze",
            "`cygnus/runtime/*` = **runtime / app shell / imported upstream topology reference**",
            "`cygnus/substrate/*` = **Cygnus-owned substrate contracts**",
            "`cygnus/domain/*` = **support-domain contracts / object vocabulary**",
            "`cygnus/evidence/*` = **evidence normalization and record layer**",
            "`cygnus/retrieval/*` = **object/evidence retrieval and source-trace query layer**",
            "`cygnus/review/*` / `cygnus/publish/*` / `cygnus/recovery/*` = **governance control-plane modules**",
            "`cygnus/integrations/*` = **external/session-facing integration adapters**",
            "`cygnus/workflows/*` = **workflow composition layer, not generic runtime shell**",
            "`cygnus/api/*` = **removed legacy package**",
        ],
        "docs/agent/zh/execution-context.md": [
            "Package owner contract",
            "`cygnus/runtime/*` = imported runtime/app shell/reference topology",
            "`cygnus/substrate/*` = Cygnus-owned substrate contracts",
            "`cygnus/domain/*` = support-domain contracts / object vocabulary",
            "`cygnus/evidence/*` = evidence normalization and record layer",
            "`cygnus/retrieval/*` = object/evidence retrieval and source-trace query layer",
            "`cygnus/review/*` / `cygnus/publish/*` / `cygnus/recovery/*` = governance control-plane modules",
            "`cygnus/integrations/*` = external/session-facing integration adapters",
            "`cygnus/workflows/*` = workflow composition layer，不是 generic runtime shell",
            "`cygnus/api/*` = 已移除的 legacy package",
            "`cygnus.runtime.main` 是 canonical app owner",
        ],
        "docs/agent/en/execution-context.md": [
            "Package owner contract",
            "`cygnus/runtime/*` = imported runtime/app shell/reference topology",
            "`cygnus/substrate/*` = Cygnus-owned substrate contracts",
            "`cygnus/domain/*` = support-domain contracts / object vocabulary",
            "`cygnus/evidence/*` = evidence normalization and record layer",
            "`cygnus/retrieval/*` = object/evidence retrieval and source-trace query layer",
            "`cygnus/review/*` / `cygnus/publish/*` / `cygnus/recovery/*` = governance control-plane modules",
            "`cygnus/integrations/*` = external/session-facing integration adapters",
            "`cygnus/workflows/*` = workflow composition layer, not generic runtime shell",
            "`cygnus/api/*` = removed legacy package",
            "`cygnus.runtime.main` is the canonical app owner",
        ],
    }

    for relative_path, snippets in checks.items():
        text = Path(relative_path).read_text(encoding="utf-8")
        for snippet in snippets:
            assert snippet in text, f"missing `{snippet}` in {relative_path}"


def test_package_dunders_publish_single_owner_story() -> None:
    api_modules = sorted(path.name for path in Path("cygnus/api").glob("*.py"))
    package_snippets = {
        "cygnus/__init__.py": [
            "Cygnus support knowledge operating system package",
            "runtime shell ownership remains under ``cygnus.runtime``",
            "product boundary, not an app-shell compatibility layer",
            "LangGraph is not part of the current Cygnus mainline",
        ],
        "cygnus/domain/__init__.py": [
            "Support-domain contracts and object vocabulary for Cygnus",
            "this package defines support-domain truth, not runtime wiring",
        ],
        "cygnus/evidence/__init__.py": [
            "Evidence normalization and record layer for Cygnus",
            "not a runtime shell or governance workflow owner",
        ],
        "cygnus/integrations/__init__.py": [
            "External and session-facing integration adapters for Cygnus",
            "MCP auth/scope adapters live here",
            "OAuth session adapters live here",
            "external notification fan-out adapters live here",
            "adapter boundary, not the core governance domain itself",
        ],
        "cygnus/integrations/mcp_auth.py": [
            "MCP-facing auth and scope adapter for Cygnus.",
            "MCP token verification, scope resolution, and token lifecycle live here",
            "this module is a session-facing integration adapter, not generic runtime service truth",
            "class ResolvedIdentity:",
            "class MCPAuthService:",
            "def apply_scope_filter(",
        ],
        "cygnus/integrations/oauth_service.py": [
            "OAuth session adapter for Cygnus MCP clients.",
            "Claude/MCP-facing OAuth client registration, auth-code lifecycle, and token exchange live here",
            "this module is a session-facing integration adapter, not generic runtime service truth",
            "class OAuthService:",
        ],
        "cygnus/publish/__init__.py": [
            "Governance control-plane publish modules for Cygnus",
            "owns publish governance semantics, not runtime app-shell wiring",
            "publish preview, blast radius, propagation, and projection live here",
        ],
        "cygnus/recovery/__init__.py": [
            "Governance control-plane recovery modules for Cygnus",
            "owns governance recovery semantics, not runtime app-shell wiring",
            "downstream reality check, governance overview, recovery window, and recovery proof surfaces live here",
            "RecoveryProofSurface",
        ],
        "cygnus/retrieval/__init__.py": [
            "Object/evidence retrieval and source-trace query layer for Cygnus",
            "page/source embedding persistence backing semantic retrieval lives here",
            "serves retrieval truth, not runtime entry wiring",
            "search_pages_semantic",
            "search_source_chunks_semantic",
            "VerbatimChunk",
            "index_verbatim_source",
        ],
        "cygnus/retrieval/embedding_storage.py": [
            "Embedding persistence primitives for Cygnus semantic retrieval.",
            "wiki-page and raw-source chunk embedding writes/cleanup live here",
            "this module serves retrieval backing state for semantic search, not runtime service orchestration",
            "def compute_content_hash(",
            "async def upsert_page_embedding(",
            "async def cleanup_stale_source_chunk_embeddings(",
        ],
        "cygnus/retrieval/semantic_search.py": [
            "Semantic retrieval queries for Cygnus knowledge and raw source search.",
            "wiki-page semantic search and raw-source chunk semantic search live here",
            "this module serves retrieval truth",
            "async def search_pages_semantic(",
        ],
        "cygnus/retrieval/source_chunks.py": [
            "Raw source chunk retrieval and verbatim indexing for Cygnus.",
            "verbatim raw-source chunking, semantic indexing, and chunk retrieval live here",
            "async def index_verbatim_source(",
            "class VerbatimChunk:",
            "def build_verbatim_chunks(",
        ],
        "cygnus/review/__init__.py": [
            "Governance control-plane review modules for Cygnus",
            "contribution lifecycle and automated draft pre-review annotations live under ``cygnus.review``",
            "source compilation-plan review lifecycle also lives under ``cygnus.review``",
            "submit_wiki_branch",
            "close_wiki_branch",
            "merge_wiki_branch",
            "rebase_wiki_branch_draft",
            "create_wiki_draft",
            "approve_wiki_draft",
            "reject_wiki_draft",
            "submit_skill_contribution",
            "approve_skill_contribution",
            "reject_skill_contribution",
            "approve_source_compilation_plan",
            "reject_source_compilation_plan",
            "request_source_plan_regeneration",
            "owns governance semantics, not runtime app-shell wiring",
        ],
        "cygnus/review/source_plans.py": [
            "Compilation-plan review lifecycle governance for source ingest plans.",
            "review owns approve / reject / regenerate / auto-approve semantics for governed source plans",
            "class SourcePlanInvalidTransition(Exception):",
            "async def approve_source_compilation_plan(",
            "async def reject_source_compilation_plan(",
            "async def request_source_plan_regeneration(",
            "def auto_approve_source_compilation_plan(",
            "def restore_source_plan_pending_review(",
            "def fail_source_plan_regeneration(",
        ],
        "cygnus/review/branches.py": [
            "Wiki branch lifecycle governance for review-owned contribution branches.",
            "submit / close / merge / rebase semantics for governed branch changes",
            "class BranchMergeConflict(Exception):",
            "async def submit_wiki_branch(",
            "async def close_wiki_branch(",
            "async def merge_wiki_branch(",
            "async def rebase_wiki_branch_draft(",
        ],
        "cygnus/review/contributions.py": [
            "Contribution lifecycle governance for knowledge contributions.",
            "governance lifecycle wrapper, not a table merge",
            "Wiki draft workflow owned by review governance",
            "async def create_wiki_draft(",
            "async def approve_wiki_draft(",
            "async def reject_wiki_draft(",
            "async def submit_skill_contribution(",
            "async def approve_skill_contribution(",
            "async def reject_skill_contribution(",
        ],
        "cygnus/review/pre_review/__init__.py": [
            "Governance draft pre-review annotations for Cygnus",
            "Ownership lives under ``cygnus.review``",
            "these verdicts shape the review workflow, not the runtime service tree",
        ],
        "cygnus/runtime/__init__.py": [
            "runtime shell preserving imported Arkon topology",
            "source execution-state transitions also live here as runtime truth",
            "not the whole Cygnus product boundary",
        ],
        "cygnus/runtime/source_state.py": [
            "Source runtime execution-state transitions for Cygnus.",
            "runtime queue, retry, and resume behavior",
            "Routers remain HTTP adapters, while review owns",
            "def mark_source_processing(",
            "def mark_source_requeued_after_department_change(",
            "def mark_source_retry_queued(",
            "def mark_source_ingest_queued(",
            "def mark_source_post_extraction_resume(",
            "def mark_source_plan_refine_queued(",
            "def mark_source_awaiting_approval(",
            "def mark_source_runtime_error(",
            "def mark_source_plan_ready_for_review(",
            "def mark_source_ready(",
        ],
        "cygnus/substrate/__init__.py": [
            "Cygnus-owned substrate contracts",
            "source outline extraction and page-slice primitives",
            "not a second app shell or API entry layer",
            "not a LangGraph runtime host",
        ],
        "cygnus/substrate/source_outline.py": [
            "Substrate source outline primitives for Cygnus.",
            "heading-based source structure extraction and page-range slicing live here",
            "these are compilation/navigation primitives, not runtime service wiring",
            "def assemble_full_text(",
            "def slice_pages_by_range(",
            "def parse_page_range(",
            "def build_outline(",
            "def flatten_outline(",
            "def flatten_outline_with_depth(",
        ],
        "cygnus/workflows/__init__.py": [
            "Workflow composition layer for Cygnus",
            "not a generic session runtime shell",
            "do not justify reintroducing a LangGraph mainline",
        ],
    }

    assert api_modules == []

    for relative_path, snippets in package_snippets.items():
        text = Path(relative_path).read_text(encoding="utf-8")
        for snippet in snippets:
            assert snippet in text, f"missing `{snippet}` in {relative_path}"


def test_recovery_proof_surface_lives_under_recovery_tree() -> None:
    publish_init = Path("cygnus/publish/__init__.py").read_text(encoding="utf-8")
    recovery_init = Path("cygnus/recovery/__init__.py").read_text(encoding="utf-8")
    publish_router_text = Path("cygnus/runtime/routers/governance/publish.py").read_text(encoding="utf-8")
    recovery_router_text = Path("cygnus/runtime/routers/governance/recovery.py").read_text(encoding="utf-8")

    assert "cygnus.publish.recovery" not in publish_init
    assert "get_pressure_intake_recovery_proof_surface" not in publish_init
    assert "RecoveryProofSurface" not in publish_init

    assert "get_pressure_intake_recovery_proof_surface" in recovery_init
    assert "RecoveryProofSurface" in recovery_init
    assert "cygnus.recovery" not in publish_router_text
    assert "get_pressure_intake_recovery_proof_surface" not in publish_router_text
    assert "cygnus.recovery" in recovery_router_text
    assert "get_pressure_intake_recovery_proof_surface" in recovery_router_text

    assert not Path("cygnus/publish/recovery.py").exists()
    assert Path("cygnus/recovery/proof.py").exists()


def test_governance_router_owner_converges_to_backend_router_package() -> None:
    main_text = Path("cygnus/runtime/main.py").read_text(encoding="utf-8")
    owner_text = Path("cygnus/runtime/governance_router.py").read_text(encoding="utf-8")

    assert "from cygnus.runtime.governance_router import router as governance_router" in main_text
    assert "router = APIRouter(tags=[\"governance\"])" in owner_text


def test_api_package_has_no_python_modules() -> None:
    api_modules = {
        path.name
        for path in Path("cygnus/api").glob("*.py")
        if path.name != "__pycache__"
    }

    assert api_modules == set()


def test_internal_import_policy_forbids_removed_api_facades_and_legacy_app_namespace() -> None:
    forbidden_modules = {
        "cygnus.api.auth",
        "cygnus.api.config",
        "cygnus.api.governance_router",
        "cygnus.api.app",
        "cygnus.api",
        "app",
    }

    scan_roots = [Path("cygnus"), Path("tests")]

    for root in scan_roots:
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue

            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        name = alias.name
                        assert name not in forbidden_modules, f"{path} imports forbidden module `{name}`"
                        assert not name.startswith("app."), f"{path} reintroduced legacy app namespace `{name}`"

                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    assert module not in forbidden_modules, f"{path} imports forbidden module `{module}`"
                    assert module != "app" and not module.startswith("app."), (
                        f"{path} reintroduced legacy app namespace `{module}`"
                    )
                    if module == "cygnus":
                        for alias in node.names:
                            assert alias.name != "api", f"{path} reintroduced removed `cygnus.api` package"


def test_ai_pre_review_surface_lives_under_review_tree() -> None:
    review_init = Path("cygnus/review/__init__.py").read_text(encoding="utf-8")
    pre_review_init = Path("cygnus/review/pre_review/__init__.py").read_text(encoding="utf-8")
    runtime_services_init = Path("cygnus/runtime/services/__init__.py").read_text(encoding="utf-8")
    worker_text = Path("cygnus/runtime/worker.py").read_text(encoding="utf-8")
    db_models_text = Path("cygnus/runtime/database/models.py").read_text(encoding="utf-8")

    contributions_text = Path("cygnus/review/contributions.py").read_text(encoding="utf-8")

    assert "contribution lifecycle and automated draft pre-review annotations live under ``cygnus.review``" in review_init
    assert "Governance draft pre-review annotations for Cygnus" in pre_review_init
    assert "Contribution lifecycle governance for knowledge contributions." in contributions_text
    assert "contribution lifecycle and governance draft pre-review no longer live here" in runtime_services_init
    assert "source outline extraction and page-slice primitives no longer live here" in runtime_services_init
    assert "from cygnus.review.pre_review import run_async_checks" in worker_text
    assert "cygnus/review/pre_review/runner.py" in db_models_text

    assert Path("cygnus/review/pre_review/runner.py").exists()
    assert Path("cygnus/review/contributions.py").exists()
    assert not Path("cygnus/runtime/services/ai_review").exists()
    assert not Path("cygnus/runtime/services/contribution_service.py").exists()




def test_source_outline_primitives_live_under_substrate_tree() -> None:
    substrate_init = Path("cygnus/substrate/__init__.py").read_text(encoding="utf-8")
    substrate_outline = Path("cygnus/substrate/source_outline.py").read_text(encoding="utf-8")
    worker_text = Path("cygnus/runtime/worker.py").read_text(encoding="utf-8")
    mcp_tools_text = Path("cygnus/runtime/mcp/tools.py").read_text(encoding="utf-8")
    mrp_writer_text = Path("cygnus/runtime/ai/mrp/writer.py").read_text(encoding="utf-8")
    runtime_services_init = Path("cygnus/runtime/services/__init__.py").read_text(encoding="utf-8")

    assert "source outline extraction and page-slice primitives" in substrate_init
    assert "Substrate source outline primitives for Cygnus." in substrate_outline
    assert "from cygnus.substrate.source_outline import assemble_full_text, build_outline" in worker_text
    assert "from cygnus.substrate.source_outline import parse_page_range, slice_pages_by_range" in mcp_tools_text
    assert "from cygnus.substrate.source_outline import flatten_outline_with_depth" in mrp_writer_text
    assert "source outline extraction and page-slice primitives no longer live here" in runtime_services_init

    assert Path("cygnus/substrate/source_outline.py").exists()
    assert not Path("cygnus/runtime/services/source_outline.py").exists()


def test_external_notification_dispatch_lives_under_integrations_tree() -> None:
    integrations_init = Path("cygnus/integrations/__init__.py").read_text(encoding="utf-8")
    integration_dispatch = Path("cygnus/integrations/notification_dispatch.py").read_text(encoding="utf-8")
    runtime_services_init = Path("cygnus/runtime/services/__init__.py").read_text(encoding="utf-8")
    notification_service_text = Path("cygnus/runtime/services/notification_service.py").read_text(encoding="utf-8")

    assert "external notification fan-out adapters live here" in integrations_init
    assert "External notification fan-out adapters for Cygnus." in integration_dispatch
    assert "outward notification fan-out no longer lives here" in runtime_services_init
    assert "from cygnus.integrations.notification_dispatch import dispatch_external" in notification_service_text

    assert Path("cygnus/integrations/notification_dispatch.py").exists()
    assert not Path("cygnus/runtime/services/notification_dispatch.py").exists()


def test_mcp_auth_scope_adapter_lives_under_integrations_tree() -> None:
    integrations_init = Path("cygnus/integrations/__init__.py").read_text(encoding="utf-8")
    mcp_auth_text = Path("cygnus/integrations/mcp_auth.py").read_text(encoding="utf-8")
    runtime_services_init = Path("cygnus/runtime/services/__init__.py").read_text(encoding="utf-8")
    oauth_service_text = Path("cygnus/integrations/oauth_service.py").read_text(encoding="utf-8")
    rbac_router_text = Path("cygnus/runtime/routers/rbac.py").read_text(encoding="utf-8")
    mcp_permissions_text = Path("cygnus/runtime/mcp/permissions.py").read_text(encoding="utf-8")
    mcp_tools_text = Path("cygnus/runtime/mcp/tools.py").read_text(encoding="utf-8")

    assert "MCP auth/scope adapters live here" in integrations_init
    assert "MCP-facing auth and scope adapter for Cygnus." in mcp_auth_text
    assert "MCP token verification, scope resolution, and token lifecycle live here" in mcp_auth_text
    assert "MCP auth/scope adapters no longer live here" in runtime_services_init
    assert "from cygnus.integrations.mcp_auth import MCPAuthService" in oauth_service_text
    assert "from cygnus.integrations.mcp_auth import MCPAuthService" in rbac_router_text
    assert "from cygnus.integrations.mcp_auth import ResolvedIdentity" in mcp_permissions_text
    assert "from cygnus.integrations.mcp_auth import MCPAuthService" in mcp_tools_text
    assert "from cygnus.integrations.mcp_auth import apply_scope_filter" in mcp_tools_text

    assert Path("cygnus/integrations/mcp_auth.py").exists()
    assert not Path("cygnus/runtime/services/mcp_auth_service.py").exists()


def test_oauth_session_adapter_lives_under_integrations_tree() -> None:
    integrations_init = Path("cygnus/integrations/__init__.py").read_text(encoding="utf-8")
    oauth_service_text = Path("cygnus/integrations/oauth_service.py").read_text(encoding="utf-8")
    runtime_services_init = Path("cygnus/runtime/services/__init__.py").read_text(encoding="utf-8")
    oauth_router_text = Path("cygnus/runtime/routers/oauth.py").read_text(encoding="utf-8")

    assert "OAuth session adapters live here" in integrations_init
    assert "OAuth session adapter for Cygnus MCP clients." in oauth_service_text
    assert "Claude/MCP-facing OAuth client registration, auth-code lifecycle, and token exchange live here" in oauth_service_text
    assert "OAuth session adapters no longer live here" in runtime_services_init
    assert "from cygnus.integrations.oauth_service import OAuthService" in oauth_router_text

    assert Path("cygnus/integrations/oauth_service.py").exists()
    assert not Path("cygnus/runtime/services/oauth_service.py").exists()


def test_raw_source_retrieval_primitives_live_under_retrieval_tree() -> None:
    retrieval_init = Path("cygnus/retrieval/__init__.py").read_text(encoding="utf-8")
    semantic_search = Path("cygnus/retrieval/semantic_search.py").read_text(encoding="utf-8")
    source_chunks = Path("cygnus/retrieval/source_chunks.py").read_text(encoding="utf-8")
    runtime_services_init = Path("cygnus/runtime/services/__init__.py").read_text(encoding="utf-8")
    worker_text = Path("cygnus/runtime/worker.py").read_text(encoding="utf-8")
    mcp_tools_text = Path("cygnus/runtime/mcp/tools.py").read_text(encoding="utf-8")
    wiki_service_text = Path("cygnus/runtime/services/wiki_service.py").read_text(encoding="utf-8")

    assert "search_pages_semantic" in retrieval_init
    assert "search_source_chunks_semantic" in retrieval_init
    assert "VerbatimChunk" in retrieval_init
    assert "index_verbatim_source" in retrieval_init
    assert "Semantic retrieval queries for Cygnus knowledge and raw source search." in semantic_search
    assert "Raw source chunk retrieval and verbatim indexing for Cygnus." in source_chunks
    assert "raw-source verbatim indexing and chunk retrieval no longer live here" in runtime_services_init
    assert "from cygnus.retrieval import semantic_search as wiki_search" in mcp_tools_text
    assert "from cygnus.retrieval.source_chunks import index_verbatim_source" in worker_text
    assert "from cygnus.retrieval.source_chunks import search_source_chunks_semantic" in mcp_tools_text
    assert "async def search_pages_semantic(" not in wiki_service_text
    assert "search_source_chunks_semantic(" not in wiki_service_text

    assert Path("cygnus/retrieval/semantic_search.py").exists()
    assert Path("cygnus/retrieval/source_chunks.py").exists()
    assert not Path("cygnus/runtime/services/verbatim_service.py").exists()


def test_embedding_persistence_primitives_live_under_retrieval_tree() -> None:
    retrieval_init = Path("cygnus/retrieval/__init__.py").read_text(encoding="utf-8")
    embedding_storage = Path("cygnus/retrieval/embedding_storage.py").read_text(encoding="utf-8")
    runtime_services_init = Path("cygnus/runtime/services/__init__.py").read_text(encoding="utf-8")
    source_chunks_text = Path("cygnus/retrieval/source_chunks.py").read_text(encoding="utf-8")
    mrp_pipeline_text = Path("cygnus/runtime/ai/mrp/pipeline.py").read_text(encoding="utf-8")
    wiki_compiler_text = Path("cygnus/runtime/ai/wiki_compiler.py").read_text(encoding="utf-8")
    worker_text = Path("cygnus/runtime/worker.py").read_text(encoding="utf-8")

    assert "page/source embedding persistence backing semantic retrieval lives here" in retrieval_init
    assert "Embedding persistence primitives for Cygnus semantic retrieval." in embedding_storage
    assert "wiki-page and raw-source chunk embedding writes/cleanup live here" in embedding_storage
    assert "embedding persistence helpers no longer live here" in runtime_services_init
    assert "from cygnus.retrieval.embedding_storage import (" in source_chunks_text
    assert "from cygnus.retrieval.embedding_storage import (" in mrp_pipeline_text
    assert "from cygnus.retrieval.embedding_storage import (" in wiki_compiler_text
    assert "from cygnus.retrieval.embedding_storage import (" in worker_text

    assert Path("cygnus/retrieval/embedding_storage.py").exists()
    assert not Path("cygnus/runtime/services/embedding_storage.py").exists()

def test_sources_router_no_longer_owns_runtime_source_dispatch_names() -> None:
    sources_router = Path("cygnus/runtime/routers/sources.py").read_text(encoding="utf-8")
    worker_text = Path("cygnus/runtime/worker.py").read_text(encoding="utf-8")

    assert "enqueue_source_ingest_file" in sources_router
    assert "enqueue_source_ingest_url" in sources_router
    assert "enqueue_source_map_reduce" in sources_router
    assert "enqueue_source_refine" in sources_router
    assert "enqueue_source_plan_regeneration" in sources_router

    forbidden_dispatch_literals = [
        'enqueue_job("ingest_file_task"',
        'enqueue_job("ingest_url_task"',
        'enqueue_job("ingest_map_reduce_task"',
        'enqueue_job("ingest_refine_task"',
        'enqueue_job("regenerate_plan_task"',
    ]

    for snippet in forbidden_dispatch_literals:
        assert snippet not in sources_router

    assert 'async def enqueue_source_ingest_file(' in worker_text
    assert 'async def enqueue_source_ingest_url(' in worker_text
    assert 'async def enqueue_source_map_reduce(' in worker_text
    assert 'async def enqueue_source_refine(' in worker_text
    assert 'async def enqueue_source_retry(' in worker_text
    assert 'async def enqueue_source_plan_regeneration(' in worker_text
