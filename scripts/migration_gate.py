#!/usr/bin/env python3
"""Migration gate for the Cygnus release pipeline.

Static mode (default, offline):
  - every revision file in migrations/versions declares `revision`,
    `down_revision`, `upgrade`, and `downgrade`;
  - `downgrade` is a real reversal — a no-op body (only `pass`/docstring/
    `...`) fails the gate, because a migration that cannot be rolled back is
    a rollback-compatibility violation;
  - revision ids are unique, every `down_revision` resolves, and the chain
    has exactly one head (no branches, no forks);
  - with `--baseline <rev>`, reversibility is enforced only for revisions
    added after the released baseline, so existing shipped migrations are
    not re-litigated.

Database mode (--database-url, used by the release workflow on a live
Postgres service): runs `upgrade head -> downgrade -1 -> upgrade head` and
asserts the schema lands back on head each time. This is the
migration-before-rollout gate: the workflow only publishes after this
evidence is recorded.

Exit status: 0 = pass, 1 = any static or dynamic violation.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import cast

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "migrations" / "versions"

_NOOP_EXPRS = (ast.Constant,)


def _git_sha(repo_root: Path = REPO_ROOT) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            check=True,
            text=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


@dataclass(frozen=True)
class Revision:
    revision: str
    down_revision: str | None
    path: str

    @property
    def filename(self) -> str:
        return Path(self.path).name


def _body_statements(function: ast.FunctionDef | None) -> list[ast.stmt]:
    if function is None:
        return []
    statements: list[ast.stmt] = []
    for node in function.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, _NOOP_EXPRS):
            continue  # docstring / constant
        statements.append(node)
    return statements


def _is_noop(function: ast.FunctionDef | None) -> bool:
    statements = _body_statements(function)
    if not statements:
        return True
    # Docstrings and ellipses were already filtered by _body_statements; any
    # remaining statement — including expression calls like op.drop_table(...)
    # — is real work. Only bare `pass` bodies are no-ops.
    return all(isinstance(node, ast.Pass) for node in statements)


def parse_revision_file(path: Path) -> tuple[Revision, dict[str, object]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    revision: str | None = None
    down_revision: str | None = None
    upgrade: ast.FunctionDef | None = None
    downgrade: ast.FunctionDef | None = None

    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target: ast.Name
            if isinstance(node, ast.Assign):
                if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                    continue
                target = node.targets[0]
            else:
                if not isinstance(node.target, ast.Name):
                    continue
                target = node.target
                if not isinstance(node.value, ast.Constant) or not isinstance(
                    node.value.value, str
                ):
                    continue
            if not isinstance(node.value, ast.Constant) or not isinstance(
                node.value.value, str
            ):
                continue
            if target.id == "revision":
                revision = node.value.value
            elif target.id == "down_revision":
                value = node.value.value
                # The root migration declares `down_revision = None`; treat the
                # string `"None"` (a template-generated root) the same way. A
                # revision id is never the literal string "None", and treating
                # it as root keeps the exactly-one-head check as the guard.
                down_revision = None if value == "None" else value
        elif isinstance(node, ast.FunctionDef):
            if node.name == "upgrade":
                upgrade = node
            elif node.name == "downgrade":
                downgrade = node

    checks: dict[str, object] = {
        "revision_declared": revision is not None,
        "down_revision_declared": down_revision is not None,
        "upgrade_declared": upgrade is not None,
        "downgrade_declared": downgrade is not None,
        "downgrade_is_noop": _is_noop(downgrade),
    }
    return (
        Revision(
            revision=revision or f"<missing:{path.name}>",
            down_revision=down_revision,
            path=str(path),
        ),
        checks,
    )


def static_checks(
    migrations_dir: Path, baseline: str | None = None
) -> dict[str, object]:
    failures: list[str] = []
    checks: dict[str, object] = {}

    files = sorted(migrations_dir.glob("*.py")) if migrations_dir.is_dir() else []
    checks["revision_files"] = len(files)
    if not files:
        failures.append(f"no revision files found under {migrations_dir}")

    revisions: dict[str, Revision] = {}
    file_checks: dict[str, dict[str, object]] = {}
    for path in files:
        try:
            revision, per_file = parse_revision_file(path)
        except SyntaxError as exc:
            failures.append(f"{path.name}: cannot parse revision file: {exc}")
            continue
        file_checks[path.name] = per_file
        if revision.revision.startswith("<missing"):
            failures.append(f"{path.name}: missing revision id")
            continue
        if revision.revision in revisions:
            failures.append(
                f"duplicate revision id {revision.revision!r} in {revisions[revision.revision].filename} and {path.name}"
            )
        revisions[revision.revision] = revision

    checks["files"] = file_checks

    known = set(revisions)
    for revision in revisions.values():
        if revision.down_revision is not None and revision.down_revision not in known:
            failures.append(
                f"{revision.filename}: down_revision {revision.down_revision!r} does not resolve"
            )

    children: dict[str | None, list[str]] = {}
    for revision in revisions.values():
        children.setdefault(revision.down_revision, []).append(revision.revision)
    heads = [revision for revision in revisions if revision not in children]
    checks["heads"] = sorted(heads)
    if len(heads) != 1:
        failures.append(
            f"expected exactly one head revision, found {len(heads)}: {sorted(heads)}"
        )

    # Reversibility is enforced for every revision, or — when a released
    # baseline is given — only for revisions added after it (walking the
    # down_revision chain up from the baseline).
    def is_after_baseline(revision_id: str) -> bool:
        if baseline is None:
            return True
        if revision_id == baseline:
            return False
        seen: set[str] = set()
        current: str | None = revision_id
        while current is not None and current not in seen:
            if current == baseline:
                return True
            seen.add(current)
            current = revisions[current].down_revision if current in revisions else None
        return False

    checks["baseline"] = baseline
    for revision in revisions.values():
        per_file = file_checks[revision.filename]
        if per_file["upgrade_declared"] is False:
            failures.append(f"{revision.filename}: no upgrade() function")
        if not is_after_baseline(revision.revision):
            continue
        if per_file["downgrade_declared"] is False:
            failures.append(
                f"{revision.filename}: no downgrade() function (rollback incompatible)"
            )
        elif per_file["downgrade_is_noop"]:
            failures.append(
                f"{revision.filename}: downgrade() is a no-op (rollback incompatible)"
            )

    return {"ok": not failures, "checks": checks, "failures": failures}


def _alembic_current_head(alembic_ini: Path) -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(alembic_ini))
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    if head is None:
        raise RuntimeError("migration chain has no head revision")
    return head


def database_checks(repo_root: Path, database_url: str) -> dict[str, object]:
    """Run upgrade head -> downgrade -1 -> upgrade head against a live DB."""
    failures: list[str] = []
    checks: dict[str, object] = {}

    import asyncio

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    alembic_ini = repo_root / "alembic.ini"
    config = Config(str(alembic_ini))
    config.set_main_option("script_location", str(repo_root / "migrations"))
    config.attributes["database_url"] = database_url

    expected_head = _alembic_current_head(alembic_ini)
    checks["expected_head"] = expected_head

    async def db_head() -> str:
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as connection:
                result = await connection.execute(
                    text("SELECT version_num FROM alembic_version")
                )
                row = result.first()
                if row is None:
                    return "<no alembic_version table>"
                return str(row[0])
        finally:
            await engine.dispose()

    try:
        command.upgrade(config, "head")
        after_upgrade = asyncio.run(db_head())
        checks["after_upgrade"] = after_upgrade
        if after_upgrade != expected_head:
            failures.append(
                f"after `upgrade head` the database is at {after_upgrade!r}, expected {expected_head!r}"
            )

        command.downgrade(config, "-1")
        after_downgrade = asyncio.run(db_head())
        checks["after_downgrade"] = after_downgrade
        if after_downgrade == expected_head:
            failures.append(
                "`downgrade -1` did not move off head — newest migration cannot be rolled back"
            )

        command.upgrade(config, "head")
        after_reapply = asyncio.run(db_head())
        checks["after_reapply"] = after_reapply
        if after_reapply != expected_head:
            failures.append(
                f"after re-running `upgrade head` the database is at {after_reapply!r}, expected {expected_head!r}"
            )
    except Exception as exc:  # noqa: BLE001 - gate reports any failure fail-closed
        failures.append(f"database migration cycle failed: {exc}")

    checks["cycle"] = ["upgrade head", "downgrade -1", "upgrade head"]
    return {"ok": not failures, "checks": checks, "failures": failures}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migration gate: static reversibility + optional live rollback-compatibility cycle."
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help="Released baseline revision id; only revisions after it must be reversible.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Postgres URL (asyncpg). When set, runs upgrade/downgrade/upgrade against it.",
    )
    parser.add_argument("--quiet", action="store_true", help="Only print failures.")
    parser.add_argument(
        "--json", action="store_true", help="Emit the structured report as JSON."
    )
    parser.add_argument(
        "--report", type=Path, default=None, help="Write the structured report to PATH."
    )
    args = parser.parse_args(argv)

    static = static_checks(MIGRATIONS_DIR, baseline=args.baseline)
    if args.database_url:
        dynamic = database_checks(REPO_ROOT, args.database_url)
        failures = cast(list[str], static["failures"]) + cast(
            list[str], dynamic["failures"]
        )
        ok = static["ok"] and dynamic["ok"]
        report: dict[str, object] = {
            "gate": "migration_gate",
            "ok": ok,
            "git_sha": _git_sha(),
            "static": static,
            "database": dynamic,
        }
    else:
        failures = cast(list[str], static["failures"])
        ok = static["ok"]
        report = {
            "gate": "migration_gate",
            "ok": ok,
            "git_sha": _git_sha(),
            "static": static,
        }

    if args.report is not None:
        report_path = args.report
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))

    if failures:
        if not args.quiet:
            print("[migration-gate] FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1

    if not args.quiet and not args.json:
        print("[migration-gate] OK (chain reversible, single head)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
