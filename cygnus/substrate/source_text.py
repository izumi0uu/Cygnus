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

from cygnus.substrate.source_url import fetch_public_source_url


_TEXTUAL_EXTENSIONS = {
    "txt",
    "md",
    "html",
    "htm",
    "json",
    "xml",
    "yaml",
    "yml",
    "log",
    "rst",
}
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

_GENERIC_BINARY_CONTENT_TYPE = "application/octet-stream"
_TEXTUAL_SOURCE_KINDS = frozenset({"text", "html", "json", "xml", "yaml", "csv"})
_SOURCE_KIND_BY_EXTENSION = {
    "txt": "text",
    "md": "text",
    "html": "html",
    "htm": "html",
    "json": "json",
    "xml": "xml",
    "yaml": "yaml",
    "yml": "yaml",
    "log": "text",
    "rst": "text",
    "csv": "csv",
    "pdf": "pdf",
    "docx": "docx",
    "doc": "legacy_binary",
    "pptx": "pptx",
    "ppt": "legacy_binary",
    "xlsx": "xlsx",
    "xls": "legacy_binary",
}
_SOURCE_KIND_BY_CONTENT_TYPE = {
    "text/csv": "csv",
    "text/html": "html",
    "text/xml": "xml",
    "application/json": "json",
    "application/xml": "xml",
    "application/xhtml+xml": "html",
    "application/x-yaml": "yaml",
    "application/yaml": "yaml",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "legacy_binary",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.ms-powerpoint": "legacy_binary",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "legacy_binary",
}


class SourceContentTypeError(ValueError):
    """Raised when a source payload type is unsupported or mismatched."""


class SourceArchiveLimitError(ValueError):
    """Raised when a source archive violates member/count/ratio/size bounds."""


class SourceXMLLimitError(ValueError):
    """Raised when XML parsed from a source payload violates safety bounds."""


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
        "xls": "application/vnd.ms-excel",
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
        "text/xml": "xml",
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


def _source_file_kind(file_name: str) -> str | None:
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    return _SOURCE_KIND_BY_EXTENSION.get(ext)


def _source_content_kind(content_type: str | None) -> str | None:
    normalized = _content_type_without_charset(content_type)
    if not normalized:
        return None
    if normalized == _GENERIC_BINARY_CONTENT_TYPE:
        return "generic_binary"
    if normalized in _SOURCE_KIND_BY_CONTENT_TYPE:
        return _SOURCE_KIND_BY_CONTENT_TYPE[normalized]
    if normalized.startswith("text/"):
        return "text"
    return None


def _payload_looks_like_zip(payload: bytes) -> bool:
    return payload.startswith(b"PK\x03\x04")


def _payload_kinds_are_compatible(
    file_kind: str | None, content_kind: str | None
) -> bool:
    if file_kind is None or content_kind in {None, "generic_binary"}:
        return True
    if file_kind in _TEXTUAL_SOURCE_KINDS and content_kind in _TEXTUAL_SOURCE_KINDS:
        return (
            file_kind == content_kind or file_kind == "text" or content_kind == "text"
        )
    return file_kind == content_kind


