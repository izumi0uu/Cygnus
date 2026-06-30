"""Substrate source image extraction primitives for Cygnus.

Ownership:
- document image extraction for source ingestion/compilation lives here
- these are source-media primitives, not runtime service ownership
- callers provide the storage adapter so substrate does not depend on runtime wiring
"""

import io
from typing import Optional, Protocol

from loguru import logger

# Skip images smaller than this — they're almost always icons/decorators,
# not content. Tune via env later if needed.
MIN_IMAGE_BYTES = 2048


class SourceImageStorage(Protocol):
    def upload_file(self, object_name: str, data: bytes, content_type: str) -> None: ...


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
    """
    Extract all images from a PDF file and upload to MinIO.
    Returns list of ImageInfo with MinIO keys.
    """
    import fitz  # PyMuPDF

    images: list[ImageInfo] = []
    try:
        doc = fitz.open(stream=file_data, filetype="pdf")
    except Exception as e:
        logger.warning(f"Failed to open PDF for image extraction: {e}")
        return images

    image_index = 0
    for page_num in range(len(doc)):
        page = doc[page_num]
        image_list = page.get_images(full=True)

        for img_ref in image_list:
            try:
                xref = img_ref[0]
                base_image = doc.extract_image(xref)
                if not base_image:
                    continue

                img_bytes = base_image["image"]
                img_ext = base_image.get("ext", "png")

                if len(img_bytes) < MIN_IMAGE_BYTES:
                    continue

                content_type = _mime_from_ext(img_ext)
                object_name = f"sources/{source_id}/images/page{page_num + 1}_{image_index}.{img_ext}"
                storage.upload_file(
                    object_name=object_name,
                    data=img_bytes,
                    content_type=content_type,
                )

                images.append(ImageInfo(
                    minio_key=object_name,
                    page_number=page_num + 1,
                    image_index=image_index,
                    content_type=content_type,
                    size_bytes=len(img_bytes),
                ))
                image_index += 1

            except Exception as e:
                logger.warning(f"Failed to extract image {img_ref} from page {page_num}: {e}")
                continue

    doc.close()
    logger.info(f"Extracted {len(images)} images from PDF (source {source_id})")
    return images


def extract_images_from_docx(
    file_data: bytes,
    source_id: str,
    storage: SourceImageStorage,
) -> list[ImageInfo]:
    """
    Extract all images from a DOCX file and upload to MinIO.
    """
    from docx import Document

    images: list[ImageInfo] = []
    try:
        doc = Document(io.BytesIO(file_data))
    except Exception as e:
        logger.warning(f"Failed to open DOCX for image extraction: {e}")
        return images

    image_index = 0
    for rel in doc.part.rels.values():
        if "image" in rel.reltype:
            try:
                img_blob = rel.target_part.blob
                content_type = rel.target_part.content_type or "image/png"
                ext = content_type.split("/")[-1]
                if ext == "svg+xml":
                    ext = "svg"

                if len(img_blob) < MIN_IMAGE_BYTES:
                    continue

                object_name = f"sources/{source_id}/images/docx_{image_index}.{ext}"
                storage.upload_file(
                    object_name=object_name,
                    data=img_blob,
                    content_type=content_type,
                )

                images.append(ImageInfo(
                    minio_key=object_name,
                    page_number=None,  # DOCX doesn't expose page numbers easily
                    image_index=image_index,
                    content_type=content_type,
                    size_bytes=len(img_blob),
                ))
                image_index += 1

            except Exception as e:
                logger.warning(f"Failed to extract DOCX image {image_index}: {e}")
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


def inline_image_markers(pages_data: list[dict], images: list[ImageInfo]) -> None:
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
        pnum = page.get("page_number") or 1
        markers = by_page.get(pnum)
        if not markers:
            continue
        joined = "\n\n".join(markers)
        page["content"] = (page.get("content") or "") + f"\n\n{joined}\n"
