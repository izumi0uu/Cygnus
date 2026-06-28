"""Token counting for extracted document text.

Uses tiktoken's cl100k_base (GPT-4 encoding) as a universal estimator. Not
identical to Claude/Gemini tokenizers but close enough for sizing decisions
(within ~10-15%). Vietnamese and other non-Latin scripts produce more tokens
per char than English — cl100k_base handles this correctly.
"""

from functools import lru_cache

import tiktoken


@lru_cache(maxsize=1)
def _encoding():
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Return token count for `text`. Empty/None → 0."""
    if not text:
        return 0
    return len(_encoding().encode(text, disallowed_special=()))
