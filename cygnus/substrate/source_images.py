"""Substrate source image extraction primitives for Cygnus.

Ownership:
- document image extraction for source ingestion/compilation lives here
- these are source-media primitives, not runtime service ownership
- callers provide the storage adapter so substrate does not depend on runtime wiring
"""

from collections.abc import MutableMapping, Sequence
import io
from typing import Optional, Protocol

from loguru import logger

from cygnus.substrate.source_text import SourceParsingLimitError, _guard_zip_bounds

# Skip images smaller than this — they're almost always icons/decorators,
# not content. Tune via env later if needed.
MIN_IMAGE_BYTES = 2048


class SourceImageLimitError(SourceParsingLimitError):
    """Raised when embedded source images exceed deterministic parse budgets."""


def _source_image_limits() -> tuple[int, int, int, int, int]:
    from cygnus.runtime.config import settings

    return (
        settings.max_source_pdf_pages,
        settings.max_source_document_images,
        settings.max_source_document_image_pixels,
        settings.max_source_expanded_payload_bytes,
        settings.max_source_archive_bytes,
    )


def _image_pixels(width: object, height: object, *, label: str) -> int:
    if isinstance(width, bool) or not isinstance(width, (int, str, bytes, bytearray)):
        raise SourceImageLimitError(f"{label} dimensions are not valid")
    if isinstance(height, bool) or not isinstance(height, (int, str, bytes, bytearray)):
        raise SourceImageLimitError(f"{label} dimensions are not valid")
    try:
        bounded_width = int(width)
        bounded_height = int(height)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SourceImageLimitError(f"{label} dimensions are not valid") from exc
    if bounded_width <= 0 or bounded_height <= 0:
        raise SourceImageLimitError(f"{label} dimensions are not valid")
    return bounded_width * bounded_height


class SourceImageStorage(Protocol):
    def upload_file(
        self, object_name: str, data: bytes, content_type: str
    ) -> str | None: ...


def _mime_from_ext(ext: str) -> str:
    """Map extension to MIME type."""
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "bmp": "image/bmp",
        "tiff": "image/tiff",
        "webp": "image/webp",
        "svg": "image/svg+xml",
    }.get(ext.lower(), "image/png")


class ImageInfo:
    """Metadata about an extracted image."""

    def __init__(
        self,
        minio_key: str,
        page_number: Optional[int],
        image_index: int,
        content_type: str,
        size_bytes: int,
        caption: Optional[str] = None,
        image_id: Optional[str] = None,
    ):
        self.minio_key = minio_key
        self.page_number = page_number
        self.image_index = image_index
        self.content_type = content_type
        self.size_bytes = size_bytes
        self.caption = caption
        # Set after the row is persisted to source_images. The compiler
        # references this in `image://<uuid>` markers inside wiki content_md.
        self.image_id = image_id


