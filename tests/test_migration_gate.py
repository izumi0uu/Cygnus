from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "migration_gate.py"
    spec = importlib.util.spec_from_file_location("migration_gate", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["migration_gate"] = module
    spec.loader.exec_module(module)
    return module


migration_gate = _load_module()

_REVISION_TEMPLATE = '''"""Revision {revision}."""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "{revision}"
down_revision: str | None = "{down}"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "table_{revision}",
        sa.Column("id", sa.Integer(), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("table_{revision}")
'''

_NOOP_DOWNGRADE_TEMPLATE = '''"""Revision {revision}."""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "{revision}"
down_revision: str | None = "{down}"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "table_{revision}",
        sa.Column("id", sa.Integer(), primary_key=True),
    )


def downgrade() -> None:
    # Intentionally irreversible.
    pass
'''


class MigrationGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.versions = Path(self._tmp.name) / "migrations" / "versions"
        self.versions.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, name: str, content: str) -> Path:
        path = self.versions / name
        path.write_text(content, encoding="utf-8")
        return path

    def _linear_chain(self, revisions: list[str]) -> None:
        for index, revision in enumerate(revisions):
            down = revisions[index - 1] if index > 0 else None
            self._write(
                f"rev_{revision}.py",
                _REVISION_TEMPLATE.format(revision=revision, down=down),
            )

    def test_linear_reversible_chain_passes(self) -> None:
        self._linear_chain(["a1", "a2", "a3"])
        result = migration_gate.static_checks(self.versions)
        self.assertTrue(result["ok"], result["failures"])
        self.assertEqual(result["checks"]["heads"], ["a3"])

    def test_noop_downgrade_fails(self) -> None:
        self._write(
            "rev_a1.py",
            _NOOP_DOWNGRADE_TEMPLATE.format(revision="a1", down=None),
        )
        self._write(
            "rev_a2.py",
            _NOOP_DOWNGRADE_TEMPLATE.format(revision="a2", down="a1"),
        )
        result = migration_gate.static_checks(self.versions)
        self.assertFalse(result["ok"])
        self.assertTrue(any("no-op" in failure for failure in result["failures"]))

    def test_missing_downgrade_fails(self) -> None:
        content = _REVISION_TEMPLATE.format(revision="a1", down=None)
        content = content.replace(
            '\n\ndef downgrade() -> None:\n    op.drop_table("table_a1")\n', "\n"
        )
        self._write("rev_a1.py", content)
        result = migration_gate.static_checks(self.versions)
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("no downgrade() function" in failure for failure in result["failures"])
        )

    def test_duplicate_revision_fails(self) -> None:
        self._write("rev_a1.py", _REVISION_TEMPLATE.format(revision="a1", down=None))
        self._write("rev_a1b.py", _REVISION_TEMPLATE.format(revision="a1", down=None))
        result = migration_gate.static_checks(self.versions)
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("duplicate revision" in failure for failure in result["failures"])
        )

    def test_unresolved_down_revision_fails(self) -> None:
        self._write("rev_a1.py", _REVISION_TEMPLATE.format(revision="a1", down="ghost"))
        result = migration_gate.static_checks(self.versions)
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("does not resolve" in failure for failure in result["failures"])
        )

    def test_multiple_heads_fail(self) -> None:
        self._write("rev_a1.py", _REVISION_TEMPLATE.format(revision="a1", down=None))
        self._write("rev_b1.py", _REVISION_TEMPLATE.format(revision="b1", down=None))
        result = migration_gate.static_checks(self.versions)
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("exactly one head" in failure for failure in result["failures"])
        )

    def test_baseline_limits_reversibility_to_new_revisions(self) -> None:
        # a1 has a no-op downgrade but predates the baseline; a2 is reversible.
        self._write(
            "rev_a1.py", _NOOP_DOWNGRADE_TEMPLATE.format(revision="a1", down=None)
        )
        self._write("rev_a2.py", _REVISION_TEMPLATE.format(revision="a2", down="a1"))
        result = migration_gate.static_checks(self.versions, baseline="a1")
        self.assertTrue(result["ok"], result["failures"])

    def test_baseline_catches_irreversible_revision_added_after_baseline(self) -> None:
        self._write("rev_a1.py", _REVISION_TEMPLATE.format(revision="a1", down=None))
        self._write(
            "rev_a2.py", _NOOP_DOWNGRADE_TEMPLATE.format(revision="a2", down="a1")
        )
        result = migration_gate.static_checks(self.versions, baseline="a1")
        self.assertFalse(result["ok"])
        self.assertTrue(
            any(
                "no-op" in failure and "a2" in failure for failure in result["failures"]
            )
        )

    def test_empty_versions_dir_fails(self) -> None:
        result = migration_gate.static_checks(self.versions)
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("no revision files" in failure for failure in result["failures"])
        )


if __name__ == "__main__":
    unittest.main()
