from __future__ import annotations

import importlib
import inspect
import unittest
from pathlib import Path

PROVIDER_BASELINE_FILES = [
    "cygnus/backend/ai/providers/__init__.py",
    "cygnus/backend/ai/providers/base.py",
    "cygnus/backend/ai/providers/openai_provider.py",
    "cygnus/backend/ai/providers/anthropic_provider.py",
    "cygnus/backend/ai/providers/google.py",
]

PROVIDER_BASELINE_MODULES = {
    "cygnus.backend.ai.providers.base": [
        "ProviderType",
        "ProviderConfig",
        "EmbeddingProvider",
        "LLMProvider",
        "VisionProvider",
    ],
    "cygnus.backend.ai.providers.openai_provider": [
        "OpenAIEmbedding",
        "OpenAILLM",
        "OpenAIVision",
    ],
    "cygnus.backend.ai.providers.anthropic_provider": [
        "AnthropicLLM",
    ],
    "cygnus.backend.ai.providers.google": [
        "GoogleEmbedding",
        "GoogleLLM",
        "GoogleVision",
    ],
}


class ProviderBaselineImportTests(unittest.TestCase):
    def test_provider_baseline_files_exist(self) -> None:
        for relative_path in PROVIDER_BASELINE_FILES:
            self.assertTrue(Path(relative_path).is_file(), f"missing mirrored provider file: {relative_path}")

    def test_provider_baseline_files_are_syntax_valid(self) -> None:
        for relative_path in PROVIDER_BASELINE_FILES:
            source = Path(relative_path).read_text(encoding="utf-8")
            compile(source, relative_path, "exec")

    def test_provider_baseline_topology_is_exactly_the_upstream_module_family(self) -> None:
        expected = {Path(path).name for path in PROVIDER_BASELINE_FILES}
        actual = {path.name for path in Path("cygnus/backend/ai/providers").glob("*.py")}

        self.assertEqual(expected, actual)

    def test_provider_modules_import_and_expose_upstream_entrypoints(self) -> None:
        for module_name, symbols in PROVIDER_BASELINE_MODULES.items():
            module = importlib.import_module(module_name)

            for symbol in symbols:
                value = getattr(module, symbol, None)
                self.assertIsNotNone(value, f"{module_name} missing upstream provider symbol: {symbol}")
                self.assertTrue(
                    inspect.isclass(value) or callable(value),
                    f"{module_name}.{symbol} should remain an importable provider entrypoint",
                )

    def test_provider_base_defines_neutral_provider_contracts(self) -> None:
        source = Path("cygnus/backend/ai/providers/base.py").read_text(encoding="utf-8")

        for token in ["ProviderType", "ProviderConfig", "EmbeddingProvider", "LLMProvider", "VisionProvider"]:
            self.assertIn(token, source, f"provider base lost contract token: {token}")

        self.assertIn("async def generate_with_tools", source)
        self.assertIn("async def embed_batch", source)
        self.assertIn("async def analyze_image", source)


if __name__ == "__main__":
    unittest.main()
