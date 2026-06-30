"""
Source ingest orchestration for the Cygnus runtime shell.

Ownership:
- file/url source ingest orchestration, source-media persistence, and wiki-compilation handoff live here
- source text/image/outline extraction primitives stay under ``cygnus.substrate``
- runtime storage, provider registry, and source-row mutation wiring stay in the runtime shell
- this module owns source-ingest execution orchestration, not generic runtime service catalog truth
"""

import uuid
from typing import Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.ai.registry import ProviderRegistry
from cygnus.runtime.ai.wiki_compiler import compile_source_into_wiki
from cygnus.runtime.database.models import KnowledgeType, Source, SourceImage
from cygnus.runtime.services.storage_service import storage_service
from cygnus.substrate.source_images import ImageInfo, extract_images, inline_image_markers
from cygnus.substrate.source_outline import assemble_full_text, build_outline
from cygnus.substrate.source_text import _extract_text_from_file, _extract_text_from_url, _guess_content_type


async def ingest_source(
    session: AsyncSession,
    source_id: uuid.UUID,
    file_data: Optional[bytes] = None,
    file_name: Optional[str] = None,
) -> Source:
    """
    Ingest a Source into the wiki:
      1. Upload original file to MinIO (if file)
      2. Extract text per page
      3. Extract images, caption with vision provider, inline captions
      4. Build heading-based outline → Source.outline_json
      5. Compile into wiki via LLM (creates/updates WikiPage rows)
    """
    source = await session.get(Source, source_id)
    if not source:
        raise ValueError(f"Source {source_id} not found")

    try:
        registry = ProviderRegistry(session)
        vision_provider = await registry.get_vision()

        source.status = "processing"
        await session.flush()

        if file_data and file_name:
            minio_key = f"sources/{source_id}/original/{file_name}"
            storage_service.upload_file(
                object_name=minio_key,
                data=file_data,
                content_type=_guess_content_type(file_name),
            )
            source.minio_key = minio_key
            source.file_name = file_name
            source.file_size = len(file_data)

        if file_data and file_name:
            pages_data = await _extract_text_from_file(file_data, file_name, vision_provider=vision_provider)
        elif source.url:
            pages_data = await _extract_text_from_url(source.url)
        else:
            pages_data = []

        if not pages_data or not any((page.get("content") or "").strip() for page in pages_data):
            source.status = "error"
            source.error_message = "Could not extract text content from source"
            await session.flush()
            return source

        images: list[ImageInfo] = []
        if file_data and file_name:
            images = extract_images(file_data, file_name, str(source_id), storage_service)
            if vision_provider and images:
                for idx, image in enumerate(images, 1):
                    try:
                        if idx % 5 == 0 or idx == 1 or idx == len(images):
                            logger.info(f"Vision AI analyzing image {idx}/{len(images)}...")
                        img_bytes = storage_service.download_file(image.minio_key)
                        image.caption = await vision_provider.analyze_image(
                            img_bytes,
                            image.content_type,
                        )
                    except Exception as exc:
                        logger.warning(f"Failed to analyze image {image.minio_key}: {exc}")

            for image in images:
                row = SourceImage(
                    source_id=source_id,
                    minio_key=image.minio_key,
                    page_number=image.page_number,
                    image_index=image.image_index,
                    caption=image.caption,
                    content_type=image.content_type,
                    size_bytes=image.size_bytes,
                )
                session.add(row)
                await session.flush()
                image.image_id = str(row.id)

        inline_image_markers(pages_data, images)

        source.outline_json = build_outline(pages_data)
        full_text, page_offsets = assemble_full_text(pages_data)
        source.full_text = full_text
        source.page_offsets = page_offsets

        kt_slug = kt_name = kt_desc = None
        if source.knowledge_type_id:
            knowledge_type = await session.get(KnowledgeType, source.knowledge_type_id)
            if knowledge_type:
                kt_slug = knowledge_type.slug
                kt_name = knowledge_type.name
                kt_desc = knowledge_type.description

        result = await compile_source_into_wiki(
            session=session,
            source=source,
            full_text=full_text,
            knowledge_type_slug=kt_slug,
            knowledge_type_name=kt_name,
            knowledge_type_description=kt_desc,
        )

        source.status = "ready"
        source.error_message = None
        source.auto_recover_count = 0
        await session.flush()
        logger.success(
            f"Source {source_id} ingested into wiki: "
            f"+{result['pages_created']} pages, ~{result['pages_updated']} updated"
        )
        return source

    except Exception as exc:
        logger.error(f"Ingestion failed for source {source_id}: {exc}")
        source.status = "error"
        source.error_message = str(exc)[:500]
        await session.flush()
        raise