def _validate_source_payload_type(
    payload: bytes,
    file_name: str,
    content_type: str | None = None,
    *,
    require_known_type: bool = False,
) -> None:
    """Fail closed on unsupported response types and header/body mismatches.

    Upload callers pass only the filename; URL callers additionally pass the
    server response type and require a known type from either boundary. This
    keeps type validation in the source-extraction owner rather than trusting a
    client-supplied upload MIME value or duplicating policy in the router.
    """
    file_kind = _source_file_kind(file_name)
    normalized_type = _content_type_without_charset(content_type)
    content_kind = _source_content_kind(content_type)

    if normalized_type and content_kind is None:
        raise SourceContentTypeError(
            f"Unsupported source content type: {normalized_type}"
        )
    if (
        require_known_type
        and file_kind is None
        and content_kind
        in {
            None,
            "generic_binary",
        }
    ):
        raise SourceContentTypeError(
            "Source response must declare a supported content type or filename extension"
        )
    if not _payload_kinds_are_compatible(file_kind, content_kind):
        raise SourceContentTypeError(
            "Source filename and response content type do not describe the same payload"
        )

    payload_kind = (
        content_kind if content_kind not in {None, "generic_binary"} else file_kind
    )
    if payload_kind in _TEXTUAL_SOURCE_KINDS:
        if (
            _looks_like_binary_payload(payload)
            or payload.startswith(b"%PDF-")
            or _payload_looks_like_zip(payload)
        ):
            raise SourceContentTypeError(
                "Source payload does not match its declared textual content type"
            )
    elif payload_kind == "pdf" and not payload.startswith(b"%PDF-"):
        raise SourceContentTypeError(
            "Source payload does not match its declared PDF content type"
        )
    elif payload_kind in {"docx", "pptx", "xlsx"} and not _payload_looks_like_zip(
        payload
    ):
        raise SourceContentTypeError(
            "Source payload does not match its declared Office document content type"
        )

    if payload_kind == "xml":
        _parse_xml_bytes(payload)


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

    def handle_starttag(self, tag: str, attrs) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript"}:
            self._ignore_depth += 1
            return
        if lowered == "br" or lowered in self._BLOCK_TAGS:
            self._emit_break()
        if lowered in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._emit_break()
            self._heading_prefix = f"{'#' * int(lowered[1])} "

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript"} and self._ignore_depth:
            self._ignore_depth -= 1
            return
        if lowered in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading_prefix = None
            self._emit_break()
        elif lowered in self._BLOCK_TAGS:
            self._emit_break()

    def handle_data(self, data: str) -> None:
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


def _source_archive_limits() -> tuple[int, int, int]:
    """Resolve archive safety limits from runtime settings (lazy import keeps
    substrate importable without the runtime shell)."""
    from cygnus.runtime.config import settings

    return (
        settings.max_source_archive_bytes,
        settings.max_source_archive_members,
        settings.max_source_archive_ratio,
    )


def _source_xml_max_bytes() -> int:
    """Use existing ingress/archive budgets as the XML parser byte ceiling."""
    from cygnus.runtime.config import settings

    limits = (
        settings.max_source_upload_bytes,
        settings.max_source_url_bytes,
        settings.max_source_archive_bytes,
    )
    return min(limit for limit in limits if limit > 0)


def _guard_zip_bounds(
    file_data: bytes,
    *,
    max_bytes: int | None = None,
    max_members: int | None = None,
    max_ratio: int | None = None,
) -> None:
    """Validate an in-memory zip archive before any member is decompressed.

    Reads only the central directory (no member extraction), enforcing:
      - member count cap (prevents zip-bomb member floods),
      - per-member compression ratio cap (prevents zip-bomb amplification),
      - aggregate uncompressed size cap (prevents decompression bombs),
      - member path-traversal rejection (zip-slip: absolute or ``..`` paths).

    Raises :class:`SourceArchiveLimitError` on any violation.
    """
    if max_bytes is None or max_members is None or max_ratio is None:
        default_bytes, default_members, default_ratio = _source_archive_limits()
        max_bytes = default_bytes if max_bytes is None else max_bytes
        max_members = default_members if max_members is None else max_members
        max_ratio = default_ratio if max_ratio is None else max_ratio

    try:
        archive = zipfile.ZipFile(io.BytesIO(file_data))
    except zipfile.BadZipFile as exc:
        raise SourceArchiveLimitError("Not a valid zip archive") from exc

    with archive:
        total_uncompressed = 0
        member_count = 0
        for info in archive.infolist():
            filename = info.filename
            normalized_filename = filename.replace("\\", "/")
            path_parts = PurePosixPath(normalized_filename).parts
            unix_mode = (info.external_attr >> 16) & 0o170000
            if (
                not filename
                or "\x00" in filename
                or normalized_filename.startswith("/")
                or (len(normalized_filename) >= 2 and normalized_filename[1] == ":")
                or any(part == ".." for part in path_parts)
                or unix_mode == 0o120000
            ):
                raise SourceArchiveLimitError(
                    f"Archive member path traversal detected: {filename!r}"
                )
            if info.flag_bits & 0x1:
                raise SourceArchiveLimitError(
                    f"Encrypted archive member is not allowed: {filename!r}"
                )
            if info.is_dir():
                continue

            member_count += 1
            if member_count > max_members:
                raise SourceArchiveLimitError(
                    f"Archive member count exceeds the limit of {max_members}"
                )
            if info.file_size and (
                not info.compress_size
                or info.file_size > max_ratio * info.compress_size
            ):
                raise SourceArchiveLimitError(
                    f"Archive member {filename!r} exceeds the compression ratio limit of {max_ratio}"
                )

            total_uncompressed += info.file_size
            if total_uncompressed > max_bytes:
                raise SourceArchiveLimitError(
                    f"Archive uncompressed size exceeds the limit of {max_bytes} bytes"
                )


