from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class Visibility(str, Enum):
    """Visibility boundary for a support knowledge audience."""

    INTERNAL = "internal"
    EXTERNAL = "external"


def _normalize_many(values: Iterable[str] | None) -> tuple[str, ...]:
    if values is None:
        return ()

    normalized: list[str] = []
    for raw_value in values:
        value = raw_value.strip()
        if not value:
            raise ValueError("audience dimension values must not be empty")
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized)


@dataclass(frozen=True, slots=True, kw_only=True)
class AudienceContext:
    """Runtime context used to resolve an audience filter."""

    visibility: Visibility
    brand: str | None = None
    product_line: str | None = None
    plan: str | None = None
    region: str | None = None
    language: str | None = None
    product_version: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "brand",
            "product_line",
            "plan",
            "region",
            "language",
            "product_version",
        ):
            value = getattr(self, field_name)
            if value is not None and not value.strip():
                raise ValueError(f"{field_name} must not be blank when provided")


@dataclass(frozen=True, slots=True, kw_only=True)
class AudienceFilter:
    """
    Declarative audience contract for support knowledge distribution.

    The filter is valid with only a visibility constraint, which models
    "all internal users" or "all external users" scopes.
    """

    visibility: Visibility
    brands: tuple[str, ...] = field(default_factory=tuple)
    product_lines: tuple[str, ...] = field(default_factory=tuple)
    plans: tuple[str, ...] = field(default_factory=tuple)
    regions: tuple[str, ...] = field(default_factory=tuple)
    languages: tuple[str, ...] = field(default_factory=tuple)
    product_versions: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "brands", _normalize_many(self.brands))
        object.__setattr__(self, "product_lines", _normalize_many(self.product_lines))
        object.__setattr__(self, "plans", _normalize_many(self.plans))
        object.__setattr__(self, "regions", _normalize_many(self.regions))
        object.__setattr__(self, "languages", _normalize_many(self.languages))
        object.__setattr__(
            self, "product_versions", _normalize_many(self.product_versions)
        )

    @property
    def is_global(self) -> bool:
        return not any(
            (
                self.brands,
                self.product_lines,
                self.plans,
                self.regions,
                self.languages,
                self.product_versions,
            )
        )

    def matches(self, context: AudienceContext) -> bool:
        if context.visibility is not self.visibility:
            return False

        dimension_pairs = (
            ("brands", context.brand),
            ("product_lines", context.product_line),
            ("plans", context.plan),
            ("regions", context.region),
            ("languages", context.language),
            ("product_versions", context.product_version),
        )

        for field_name, context_value in dimension_pairs:
            allowed_values = getattr(self, field_name)
            if not allowed_values:
                continue
            if context_value is None:
                return False
            if context_value not in allowed_values:
                return False
        return True

    def to_dict(self) -> dict[str, object]:
        return {
            "visibility": self.visibility.value,
            "brands": list(self.brands),
            "product_lines": list(self.product_lines),
            "plans": list(self.plans),
            "regions": list(self.regions),
            "languages": list(self.languages),
            "product_versions": list(self.product_versions),
            "is_global": self.is_global,
        }
