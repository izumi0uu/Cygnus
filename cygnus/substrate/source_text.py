"""Substrate source text extraction primitives for Cygnus.

Ownership:
- source file/url text extraction and content-type guessing for ingestion live here
- these are source-compilation primitives, not runtime service ownership
- callers provide runtime wiring such as storage or worker orchestration outside this module
"""

from __future__ import annotations

from loguru import logger


def _guess_content_type(file_name: str) -> str:
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    return {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc": "application/msword",
        "txt": "text/plain",
        "md": "text/markdown",
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }.get(ext, "application/octet-stream")


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
            # Fall through if all sheets empty
        except Exception as e:
            logger.warning(f"Spreadsheet extraction failed for '{file_name}': {e}")
            # Fall through to content_core

    if ext == "docx":
        import io

        import mammoth
        try:
            result = mammoth.extract_raw_text(io.BytesIO(file_data))
            return [{"content": result.value or "", "page_number": 1}]
        except Exception:
            pass  # fall through to content_core

    if ext in ("txt", "md"):
        return [{"content": file_data.decode("utf-8", errors="ignore"), "page_number": 1}]

    # Other formats (doc, xlsx, pptx, ...): write to a temp file and let
    # content-core extract via file path. Passing raw bytes as "content"
    # doesn't work for binary formats — content-core expects a string there.
    import os
    import tempfile

    try:
        from content_core.content.extraction import extract_content
        suffix = f".{ext}" if ext else ""
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_data)
            tmp_path = tmp.name
        try:
            result = await extract_content({
                "file_path": tmp_path,
                "output_format": "markdown",
            })
            return [{"content": result.content or "", "page_number": 1}]
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        logger.warning(f"content-core extraction failed for .{ext}: {e}")
        # Binary formats must not be decoded as UTF-8 — that produces garbage
        # with null bytes that PostgreSQL rejects. Return empty so the caller
        # can surface a clear "no text content" error instead of crashing.
        return [{"content": "", "page_number": 1}]


async def _extract_text_from_url(url: str) -> list[dict]:
    """Extract text from a URL — markdown output preferred."""
    try:
        from content_core.content.extraction import extract_content
        result = await extract_content({"url": url, "output_format": "markdown"})
        return [{"content": result.content or "", "page_number": 1}]
    except Exception as e:
        logger.warning(f"URL extraction failed for {url}: {e}")
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, follow_redirects=True, timeout=30)
            return [{"content": resp.text, "page_number": 1}]
