from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderConfig:
    provider: str
    model_id: str
    capability: str
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("provider must not be blank")
        if not self.model_id.strip():
            raise ValueError("model_id must not be blank")
        if not self.capability.strip():
            raise ValueError("capability must not be blank")


class ProviderRegistry:
    def __init__(self) -> None:
        self._configs: dict[str, ProviderConfig] = {}

    def register(self, config: ProviderConfig) -> None:
        self._configs[config.capability] = config

    def get(self, capability: str) -> ProviderConfig:
        try:
            return self._configs[capability]
        except KeyError as exc:
            raise ValueError(f"no provider configured for capability={capability}") from exc

    def supported_capabilities(self) -> tuple[str, ...]:
        return tuple(sorted(self._configs))
