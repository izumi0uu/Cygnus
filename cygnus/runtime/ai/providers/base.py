"""
Abstract base classes for AI providers.

Every provider (Google, OpenAI, Anthropic, Ollama…) implements these
interfaces so the rest of the codebase never imports a specific SDK.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from time import monotonic_ns
from typing import TYPE_CHECKING, Optional

from cygnus.observability import record_provider

if TYPE_CHECKING:
    from cygnus.substrate.agent_protocol import AssistantTurn


def _numeric_usage(usage: object, *names: str) -> int | float | None:
    for name in names:
        value = getattr(usage, name, None)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if value >= 0:
            return value
    return None


def _provider_usage(
    response: object | None,
) -> tuple[int | float | None, int | float | None, int | float | None]:
    if response is None:
        return None, None, None
    usage = getattr(response, "usage", None)
    if usage is None:
        usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return None, None, None
    input_tokens = _numeric_usage(
        usage,
        "input_tokens",
        "prompt_tokens",
        "prompt_token_count",
    )
    output_tokens = _numeric_usage(
        usage,
        "output_tokens",
        "completion_tokens",
        "candidates_token_count",
    )
    total_tokens = _numeric_usage(usage, "total_tokens", "total_token_count")
    return input_tokens, output_tokens, total_tokens


@dataclass(slots=True)
class ProviderCallObservation:
    """Record one raw provider boundary, including failures and token usage."""

    provider: str
    model: str
    operation: str
    started_ns: int = field(default_factory=monotonic_ns)
    response: object | None = None
    succeeded: bool = False

    def success(self, response: object) -> object:
        self.response = response
        self.succeeded = True
        return response

    def __enter__(self) -> "ProviderCallObservation":
        return self

    def __exit__(self, exc_type: object, _exc: object, _traceback: object) -> None:
        try:
            input_tokens, output_tokens, total_tokens = _provider_usage(self.response)
        except Exception:
            input_tokens = output_tokens = total_tokens = None
        try:
            record_provider(
                provider=self.provider,
                model=self.model,
                operation=self.operation,
                status="ok" if exc_type is None and self.succeeded else "error",
                duration_ms=max(
                    (monotonic_ns() - self.started_ns) / 1_000_000,
                    0.0,
                ),
                tokens=total_tokens,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        except Exception:
            # Telemetry must never mask a provider response or exception.
            return


def observe_provider_call(
    *, provider: str, model: str, operation: str
) -> ProviderCallObservation:
    """Return a context manager that cannot expose prompts, responses, or keys."""

    return ProviderCallObservation(
        provider=provider,
        model=model,
        operation=operation,
    )


# ---------------------------------------------------------------------------
# Provider enum — add new providers here
# ---------------------------------------------------------------------------


class ProviderType(str, Enum):
    GOOGLE = "google"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"
    VOYAGE = "voyage"
    COHERE = "cohere"


# ---------------------------------------------------------------------------
# Runtime config loaded from DB
# ---------------------------------------------------------------------------


@dataclass
class ProviderConfig:
    """
    Configuration for a single provider instance.
    Loaded from DB by ProviderRegistry at runtime.

    `spec` is a reference back to the catalog entry (LLMModelSpec /
    VisionModelSpec / EmbeddingModelSpec) when one applies. Callers that
    need capability metadata (context window, supports_tools, ...) read it
    from `config.spec` rather than hard-coding per model_id.
    """

    provider: ProviderType
    api_key: str = ""
    model_id: str = ""
    base_url: Optional[str] = None  # For Ollama, Azure, proxies
    dimensions: Optional[int] = None  # Embedding output dimensions
    extra: dict = field(default_factory=dict)  # Provider-specific params
    spec: Optional[object] = None  # LLMModelSpec | VisionModelSpec | EmbeddingModelSpec


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


class EmbeddingProvider(ABC):
    """Generate vector embeddings for text."""

    def __init__(self, config: ProviderConfig):
        self.config = config

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Embed a single text string."""
        ...

    @abstractmethod
    async def embed_batch(
        self, texts: list[str], concurrency: int = 5
    ) -> list[list[float]]:
        """Embed multiple texts with concurrency control."""
        ...

    @abstractmethod
    async def test_connection(self) -> tuple[bool, str]:
        """
        Test if the provider is reachable and credentials are valid.
        Returns (success, human-readable message).
        """
        ...

    @property
    def dimensions(self) -> int:
        """Output vector dimensions."""
        return self.config.dimensions or 768


# ---------------------------------------------------------------------------
# LLM (text generation)
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Generate text — used for summarization, webhook gateway, etc."""

    def __init__(self, config: ProviderConfig):
        self.config = config

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
    ) -> str:
        """Generate a text completion."""
        ...

    async def generate_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.2,
    ) -> "AssistantTurn":
        """
        Multi-turn tool-calling. Messages use neutral format from agent_protocol.
        Returns AssistantTurn with tool_calls (if any) and finish_reason.
        Override in providers that support tool calling.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support tool calling. "
            "Configure a provider that supports function calling (Anthropic, OpenAI, Google)."
        )

    @abstractmethod
    async def test_connection(self) -> tuple[bool, str]: ...


# ---------------------------------------------------------------------------
# Vision (image analysis)
# ---------------------------------------------------------------------------


class VisionProvider(ABC):
    """Analyze images — used during document ingestion for image captioning."""

    def __init__(self, config: ProviderConfig):
        self.config = config

    @abstractmethod
    async def analyze_image(
        self,
        image_data: bytes,
        mime_type: str = "image/jpeg",
        prompt: Optional[str] = None,
    ) -> str:
        """Analyze an image and return a text description."""
        ...

    @abstractmethod
    async def test_connection(self) -> tuple[bool, str]: ...
