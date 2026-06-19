"""
L4 LLM judgment — tone consistency + factuality sniff.

Async — runs in arq worker. One LLM call (cheap with Gemini/Haiku) that
returns a small JSON verdict.
"""

import json
import re
from typing import Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

_SYSTEM = (
    "You are a wiki-quality reviewer. Inspect a draft page and return ONLY a "
    "JSON object with these fields:\n"
    "  tone_consistent: bool  (matches a factual, neutral, encyclopedic style)\n"
    "  factual_concerns: string[]  (specific claims that look unverified, "
    "speculative, or potentially wrong - max 5 short strings)\n"
    "  scope_fit: bool  (content matches the apparent topic / page_type)\n"
    "  notes: string  (one-sentence overall impression, max 200 chars)\n"
    "Be concise and conservative. If unsure, leave factual_concerns empty."
)

_PROMPT_TEMPLATE = (
    "Draft title: {title}\n"
    "Page type: {page_type}\n\n"
    "----- DRAFT MARKDOWN -----\n"
    "{content}\n"
    "----- END DRAFT -----\n\n"
    "Return the JSON verdict only."
)


async def run(
    db: AsyncSession,
    content_md: str,
    title: str,
    page_type: str,
) -> list[dict]:
    out: list[dict] = []
    try:
        from app.ai.registry import ProviderRegistry
        registry = ProviderRegistry(db)
        llm = await registry.get_llm()
    except Exception as e:
        logger.warning(f"AI L4 provider load failed: {e}")
        return [{
            "id": "llm.judgment",
            "layer": "L4",
            "severity": "warn",
            "status": "skipped",
            "message": f"LLM provider unavailable: {e}",
            "matches": [],
        }]

    # Cap input to keep cost predictable (~3-4k tokens).
    prompt = _PROMPT_TEMPLATE.format(
        title=title or "(untitled)",
        page_type=page_type or "concept",
        content=content_md[:8000],
    )
    try:
        raw = await llm.generate(
            prompt=prompt, system=_SYSTEM,
            max_tokens=400, temperature=0.0,
        )
    except Exception as e:
        logger.warning(f"AI L4 generate failed: {e}")
        return [{
            "id": "llm.judgment",
            "layer": "L4",
            "severity": "warn",
            "status": "skipped",
            "message": f"LLM call failed: {e}",
            "matches": [],
        }]

    parsed = _safe_json(raw)
    if parsed is None:
        return [{
            "id": "llm.judgment",
            "layer": "L4",
            "severity": "warn",
            "status": "skipped",
            "message": "LLM returned unparseable response",
            "matches": [],
        }]

    tone_ok = bool(parsed.get("tone_consistent", True))
    scope_ok = bool(parsed.get("scope_fit", True))
    concerns = [str(c) for c in (parsed.get("factual_concerns") or [])][:5]
    notes = str(parsed.get("notes") or "")[:200]

    out.append({
        "id": "llm.tone",
        "layer": "L4",
        "severity": "warn",
        "status": "pass" if tone_ok else "warn",
        "message": notes if tone_ok else f"Tone may be off: {notes}",
        "matches": [],
    })
    out.append({
        "id": "llm.scope_fit",
        "layer": "L4",
        "severity": "warn",
        "status": "pass" if scope_ok else "warn",
        "message": None if scope_ok else f"Content may not fit page_type='{page_type}'",
        "matches": [],
    })
    out.append({
        "id": "llm.factual",
        "layer": "L4",
        "severity": "warn",
        "status": "warn" if concerns else "pass",
        "message": (
            f"{len(concerns)} claim(s) flagged for verification" if concerns else None
        ),
        "matches": concerns,
    })
    return out


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _safe_json(raw: str) -> Optional[dict]:
    """Parse the LLM's JSON, accepting either a raw object or a fenced block."""
    if not raw:
        return None
    text = raw.strip()
    m = _JSON_FENCE_RE.search(text)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Sometimes models leak a preface — find first { and last }.
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
        return None