def extract_images_from_pdf(
    file_data: bytes,
    source_id: str,
    storage: SourceImageStorage,
) -> list[ImageInfo]:
    """Extract bounded PDF images and upload them to object storage."""
    import fitz  # PyMuPDF

    images: list[ImageInfo] = []
    try:
        doc = fitz.open(stream=file_data, filetype="pdf")
    except Exception as exc:
        logger.warning(f"Failed to open PDF for image extraction: {exc}")
        return images

    (
        max_pages,
        max_images,
        max_image_pixels,
        max_image_bytes,
        max_total_image_bytes,
    ) = _source_image_limits()
    max_single_image_pixels = min(max_image_pixels, max_total_image_bytes // 4)
    try:
        page_count = doc.page_count
        if page_count > max_pages:
            raise SourceImageLimitError(
                f"PDF page count exceeds the limit of {max_pages}"
            )

        image_count = 0
        image_pixels = 0
        try:
            # Complete the cheap structural pass before extracting or uploading
            # any image so a late over-budget page cannot leave partial objects.
            for page_index in range(page_count):
                for image_reference in doc[page_index].get_images(full=True):
                    image_count += 1
                    if image_count > max_images:
                        raise SourceImageLimitError(
                            f"Embedded image count exceeds the limit of {max_images}"
                        )
                    if len(image_reference) < 4:
                        raise SourceImageLimitError(
                            "PDF embedded image metadata is not valid"
                        )
                    reference_pixels = _image_pixels(
                        image_reference[2],
                        image_reference[3],
                        label="PDF embedded image",
                    )
                    if reference_pixels > max_single_image_pixels:
                        raise SourceImageLimitError(
                            "PDF embedded image pixels exceed the per-image limit "
                            f"of {max_single_image_pixels}"
                        )
                    image_pixels += reference_pixels
                    if image_pixels > max_image_pixels:
                        raise SourceImageLimitError(
                            "Embedded image pixels exceed the limit of "
                            f"{max_image_pixels}"
                        )
        except SourceParsingLimitError:
            raise
        except Exception as exc:
            raise SourceImageLimitError(
                "PDF image structure could not be inspected safely"
            ) from exc

        image_index = 0
        extracted_pixels = 0
        extracted_bytes = 0
        for page_index in range(page_count):
            try:
                image_list = doc[page_index].get_images(full=True)
            except Exception as exc:
                raise SourceImageLimitError(
                    "PDF image structure changed during extraction"
                ) from exc
            for image_reference in image_list:
                try:
                    xref = image_reference[0]
                    base_image = doc.extract_image(xref)
                    if not base_image:
                        continue

                    image_bytes = base_image["image"]
                    image_size = len(image_bytes)
                    image_extension = base_image.get("ext", "png")
                    actual_image_pixels = _image_pixels(
                        base_image.get("width", image_reference[2]),
                        base_image.get("height", image_reference[3]),
                        label="Extracted PDF image",
                    )
                    if actual_image_pixels > max_single_image_pixels:
                        raise SourceImageLimitError(
                            "Extracted image pixels exceed the per-image limit of "
                            f"{max_single_image_pixels}"
                        )
                    extracted_pixels += actual_image_pixels
                    if extracted_pixels > max_image_pixels:
                        raise SourceImageLimitError(
                            "Extracted image pixels exceed the limit of "
                            f"{max_image_pixels}"
                        )
                    if image_size > max_image_bytes:
                        raise SourceImageLimitError(
                            "Extracted image exceeds the expanded payload limit of "
                            f"{max_image_bytes} bytes"
                        )
                    extracted_bytes += image_size
                    if extracted_bytes > max_total_image_bytes:
                        raise SourceImageLimitError(
                            "Extracted image bytes exceed the aggregate limit of "
                            f"{max_total_image_bytes} bytes"
                        )

                    if image_size < MIN_IMAGE_BYTES:
                        continue

                    content_type = _mime_from_ext(image_extension)
                    object_name = (
                        f"sources/{source_id}/images/"
                        f"page{page_index + 1}_{image_index}.{image_extension}"
                    )
                    storage.upload_file(
                        object_name=object_name,
                        data=image_bytes,
                        content_type=content_type,
                    )

                    images.append(
                        ImageInfo(
                            minio_key=object_name,
                            page_number=page_index + 1,
                            image_index=image_index,
                            content_type=content_type,
                            size_bytes=image_size,
                        )
                    )
                    image_index += 1
                except SourceParsingLimitError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "Failed to extract image "
                        f"{image_reference} from page {page_index}: {exc}"
                    )
                    continue
    finally:
        doc.close()

    logger.info(f"Extracted {len(images)} images from PDF (source {source_id})")
    return images