def _guard_office_archive(file_data: bytes, *, expected_root: str) -> None:
    """Validate Office ZIP/XML members before their third-party parser runs."""
    _guard_zip_bounds(file_data)
    with zipfile.ZipFile(io.BytesIO(file_data)) as archive:
        members = [info for info in archive.infolist() if not info.is_dir()]
        if not any(info.filename.startswith(expected_root) for info in members):
            raise SourceArchiveLimitError(
                f"Archive is not a valid {expected_root.rstrip('/')} package"
            )
        max_xml_bytes = _source_xml_max_bytes()
        for info in members:
            normalized_name = info.filename.replace("\\", "/").lower()
            if not normalized_name.endswith((".xml", ".rels")):
                continue
            if info.file_size > max_xml_bytes:
                raise SourceXMLLimitError(
                    f"Archive XML member exceeds the limit of {max_xml_bytes} bytes"
                )
            _parse_xml_bytes(archive.read(info.filename), max_bytes=max_xml_bytes)


def _parse_xml_bytes(
    xml_bytes: bytes,
    *,
    max_depth: int | None = None,
    max_bytes: int | None = None,
) -> ElementTree.Element:
    """Parse XML with entity-expansion, byte, and nesting-depth guards.

    Rejects DOCTYPE/ENTITY declarations outright (billion-laughs and external
    entity vectors), bounds bytes before parser allocation, and enforces a
    maximum element nesting depth. Raises :class:`SourceXMLLimitError` on any
    policy violation.
    """
    if max_depth is None:
        from cygnus.runtime.config import settings

        max_depth = settings.max_source_xml_depth
    if max_bytes is None:
        max_bytes = _source_xml_max_bytes()
    if len(xml_bytes) > max_bytes:
        raise SourceXMLLimitError(f"XML payload exceeds the limit of {max_bytes} bytes")

    lowered = xml_bytes.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise SourceXMLLimitError(
            "XML document type/entity declarations are not allowed"
        )

    # Enforce nesting while the parser consumes bytes rather than after a
    # potentially hostile deep tree has already been fully materialized.
    depth = 0
    root: ElementTree.Element | None = None
    try:
        for event, element in ElementTree.iterparse(
            io.BytesIO(xml_bytes), events=("start", "end")
        ):
            if event == "start":
                depth += 1
                if depth > max_depth:
                    raise SourceXMLLimitError(
                        f"XML nesting depth exceeds the limit of {max_depth}"
                    )
                if root is None:
                    root = element
            else:
                depth -= 1
    except ElementTree.ParseError as exc:
        raise SourceXMLLimitError("XML document is not well-formed") from exc
    if root is None:
        raise SourceXMLLimitError("XML document has no root element")
    return root


