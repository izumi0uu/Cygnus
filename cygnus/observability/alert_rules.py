"""Fail-closed rendering for deployment-approved Prometheus alert rules.

The checked-in rule file is a tokenized template. Numeric alert limits are
never repository defaults: production supplies one reviewed JSON document whose
identity and exact bytes are bound to the deployment input gate. Rendering
rejects incomplete, unapproved, malformed, or stale inputs before emitting a
Prometheus-consumable rule file.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re


class AlertThresholdInputError(ValueError):
    """Raised when deployment alert limits cannot be safely rendered."""


# These are policy *names*, not policy values. The approved external JSON must
# carry every value, so adding an alert expression requires an explicit input
# and approval update rather than silently inheriting a repository default.
ALERT_THRESHOLD_KEYS: tuple[str, ...] = (
    "http_error_rate",
    "http_latency_seconds",
    "mcp_error_rate",
    "mcp_deadline_exceeded_count",
    "http_denial_rate",
    "http_retry_count",
    "queue_age_seconds",
    "queue_terminal_count",
    "governance_exhausted_count",
    "propagation_mismatch_count",
    "db_pool_saturation",
    "telemetry_failure_count",
    "stale_evidence_count",
)

_FRACTION_KEYS = frozenset(
    {
        "http_error_rate",
        "mcp_error_rate",
        "http_denial_rate",
        "db_pool_saturation",
    }
)
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_TOKEN_RE = re.compile(r"\{\{alert\.([a-z0-9_]+)\}\}")
_PLACEHOLDERS = ("change_me", "replace", "example", "todo", "pending", "unknown", "<")


@dataclass(frozen=True, slots=True)
class AlertThresholdInputs:
    """Approved identity and numeric values consumed by a rule render."""

    approval_ref: str
    thresholds_ref: str
    thresholds_sha256: str
    thresholds: dict[str, float]

    @property
    def labels(self) -> dict[str, str]:
        """Return the non-secret provenance labels written to every rule."""
        return {
            "approval_ref": self.approval_ref,
            "thresholds_ref": self.thresholds_ref,
            "thresholds_sha256": self.thresholds_sha256,
        }


def _require_ref(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise AlertThresholdInputError(f"{label} must be a non-secret reference")
    normalized = value.strip()
    if not normalized or not _REF_RE.fullmatch(normalized):
        raise AlertThresholdInputError(f"{label} must be a bounded reference")
    if any(marker in normalized.lower() for marker in _PLACEHOLDERS):
        raise AlertThresholdInputError(f"{label} is a placeholder, not an approval")
    return normalized


def _require_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise AlertThresholdInputError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _number(value: object, *, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AlertThresholdInputError(f"thresholds.{key} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        raise AlertThresholdInputError(
            f"thresholds.{key} must be finite and non-negative"
        )
    if key in _FRACTION_KEYS and numeric > 1:
        raise AlertThresholdInputError(
            f"thresholds.{key} must be a fraction no greater than 1"
        )
    return numeric


def _promql_number(value: float) -> str:
    """Serialize one validated value as a literal without executable syntax."""
    if value.is_integer():
        return str(int(value))
    return format(value, ".15g")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def load_alert_threshold_inputs(
    path: Path,
    *,
    expected_approval_ref: str,
    expected_thresholds_ref: str,
    expected_thresholds_sha256: str,
) -> AlertThresholdInputs:
    """Load one approved alert-limit document and bind it to deploy inputs."""
    expected_approval = _require_ref(
        expected_approval_ref, label="expected approval_ref"
    )
    expected_ref = _require_ref(
        expected_thresholds_ref, label="expected thresholds_ref"
    )
    expected_hash = _require_sha256(
        expected_thresholds_sha256, label="expected thresholds_sha256"
    )
    actual_hash = _sha256_file(path)
    if actual_hash != expected_hash:
        raise AlertThresholdInputError(
            "alert threshold file hash does not match expected thresholds_sha256"
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AlertThresholdInputError(
            f"cannot load alert threshold file: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise AlertThresholdInputError("alert threshold file must be a JSON object")

    approval = raw.get("approval")
    if not isinstance(approval, dict):
        raise AlertThresholdInputError("approval must be an object")
    approval_ref = _require_ref(
        approval.get("approval_ref"), label="approval.approval_ref"
    )
    thresholds_ref = _require_ref(
        approval.get("thresholds_ref"), label="approval.thresholds_ref"
    )
    if approval_ref != expected_approval:
        raise AlertThresholdInputError(
            "approval.approval_ref does not match deploy input"
        )
    if thresholds_ref != expected_ref:
        raise AlertThresholdInputError(
            "approval.thresholds_ref does not match deploy input"
        )

    raw_thresholds = raw.get("thresholds")
    if not isinstance(raw_thresholds, dict):
        raise AlertThresholdInputError("thresholds must be an object")
    expected_keys = set(ALERT_THRESHOLD_KEYS)
    actual_keys = set(raw_thresholds)
    if missing := expected_keys - actual_keys:
        raise AlertThresholdInputError(
            f"thresholds missing required keys: {sorted(missing)}"
        )
    if extra := actual_keys - expected_keys:
        raise AlertThresholdInputError(
            f"thresholds contains unknown keys: {sorted(extra)}"
        )
    thresholds = {
        key: _number(raw_thresholds[key], key=key) for key in ALERT_THRESHOLD_KEYS
    }
    return AlertThresholdInputs(
        approval_ref=approval_ref,
        thresholds_ref=thresholds_ref,
        thresholds_sha256=actual_hash,
        thresholds=thresholds,
    )


def _render_threshold_tokens(
    template: str,
    replacements: dict[str, str],
) -> str:
    referenced = set(_TOKEN_RE.findall(template))
    if missing := set(ALERT_THRESHOLD_KEYS) - referenced:
        raise AlertThresholdInputError(
            f"rule template is missing alert threshold tokens: {sorted(missing)}"
        )
    if unknown := referenced - set(replacements):
        raise AlertThresholdInputError(
            f"rule template references unknown alert thresholds: {sorted(unknown)}"
        )

    def replace(match: re.Match[str]) -> str:
        return replacements[match.group(1)]

    rendered = _TOKEN_RE.sub(replace, template)
    if "{{alert." in rendered:
        raise AlertThresholdInputError(
            "rendered alert rules retain unresolved thresholds"
        )
    return rendered


def _inject_provenance_labels(
    template: str,
    labels: dict[str, str],
) -> str:
    """Add approval identity to each concrete labels mapping.

    YAML aliases (the capacity-rule `*capacity_labels` mappings) inherit the
    labels injected into their one anchored mapping and therefore must not be
    expanded here.
    """
    source_lines = template.splitlines()
    alert_indexes = [
        index
        for index, line in enumerate(source_lines)
        if re.match(r"^\s*-\s+alert:\s*\S+", line)
    ]
    if not alert_indexes:
        raise AlertThresholdInputError("rule template contains no alerts")
    for offset, start in enumerate(alert_indexes):
        end = (
            alert_indexes[offset + 1]
            if offset + 1 < len(alert_indexes)
            else len(source_lines)
        )
        if not any(
            re.match(r"^\s+labels:\s*(?:&\S+|\*\S+)?\s*$", line)
            for line in source_lines[start:end]
        ):
            raise AlertThresholdInputError(
                f"alert template at line {start + 1} has no labels mapping"
            )

    output: list[str] = []
    for line in source_lines:
        output.append(line)
        match = re.match(r"^(?P<indent>\s+)labels:(?P<suffix>.*)$", line)
        if match is None or match.group("suffix").strip().startswith("*"):
            continue
        indent = f"{match.group('indent')}  "
        for key, value in labels.items():
            output.append(f"{indent}{key}: {json.dumps(value)}")
    return "\n".join(output) + "\n"


def render_alert_rules(
    template_path: Path,
    inputs: AlertThresholdInputs,
) -> str:
    """Render approved inputs into Prometheus-compatible YAML text."""
    try:
        template = template_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AlertThresholdInputError(
            f"cannot load alert-rule template: {exc}"
        ) from exc

    replacements = {
        key: _promql_number(value) for key, value in inputs.thresholds.items()
    }
    rendered = _render_threshold_tokens(template, replacements)
    return _inject_provenance_labels(rendered, inputs.labels)


def write_rendered_alert_rules(
    output_path: Path,
    *,
    template_path: Path,
    inputs: AlertThresholdInputs,
) -> None:
    """Atomically replace the deployment rule file after full validation."""
    if output_path.resolve() == template_path.resolve():
        raise AlertThresholdInputError(
            "rendered alert output must not overwrite the source template"
        )
    rendered = render_alert_rules(template_path, inputs)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(f"{output_path.suffix}.tmp")
    temporary.write_text(
        "# Generated from approved external alert thresholds; do not hand-edit.\n"
        + rendered,
        encoding="utf-8",
    )
    temporary.replace(output_path)


__all__ = [
    "ALERT_THRESHOLD_KEYS",
    "AlertThresholdInputError",
    "AlertThresholdInputs",
    "load_alert_threshold_inputs",
    "render_alert_rules",
    "write_rendered_alert_rules",
]
