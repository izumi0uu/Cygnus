"""Substrate source text extraction primitives for Cygnus.

Ownership:
- source file/url text extraction and content-type guessing for ingestion live here
- these are source-compilation primitives, not runtime service ownership
- callers provide runtime wiring such as storage or worker orchestration outside this module
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from html import unescape
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import urlparse
from xml.etree import ElementTree

from loguru import logger


_TEXTUAL_EXTENSIONS = {"txt", "md", "html", "htm", "json", "xml", "yaml", "yml", "log", "rst"}
_TEXTUAL_CONTENT_TYPES = {
    "application/json",
    "application/xml",
    "application/xhtml+xml",
    "application/x-yaml",
    "application/yaml",
}
_BINARY_DOCUMENT_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}


def _guess_content_type(file_name: str) -> str:
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    return {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc": "application/msword",
        "txt": "text/plain",
        "md": "text/markdown",
        "html": "text/html",
        "htm": "text/html",
        "json": "application/json",
        "xml": "application/xml",
        "yaml": "application/x-yaml",
        "yml": "application/x-yaml",
        "log": "text/plain",
        "rst": "text/plain",
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "ppt": "application/vnd.ms-powerpoint",
    }.get(ext, "application/octet-stream")


def _content_type_without_charset(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def _charset_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    match = re.search(r"charset=([^\s;]+)", content_type, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip("\"' ")


def _decode_text_bytes(payload: bytes, content_type: str | None = None) -> str:
    charset = _charset_from_content_type(content_type)
    if charset:
        try:
            return payload.decode(charset)
        except Exception:
            pass

    if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return payload.decode("utf-16")
        except Exception:
            pass

    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return payload.decode(encoding)
        except Exception:
            continue
    return payload.decode("utf-8", errors="ignore")


def _guess_extension_from_content_type(content_type: str | None) -> str:
    normalized = _content_type_without_charset(content_type)
    return {
        "application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/msword": "doc",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
        "application/vnd.ms-powerpoint": "ppt",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
        "application/vnd.ms-excel": "xls",
        "text/plain": "txt",
        "text/markdown": "md",
        "text/html": "html",
        "application/xhtml+xml": "html",
        "application/json": "json",
        "application/xml": "xml",
        "application/x-yaml": "yaml",
        "application/yaml": "yaml",
        "text/csv": "csv",
    }.get(normalized, "")


def _infer_remote_file_name(url: str, content_type: str | None = None) -> str:
    parsed = urlparse(url)
    name = PurePosixPath(parsed.path).name
    if name and "." in name:
        return name
    ext = _guess_extension_from_content_type(content_type)
    return f"downloaded.{ext}" if ext else "downloaded"


def _looks_like_binary_payload(payload: bytes) -> bool:
    sample = payload[:2048]
    return b"\x00" in sample


class _HTMLTextExtractor(HTMLParser):
    _BLOCK_TAGS = {
        "p",
        "div",
        "section",
        "article",
        "header",
        "footer",
        "main",
        "aside",
        "nav",
        "ul",
        "ol",
        "li",
        "table",
        "tr",
        "td",
        "th",
        "blockquote",
        "pre",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._ignore_depth = 0
        self._heading_prefix: str | None = None

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript"}:
            self._ignore_depth += 1
            return
        if lowered == "br" or lowered in self._BLOCK_TAGS:
            self._emit_break()
        if lowered in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._emit_break()
            self._heading_prefix = f"{'#' * int(lowered[1])} "

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript"} and self._ignore_depth:
            self._ignore_depth -= 1
            return
        if lowered in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading_prefix = None
            self._emit_break()
        elif lowered in self._BLOCK_TAGS:
            self._emit_break()

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if self._ignore_depth:
            return
        text = re.sub(r"\s+", " ", unescape(data)).strip()
        if not text:
            return

        prefix = self._heading_prefix or ""
        self._heading_prefix = None
        piece = f"{prefix}{text}" if prefix else text
        if self._chunks and not self._chunks[-1].endswith(("\n", " ")):
            self._chunks.append(" ")
        self._chunks.append(piece)

    def _emit_break(self) -> None:
        if not self._chunks:
            return
        if self._chunks[-1].endswith("\n\n"):
            return
        if self._chunks[-1].endswith("\n"):
            self._chunks[-1] += "\n"
        else:
            self._chunks.append("\n\n")

    def render(self) -> str:
        text = "".join(self._chunks)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _html_to_markdownish(html_text: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(html_text)
    parser.close()
    return parser.render()


def _extract_pptx_text(file_data: bytes) -> str:
    slides: list[str] = []
    with zipfile.ZipFile(io.BytesIO(file_data)) as archive:
        slide_names = sorted(
            (
                name
                for name in archive.namelist()
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            ),
            key=lambda item: int(re.search(r"slide(\d+)\.xml$", item).group(1))  # type: ignore[union-attr]
            if re.search(r"slide(\d+)\.xml$", item)
            else item,
        )
        for index, slide_name in enumerate(slide_names, 1):
            root = ElementTree.fromstring(archive.read(slide_name))
            parts = [
                (node.text or "").strip()
                for node in root.iter()
                if node.tag.endswith("}t") and (node.text or "").strip()
            ]
            if not parts:
                continue
            slides.append(f"## Slide {index}\n\n" + "\n".join(parts))
    return "\n\n".join(slides)


def _extract_textual_file_content(file_data: bytes, file_name: str) -> str:
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    content_type = _guess_content_type(file_name)
    text = _decode_text_bytes(file_data, content_type)

    if ext in {"html", "htm"}:
        return _html_to_markdownish(text)
    if ext == "json":
        try:
            return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except Exception:
            return text
    return text


def _should_route_url_payload_to_file_extractor(
    file_name: str,
    content_type: str | None,
    payload: bytes,
) -> bool:
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    normalized_type = _content_type_without_charset(content_type)

    if ext in {"pdf", "docx", "doc", "pptx", "ppt", "xlsx", "xls", "csv"}:
        return True
    if normalized_type in _BINARY_DOCUMENT_CONTENT_TYPES:
        return True
    if normalized_type.startswith("text/") or normalized_type in _TEXTUAL_CONTENT_TYPES:
        return False
    if ext in _TEXTUAL_EXTENSIONS:
        return False
    return _looks_like_binary_payload(payload)


async def _extract_text_from_file(
    file_data: bytes,
    file_name: str,
    vision_provider=None,
) -> list[dict]:
    """Extract text from a binary file, returning per-page records.

    When ``vision_provider`` is supplied (a VisionProvider instance) and a PDF
    page yields no text via PyMuPDF's native extraction, the page is rendered
    to an image and sent to the vision model for OCR.  This handles scanned /
    image-only PDFs that previously produced empty text → MAP phase failure.
    """
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    pages_data: list[dict] = []

    if ext == "pdf":
        import fitz
        doc = fitz.open(stream=file_data, filetype="pdf")
        empty_pages: list[tuple[int, int]] = []  # (index, page_number)

        for i, page in enumerate(doc):  # type: ignore[arg-type]
            text = (page.get_text() or "").strip()
            pages_data.append({"content": text, "page_number": i + 1})
            if not text:
                empty_pages.append((i, i + 1))

        # --- Gemini Vision OCR fallback for empty pages ---
        if empty_pages and vision_provider:
            logger.info(
                f"OCR fallback: {len(empty_pages)}/{len(pages_data)} empty pages "
                f"in '{file_name}', using vision provider"
            )
            ocr_prompt = (
                "Extract ALL text from this document page exactly as written. "
                "Preserve the original layout, headings, tables, and formatting "
                "as closely as possible using markdown. If the page contains a "
                "table, reproduce it as a markdown table. If there is no text "
                "at all, respond with an empty string."
            )
            for idx, page_num in empty_pages:
                try:
                    page = doc[idx]
                    # Render at 2x for better OCR quality
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                    img_bytes = pix.tobytes("png")
                    ocr_text = await vision_provider.analyze_image(
                        img_bytes, mime_type="image/png", prompt=ocr_prompt,
                    )
                    if ocr_text and ocr_text.strip():
                        pages_data[idx]["content"] = ocr_text.strip()
                        logger.debug(f"OCR page {page_num}: {len(ocr_text)} chars")
                except Exception as e:
                    logger.warning(f"OCR failed for page {page_num} of '{file_name}': {e}")

        doc.close()
        return pages_data

    # --- Excel / Spreadsheet extraction ---
    if ext in ("xlsx", "xls", "csv"):
        try:
            import io
            import pandas as pd

            pages_data = []
            if ext == "csv":
                df = pd.read_csv(io.BytesIO(file_data))
                md = df.to_markdown(index=False)
                pages_data.append({"content": md or "", "page_number": 1})
            else:
                # Read all sheets
                xls = pd.ExcelFile(io.BytesIO(file_data))
                for sheet_idx, sheet_name in enumerate(xls.sheet_names):
                    try:
                        df = pd.read_excel(xls, sheet_name=sheet_name)
                        if df.empty:
                            continue
                        header = f"## Sheet: {sheet_name}\n\n"
                        md = df.to_markdown(index=False)
                        pages_data.append({
                            "content": header + (md or ""),
                            "page_number": sheet_idx + 1,
                        })
                    except Exception as e:
                        logger.warning(f"Failed to read sheet '{sheet_name}': {e}")
            if pages_data:
                return pages_data
            # Fall through if all sheets are empty
        except Exception as e:
            logger.warning(f"Spreadsheet extraction failed for '{file_name}': {e}")
            # Fall through to the remaining Cygnus-owned extraction paths

    if ext == "docx":
        import mammoth
        try:
            result = mammoth.extract_raw_text(io.BytesIO(file_data))
            return [{"content": result.value or "", "page_number": 1}]
        except Exception:
            logger.warning(f"DOCX extraction failed for '{file_name}'")
            return [{"content": "", "page_number": 1}]

    if ext == "pptx":
        try:
            return [{"content": _extract_pptx_text(file_data), "page_number": 1}]
        except Exception as e:
            logger.warning(f"PPTX extraction failed for '{file_name}': {e}")
            return [{"content": "", "page_number": 1}]

    if ext in ("txt", "md", "html", "htm", "json", "xml", "yaml", "yml", "log", "rst"):
        return [{"content": _extract_textual_file_content(file_data, file_name), "page_number": 1}]

    if ext in ("doc", "ppt"):
        logger.warning(f"Unsupported legacy binary office format for '{file_name}'")
        return [{"content": "", "page_number": 1}]

    # Binary formats must not be decoded as UTF-8 — that produces garbage
    # with null bytes that PostgreSQL rejects. Return empty so the caller
    # can surface a clear "no text content" error instead of crashing.
    if _looks_like_binary_payload(file_data):
        return [{"content": "", "page_number": 1}]

    return [{"content": _decode_text_bytes(file_data, _guess_content_type(file_name)), "page_number": 1}]


async def _extract_text_from_url(url: str) -> list[dict]:
    """Extract text from a URL via Cygnus-owned substrate primitives."""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, follow_redirects=True, timeout=30)

    content_type = resp.headers.get("content-type")
    file_name = _infer_remote_file_name(url, content_type)
    payload = resp.content

    if _should_route_url_payload_to_file_extractor(file_name, content_type, payload):
        return await _extract_text_from_file(payload, file_name)

    normalized_type = _content_type_without_charset(content_type)
    text = _decode_text_bytes(payload, content_type)

    if normalized_type in {"text/html", "application/xhtml+xml"} or file_name.endswith((".html", ".htm")):
        return [{"content": _html_to_markdownish(text), "page_number": 1}]

    if normalized_type == "application/json" or file_name.endswith(".json"):
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except Exception:
            pass

    return [{"content": text, "page_number": 1}]
