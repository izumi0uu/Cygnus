from __future__ import annotations

import asyncio
import io
import json
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


_MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "cygnus" / "substrate" / "source_text.py"
)


def _load_source_text_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "cygnus_source_text_test_module", _MODULE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


source_text = _load_source_text_module()


def _fetched(
    url: str, content: bytes, content_type: str | None = None
) -> SimpleNamespace:
    return SimpleNamespace(url=url, content_type=content_type, payload=content)


class SourceTextInternalizationTests(unittest.TestCase):
    def test_extracts_html_file_without_external_extractor(self) -> None:
        payload = b"<html><body><h1>Policy</h1><p>Enterprise only.</p></body></html>"

        pages = asyncio.run(source_text._extract_text_from_file(payload, "policy.html"))

        self.assertEqual(
            pages, [{"content": "# Policy\n\nEnterprise only.", "page_number": 1}]
        )

    def test_extracts_json_file_without_external_extractor(self) -> None:
        payload = json.dumps({"plan": "enterprise", "region": "eu"}).encode("utf-8")

        pages = asyncio.run(
            source_text._extract_text_from_file(payload, "variant.json")
        )

        self.assertEqual(pages[0]["page_number"], 1)
        self.assertIn('"plan": "enterprise"', pages[0]["content"])
        self.assertIn('"region": "eu"', pages[0]["content"])

    def test_extracts_pptx_file_without_external_extractor(self) -> None:
        payload = self._build_minimal_pptx(["Launch checklist", "Variant hold for EU"])

        pages = asyncio.run(source_text._extract_text_from_file(payload, "deck.pptx"))

        self.assertEqual(pages[0]["page_number"], 1)
        self.assertIn("## Slide 1", pages[0]["content"])
        self.assertIn("Launch checklist", pages[0]["content"])
        self.assertIn("Variant hold for EU", pages[0]["content"])

    def test_url_html_uses_cygnus_owned_html_path(self) -> None:
        fetched = _fetched(
            "https://example.com/issues/sync",
            b"<html><body><h2>Known issue</h2><p>Sync delay.</p></body></html>",
            content_type="text/html; charset=utf-8",
        )

        with patch.object(
            source_text, "fetch_public_source_url", return_value=fetched
        ) as fetch_mock:
            pages = asyncio.run(
                source_text._extract_text_from_url("https://example.com/issues/sync")
            )

        fetch_mock.assert_awaited_once()
        self.assertEqual(
            pages, [{"content": "## Known issue\n\nSync delay.", "page_number": 1}]
        )

    def test_url_pdf_routes_into_file_extractor(self) -> None:
        fetched = _fetched(
            "https://example.com/source",
            b"%PDF-1.7 fake payload",
            content_type="application/pdf",
        )

        async def _fake_extract_text_from_file(
            file_data: bytes, file_name: str, vision_provider=None
        ):
            self.assertEqual(file_data, fetched.payload)
            self.assertEqual(file_name, "downloaded.pdf")
            self.assertIsNone(vision_provider)
            return [{"content": "pdf body", "page_number": 1}]

        with (
            patch.object(source_text, "fetch_public_source_url", return_value=fetched),
            patch.object(
                source_text,
                "_extract_text_from_file",
                side_effect=_fake_extract_text_from_file,
            ),
        ):
            pages = asyncio.run(
                source_text._extract_text_from_url("https://example.com/source")
            )

        self.assertEqual(pages, [{"content": "pdf body", "page_number": 1}])

    @staticmethod
    def _build_minimal_pptx(slide_texts: list[str]) -> bytes:
        content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
</Types>
"""
        presentation = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>
"""

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("ppt/presentation.xml", presentation)
            for index, text in enumerate(slide_texts, 1):
                slide = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:sp>
        <p:txBody>
          <a:p><a:r><a:t>{text}</a:t></a:r></a:p>
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sld>
"""
                archive.writestr(f"ppt/slides/slide{index}.xml", slide)
        return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
