from __future__ import annotations

import asyncio
import io
import re
import struct
import unittest
import zipfile
import zlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import fitz
from openpyxl import Workbook

from cygnus.runtime.config import settings
from cygnus.substrate import source_images, source_text


def _run(coro):
    return asyncio.run(coro)


def _make_pdf(
    *,
    page_count: int,
    width: float = 100,
    height: float = 100,
    text: bool = False,
    image: bytes | None = None,
) -> bytes:
    document = fitz.open()
    try:
        for index in range(page_count):
            page = document.new_page(width=width, height=height)
            if text:
                page.insert_text((10, 20), f"page {index + 1}")
            if image is not None:
                page.insert_image(page.rect, stream=image)
        return document.tobytes(deflate=True)
    finally:
        document.close()


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type)
    checksum = zlib.crc32(data, checksum)
    return (
        struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)
    )


def _make_compressed_png(width: int, height: int) -> bytes:
    scanline = b"\x00" + (b"\x00\x00\x00" * width)
    raw_pixels = scanline * height
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(raw_pixels, level=9))
        + _png_chunk(b"IEND", b"")
    )


def _make_xlsx(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    for row in rows:
        worksheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _replace_sheet_dimension(payload: bytes, dimension: str) -> bytes:
    source = io.BytesIO(payload)
    output = io.BytesIO()
    with (
        zipfile.ZipFile(source) as input_archive,
        zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as output_archive,
    ):
        for info in input_archive.infolist():
            member = input_archive.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                member, replacements = re.subn(
                    rb'<dimension ref="[^"]+"',
                    f'<dimension ref="{dimension}"'.encode(),
                    member,
                    count=1,
                )
                if replacements != 1:
                    raise AssertionError("worksheet dimension was not found")
            output_archive.writestr(info, member)
    return output.getvalue()


class _RecordingStorage:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, bytes, str]] = []

    def upload_file(
        self, object_name: str, data: bytes, content_type: str
    ) -> str | None:
        self.uploads.append((object_name, data, content_type))
        return object_name


class PDFTextBudgetTests(unittest.TestCase):
    def test_page_count_over_budget_is_rejected(self) -> None:
        payload = _make_pdf(page_count=3, text=True)

        with patch.object(settings, "max_source_pdf_pages", 2):
            with self.assertRaises(source_text.SourceDocumentLimitError):
                _run(source_text._extract_text_from_file(payload, "oversized.pdf"))

    def test_page_and_render_pixel_boundaries_allow_normal_ocr(self) -> None:
        payload = _make_pdf(page_count=2)
        vision = SimpleNamespace(analyze_image=AsyncMock(return_value="scanned text"))

        with (
            patch.object(settings, "max_source_pdf_pages", 2),
            patch.object(settings, "max_source_pdf_render_pixels", 80_000),
        ):
            pages = _run(
                source_text._extract_text_from_file(
                    payload, "boundary.pdf", vision_provider=vision
                )
            )

        self.assertEqual([page["content"] for page in pages], ["scanned text"] * 2)
        self.assertEqual(vision.analyze_image.await_count, 2)

    def test_render_pixel_over_budget_fails_before_ocr(self) -> None:
        payload = _make_pdf(page_count=2)
        vision = SimpleNamespace(analyze_image=AsyncMock(return_value="unused"))

        with (
            patch.object(settings, "max_source_pdf_pages", 2),
            patch.object(settings, "max_source_pdf_render_pixels", 79_999),
        ):
            with self.assertRaises(source_text.SourceDocumentLimitError):
                _run(
                    source_text._extract_text_from_file(
                        payload, "render-bomb.pdf", vision_provider=vision
                    )
                )

        vision.analyze_image.assert_not_awaited()


class PDFImageBudgetTests(unittest.TestCase):
    def test_image_count_over_budget_fails_before_upload(self) -> None:
        image = _make_compressed_png(10, 10)
        payload = _make_pdf(page_count=2, image=image)
        storage = _RecordingStorage()

        with (
            patch.object(settings, "max_source_pdf_pages", 2),
            patch.object(settings, "max_source_document_images", 1),
            patch.object(settings, "max_source_document_image_pixels", 1_000),
            patch.object(source_images, "MIN_IMAGE_BYTES", 0),
        ):
            with self.assertRaises(source_images.SourceImageLimitError):
                source_images.extract_images_from_pdf(payload, "source-id", storage)

        self.assertEqual(storage.uploads, [])

    def test_small_compressed_image_with_too_many_pixels_is_rejected(self) -> None:
        image = _make_compressed_png(101, 100)
        payload = _make_pdf(page_count=1, image=image)
        storage = _RecordingStorage()

        with (
            patch.object(settings, "max_source_pdf_pages", 1),
            patch.object(settings, "max_source_document_images", 1),
            patch.object(settings, "max_source_document_image_pixels", 10_000),
            patch.object(source_images, "MIN_IMAGE_BYTES", 0),
        ):
            with self.assertRaises(source_images.SourceImageLimitError):
                source_images.extract_images_from_pdf(payload, "source-id", storage)

        self.assertEqual(storage.uploads, [])

    def test_image_count_and_pixel_boundaries_allow_normal_pdf(self) -> None:
        image = _make_compressed_png(100, 100)
        payload = _make_pdf(page_count=1, image=image)
        storage = _RecordingStorage()

        with (
            patch.object(settings, "max_source_pdf_pages", 1),
            patch.object(settings, "max_source_document_images", 1),
            patch.object(settings, "max_source_document_image_pixels", 10_000),
            patch.object(source_images, "MIN_IMAGE_BYTES", 0),
        ):
            images = source_images.extract_images_from_pdf(
                payload, "source-id", storage
            )

        self.assertEqual(len(images), 1)
        self.assertEqual(len(storage.uploads), 1)
        self.assertEqual(images[0].page_number, 1)