def extract_images_from_docx(
    file_data: bytes,
    source_id: str,
    storage: SourceImageStorage,
) -> list[ImageInfo]:
    """Extract bounded DOCX images and upload them to object storage."""
    from docx import Document

    _guard_zip_bounds(file_data)

    images: list[ImageInfo] = []
    try:
        doc = Document(io.BytesIO(file_data))
    except Exception as exc:
        logger.warning(f"Failed to open DOCX for image extraction: {exc}")
        return images

    (
        _,
        max_images,
        max_image_pixels,
        max_image_bytes,
        max_total_image_bytes,
    ) = _source_image_limits()
    max_single_image_pixels = min(max_image_pixels, max_total_image_bytes // 4)
    image_count = 0
    image_pixels = 0
    image_bytes = 0
    try:
        # python-docx has already indexed relationships; inspect every image
        # before the first upload so count/pixel/byte failures are atomic.
        for relationship in doc.part.rels.values():
            if "image" not in relationship.reltype:
                continue
            image_count += 1
            if image_count > max_images:
                raise SourceImageLimitError(
                    f"Embedded image count exceeds the limit of {max_images}"
                )
            image_part = relationship.target_part
            image_metadata = image_part.image
            reference_pixels = _image_pixels(
                image_metadata.px_width,
                image_metadata.px_height,
                label="DOCX embedded image",
            )
            if reference_pixels > max_single_image_pixels:
                raise SourceImageLimitError(
                    "DOCX embedded image pixels exceed the per-image limit of "
                    f"{max_single_image_pixels}"
                )
            image_pixels += reference_pixels
            if image_pixels > max_image_pixels:
                raise SourceImageLimitError(
                    f"Embedded image pixels exceed the limit of {max_image_pixels}"
                )
            blob_size = len(image_part.blob)
            if blob_size > max_image_bytes:
                raise SourceImageLimitError(
                    "Embedded image exceeds the expanded payload limit of "
                    f"{max_image_bytes} bytes"
                )
            image_bytes += blob_size
            if image_bytes > max_total_image_bytes:
                raise SourceImageLimitError(
                    "Embedded image bytes exceed the aggregate limit of "
                    f"{max_total_image_bytes} bytes"
                )
    except SourceParsingLimitError:
        raise
    except Exception as exc:
        raise SourceImageLimitError(
            "DOCX image structure could not be inspected safely"
        ) from exc

    image_index = 0
    for relationship in doc.part.rels.values():
        if "image" not in relationship.reltype:
            continue
        try:
            image_part = relationship.target_part
            image_blob = image_part.blob
            content_type = image_part.content_type or "image/png"
            extension = content_type.split("/")[-1]
            if extension == "svg+xml":
                extension = "svg"

            if len(image_blob) < MIN_IMAGE_BYTES:
                continue

            object_name = f"sources/{source_id}/images/docx_{image_index}.{extension}"
            storage.upload_file(
                object_name=object_name,
                data=image_blob,
                content_type=content_type,
            )

            images.append(
                ImageInfo(
                    minio_key=object_name,
                    page_number=None,
                    image_index=image_index,
                    content_type=content_type,
                    size_bytes=len(image_blob),
                )
            )
            image_index += 1
        except SourceParsingLimitError:
            raise
        except Exception as exc:
            logger.warning(f"Failed to extract DOCX image {image_index}: {exc}")
            continue

    logger.info(f"Extracted {len(images)} images from DOCX (source {source_id})")
    return images


def extract_images(
    file_data: bytes,
    file_name: str,
    source_id: str,
    storage: SourceImageStorage,
) -> list[ImageInfo]:
    """Auto-detect file type and extract images."""
    lower = file_name.lower()
    if lower.endswith(".pdf"):
        return extract_images_from_pdf(file_data, source_id, storage)
    elif lower.endswith(".docx"):
        return extract_images_from_docx(file_data, source_id, storage)
    else:
        logger.debug(f"No image extraction for file type: {file_name}")
        return []


def _sanitize_caption_for_alt(caption: str) -> str:
    """Make a caption safe to use inside markdown image alt text."""
    cleaned = caption.replace("\n", " ").replace("\r", " ")
    cleaned = cleaned.replace("[", "(").replace("]", ")")
    return cleaned.strip()


def inline_image_markers(
    pages_data: Sequence[MutableMapping[str, object]], images: list[ImageInfo]
) -> None:
    """Inject markdown image markers into per-page text."""
    if not images:
        return

    by_page: dict[int, list[str]] = {}
    for img in images:
        if not img.image_id:
            continue
        alt = _sanitize_caption_for_alt(img.caption or "")
        marker = f"![{alt}](image://{img.image_id})"
        page_num = img.page_number or 1
        by_page.setdefault(page_num, []).append(marker)

    if not by_page:
        return

    for page in pages_data:
        page_number = page.get("page_number")
        pnum = page_number if isinstance(page_number, int) else 1
        markers = by_page.get(pnum)
        if not markers:
            continue
        joined = "\n\n".join(markers)
        current_content = page.get("content")
        page["content"] = (
            current_content if isinstance(current_content, str) else ""
        ) + f"\n\n{joined}\n"