def _extract_pptx_text(file_data: bytes) -> str:
    slides: list[str] = []
    _guard_office_archive(file_data, expected_root="ppt/")
    with zipfile.ZipFile(io.BytesIO(file_data)) as archive:
        slide_names = sorted(
            (
                name
                for name in archive.namelist()
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            ),
            key=lambda item: (
                int(re.search(r"slide(\d+)\.xml$", item).group(1))  # type: ignore[union-attr]
                if re.search(r"slide(\d+)\.xml$", item)
                else item
            ),
        )
        for index, slide_name in enumerate(slide_names, 1):
            root = _parse_xml_bytes(archive.read(slide_name))
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
    _validate_source_payload_type(file_data, file_name)

    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    pages_data: list[dict] = []

    if ext == "pdf":
        import fitz

        doc = fitz.open(stream=file_data, filetype="pdf")
        empty_pages: list[tuple[int, int]] = []  # (index, page_number)

        for i, page in enumerate(doc):
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
                        img_bytes,
                        mime_type="image/png",
                        prompt=ocr_prompt,
                    )
                    if ocr_text and ocr_text.strip():
                        pages_data[idx]["content"] = ocr_text.strip()
                        logger.debug(f"OCR page {page_num}: {len(ocr_text)} chars")
                except Exception as e:
                    logger.warning(
                        f"OCR failed for page {page_num} of '{file_name}': {e}"
                    )

        doc.close()
        return pages_data

    # --- Excel / Spreadsheet extraction ---
    if ext in ("xlsx", "xls", "csv"):
        if ext == "xlsx":
            # Validate the package and every XML member before pandas/openpyxl
            # receives untrusted archive content.
            _guard_office_archive(file_data, expected_root="xl/")
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
                        pages_data.append(
                            {
                                "content": header + (md or ""),
                                "page_number": sheet_idx + 1,
                            }
                        )
                    except Exception as e:
                        logger.warning(f"Failed to read sheet '{sheet_name}': {e}")
            if pages_data:
                return pages_data
            # Fall through if all sheets are empty
        except Exception as e:
            logger.warning(f"Spreadsheet extraction failed for '{file_name}': {e}")
            # Fall through to the remaining Cygnus-owned extraction paths

    if ext == "docx":
        # Validate the ZIP/XML package before mammoth decompresses or parses it.
        _guard_office_archive(file_data, expected_root="word/")
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
        except (SourceArchiveLimitError, SourceXMLLimitError):
            # Safety validation in _extract_pptx_text must fail the source, not
            # be converted into an empty document by recovery-only handling.
            raise
        except Exception as exc:
            logger.warning(f"PPTX extraction failed for '{file_name}': {exc}")
            return [{"content": "", "page_number": 1}]

    if ext in ("txt", "md", "html", "htm", "json", "xml", "yaml", "yml", "log", "rst"):
        return [
            {
                "content": _extract_textual_file_content(file_data, file_name),
                "page_number": 1,
            }
        ]

    if ext in ("doc", "ppt"):
        logger.warning(f"Unsupported legacy binary office format for '{file_name}'")
        return [{"content": "", "page_number": 1}]

    # Binary formats must not be decoded as UTF-8 — that produces garbage
    # with null bytes that PostgreSQL rejects. Return empty so the caller
    # can surface a clear "no text content" error instead of crashing.
    if _looks_like_binary_payload(file_data):
        return [{"content": "", "page_number": 1}]

    return [
        {
            "content": _decode_text_bytes(file_data, _guess_content_type(file_name)),
            "page_number": 1,
        }
    ]


async def _extract_text_from_url(
    url: str, *, max_bytes: int | None = None
) -> list[dict]:
    """Extract text from a public URL via Cygnus-owned substrate primitives.

    The payload is fetched through :func:`cygnus.substrate.source_url.fetch_public_source_url`,
    which validates the destination (public, non-reserved addresses only),
    re-validates every redirect hop, pins the TCP connection to the validated
    addresses (DNS-rebinding safe), and streams the body through the configured
    byte budget. ``max_bytes`` overrides the runtime ``max_source_url_bytes``
    limit (used by callers that pass an explicit budget).
    """
    from cygnus.runtime.config import settings

    limit = settings.max_source_url_bytes if max_bytes is None else max_bytes
    fetched = await fetch_public_source_url(
        url,
        max_bytes=limit,
        timeout_seconds=settings.max_source_url_fetch_seconds,
    )

    content_type = fetched.content_type
    file_name = _infer_remote_file_name(fetched.url, content_type)
    payload = fetched.payload

    _validate_source_payload_type(
        payload,
        file_name,
        content_type,
        require_known_type=True,
    )

    if _should_route_url_payload_to_file_extractor(file_name, content_type, payload):
        return await _extract_text_from_file(payload, file_name)

    normalized_type = _content_type_without_charset(content_type)
    text = _decode_text_bytes(payload, content_type)

    if normalized_type in {"text/html", "application/xhtml+xml"} or file_name.endswith(
        (".html", ".htm")
    ):
        return [{"content": _html_to_markdownish(text), "page_number": 1}]

    if normalized_type == "application/json" or file_name.endswith(".json"):
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except Exception:
            pass

    return [{"content": text, "page_number": 1}]