class SpreadsheetBudgetTests(unittest.TestCase):
    def test_csv_row_and_cell_boundaries_allow_normal_document(self) -> None:
        payload = b"name,value\nalpha,1\n"

        with (
            patch.object(settings, "max_source_spreadsheet_rows", 2),
            patch.object(settings, "max_source_spreadsheet_cells", 4),
        ):
            pages = _run(source_text._extract_text_from_file(payload, "normal.csv"))

        self.assertEqual(len(pages), 1)
        self.assertIn("alpha", pages[0]["content"])

    def test_csv_row_budget_is_checked_before_pandas(self) -> None:
        payload = b"name\nalpha\nbeta\n"

        with (
            patch.object(settings, "max_source_spreadsheet_rows", 2),
            patch.object(settings, "max_source_spreadsheet_cells", 10),
            patch("pandas.read_csv") as read_csv,
        ):
            with self.assertRaises(source_text.SourceDocumentLimitError):
                _run(source_text._extract_text_from_file(payload, "rows.csv"))

        read_csv.assert_not_called()

    def test_csv_materialized_cell_shape_is_bounded(self) -> None:
        payload = b'a"literal,b,c\n1\n'

        with (
            patch.object(settings, "max_source_spreadsheet_rows", 2),
            patch.object(settings, "max_source_spreadsheet_cells", 5),
            patch("pandas.read_csv") as read_csv,
        ):
            with self.assertRaises(source_text.SourceDocumentLimitError):
                _run(source_text._extract_text_from_file(payload, "cells.csv"))

        read_csv.assert_not_called()

    def test_xlsx_row_and_cell_boundaries_allow_normal_document(self) -> None:
        payload = _make_xlsx([["name", "value"], ["alpha", 1]])

        with (
            patch.object(settings, "max_source_spreadsheet_rows", 2),
            patch.object(settings, "max_source_spreadsheet_cells", 4),
        ):
            pages = _run(source_text._extract_text_from_file(payload, "normal.xlsx"))

        self.assertEqual(len(pages), 1)
        self.assertIn("alpha", pages[0]["content"])

    def test_xlsx_row_budget_is_checked_before_excel_parser(self) -> None:
        payload = _make_xlsx([["name"], ["alpha"], ["beta"]])

        with (
            patch.object(settings, "max_source_spreadsheet_rows", 2),
            patch.object(settings, "max_source_spreadsheet_cells", 10),
            patch("pandas.ExcelFile") as excel_file,
        ):
            with self.assertRaises(source_text.SourceDocumentLimitError):
                _run(source_text._extract_text_from_file(payload, "rows.xlsx"))

        excel_file.assert_not_called()

    def test_sparse_xlsx_dimension_bomb_is_checked_before_excel_parser(self) -> None:
        payload = _make_xlsx([["value"]])
        payload = _replace_sheet_dimension(payload, "A1:XFD1048576")

        with (
            patch.object(settings, "max_source_spreadsheet_rows", 100),
            patch.object(settings, "max_source_spreadsheet_cells", 1_000),
            patch("pandas.ExcelFile") as excel_file,
        ):
            with self.assertRaises(source_text.SourceDocumentLimitError):
                _run(source_text._extract_text_from_file(payload, "sparse.xlsx"))

        excel_file.assert_not_called()

    def test_legacy_xls_dimensions_enforce_boundary_and_overflow(self) -> None:
        release_resources = Mock()
        workbook = SimpleNamespace(
            nsheets=1,
            sheet_by_index=lambda _: SimpleNamespace(nrows=2, ncols=2),
            release_resources=release_resources,
        )
        with patch("xlrd.open_workbook", return_value=workbook):
            source_text._guard_xls_spreadsheet_bounds(
                b"xls", max_rows=2, max_cells=4, max_sheets=1
            )
        release_resources.assert_called_once_with()

        oversized_workbook = SimpleNamespace(
            nsheets=1,
            sheet_by_index=lambda _: SimpleNamespace(nrows=2, ncols=3),
            release_resources=Mock(),
        )
        with patch("xlrd.open_workbook", return_value=oversized_workbook):
            with self.assertRaises(source_text.SourceDocumentLimitError):
                source_text._guard_xls_spreadsheet_bounds(
                    b"xls", max_rows=2, max_cells=5, max_sheets=1
                )


if __name__ == "__main__":
    unittest.main()
