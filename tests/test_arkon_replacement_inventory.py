from __future__ import annotations

import importlib.util
import tempfile
import sys
import unittest
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "arkon_replacement_inventory.py"
    spec = importlib.util.spec_from_file_location("arkon_replacement_inventory", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


arkon_replacement_inventory = _load_module()


class ArkonReplacementInventoryTests(unittest.TestCase):
    def test_inventory_reports_kept_removed_and_runtime_residue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            kept_paths = [
                "cygnus/runtime/__init__.py",
                "cygnus/runtime/governance_router.py",
                "cygnus/runtime/main.py",
                "cygnus/substrate/__init__.py",
                "scripts/upstream_cutover_gate.py",
            ]
            for relative_path in kept_paths:
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# kept surface\n", encoding="utf-8")

            removed_auth = root / "cygnus/api/auth.py"
            removed_auth.parent.mkdir(parents=True, exist_ok=True)
            removed_auth.write_text("import arkon\n", encoding="utf-8")

            runtime_residue = root / "cygnus/runtime.py"
            runtime_residue.parent.mkdir(parents=True, exist_ok=True)
            runtime_residue.write_text("import arkon\n", encoding="utf-8")

            inventory = arkon_replacement_inventory.build_inventory(root)

            self.assertEqual(
                inventory["summary"],
                {"kept_surfaces": 5, "removed_surfaces": 5, "guardrail_files": 6},
            )
            self.assertEqual(
                [item["path"] for item in inventory["kept_surfaces"]],
                kept_paths,
            )

            removed_by_path = {item["path"]: item for item in inventory["removed_surfaces"]}
            self.assertFalse(removed_by_path["cygnus/api/__init__.py"]["exists"])
            self.assertFalse(removed_by_path["cygnus/api/app.py"]["exists"])
            self.assertTrue(removed_by_path["cygnus/api/auth.py"]["exists"])
            self.assertFalse(removed_by_path["cygnus/api/config.py"]["exists"])
            self.assertFalse(removed_by_path["cygnus/api/governance_router.py"]["exists"])

            residue = inventory["unexpected_runtime_residue"]
            self.assertEqual(len(residue), 1)
            self.assertIn("cygnus/runtime.py:1:", residue[0])
            self.assertNotIn("cygnus/api/auth.py", residue[0])
            self.assertEqual(inventory["next_replacement_target"], [])


if __name__ == "__main__":
    unittest.main()
