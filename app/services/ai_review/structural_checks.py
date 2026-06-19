"""
L2 structural checks — broken wikilinks, frontmatter sanity, malformed markdown.

Sync, DB-aware (needs an AsyncSession to verify wikilink targets exist).
"""

import re
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import WikiPage
from app.services import wiki_service

_HEADING_RE = re.compile(r"^(#{1,6})\s+\S", re.MULTILINE)


async def run(
    db: AsyncSession,
    content_md: str,
    self_slug: Optional[str],
    scope_type: str = "global",
    scope_id: Optional[uuid.UUID] = None,
) -> list[dict]:
    out: list[dict] = []
    if not content_md:
        return out

    # --- Broken wikilinks --------------------------------------------------
    targets = wiki_service.extract_wikilinks(content_md)
    broken: list[str] = []
    if targets:
        # Same-scope OR global resolution: a wikilink resolves to the same
        # scope first, then falls back to global. Anything that hits neither
        # is broken.
        rows = (await db.execute(
            select(WikiPage.slug).where(WikiPage.slug.in_(targets))
        )).all()
        existing = {r[0] for r in rows}
        broken = [t for t in targets if t not in existing and t != self_slug]
    out.append({
        "id": "links.broken",
        "layer": "L2",
        "severity": "warn",
        "status": "warn" if broken else "pass",
        "message": (
            f"{len(broken)} wikilink target(s) do not exist in any scope"
            if broken else None
        ),
        "matches": broken[:20],
    })

    # --- Self-link -------------------------------------------------------
    self_referential = bool(self_slug and self_slug in targets)
    out.append({
        "id": "links.self",
        "layer": "L2",
        "severity": "warn",
        "status": "warn" if self_referential else "pass",
        "message": "Page links back to itself" if self_referential else None,
        "matches": [self_slug] if self_referential and self_slug else [],
    })

    # --- Length sanity ----------------------------------------------------
    length = len(content_md)
    too_short = length < 100
    too_long = length > 45_000  # 50k hard cap; warn earlier
    out.append({
        "id": "length.sanity",
        "layer": "L2",
        "severity": "warn",
        "status": "warn" if (too_short or too_long) else "pass",
        "message": (
            f"Content is unusually short ({length} chars)" if too_short
            else f"Content is approaching the 50KB hard cap ({length} chars)"
            if too_long else None
        ),
        "matches": [],
    })

    # --- Heading hierarchy -----------------------------------------------
    headings = _HEADING_RE.findall(content_md)
    levels = [len(h) for h in headings]
    bad_jumps = []
    for i in range(1, len(levels)):
        if levels[i] - levels[i - 1] > 1:
            bad_jumps.append(f"H{levels[i - 1]} → H{levels[i]}")
    out.append({
        "id": "markdown.heading_jump",
        "layer": "L2",
        "severity": "warn",
        "status": "warn" if bad_jumps else "pass",
        "message": (
            f"Heading levels jump non-incrementally: {', '.join(bad_jumps[:5])}"
            if bad_jumps else None
        ),
        "matches": bad_jumps[:10],
    })

    # --- Unclosed code fences --------------------------------------------
    fence_count = content_md.count("\n```")
    # `content_md` doesn't always start with newline, so add a leading hint.
    if content_md.startswith("```"):
        fence_count += 1
    unclosed = (fence_count % 2) == 1
    out.append({
        "id": "markdown.unclosed_fence",
        "layer": "L2",
        "severity": "warn",
        "status": "warn" if unclosed else "pass",
        "message": "Code fence appears to be unclosed" if unclosed else None,
        "matches": [],
    })

    return out
