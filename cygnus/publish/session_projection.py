from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from cygnus.publish.actions import PublishGovernanceResult


@dataclass(frozen=True, slots=True, kw_only=True)
class PublishProjectionSnapshot:
    object_id: str
    selected_action: str
    result: PublishGovernanceResult


class PublishProjectionStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._snapshots: dict[str, PublishProjectionSnapshot] = {}

    def remember(
        self,
        object_id: str,
        *,
        selected_action: str,
        result: PublishGovernanceResult,
    ) -> PublishProjectionSnapshot:
        snapshot = PublishProjectionSnapshot(
            object_id=object_id,
            selected_action=selected_action,
            result=result,
        )
        with self._lock:
            self._snapshots[object_id] = snapshot
        return snapshot

    def get(self, object_id: str) -> PublishProjectionSnapshot | None:
        with self._lock:
            return self._snapshots.get(object_id)

    def clear(self) -> None:
        with self._lock:
            self._snapshots.clear()


projection_store = PublishProjectionStore()


def remember_publish_projection(
    object_id: str,
    *,
    selected_action: str,
    result: PublishGovernanceResult,
) -> PublishProjectionSnapshot:
    return projection_store.remember(
        object_id,
        selected_action=selected_action,
        result=result,
    )


def get_publish_projection(object_id: str) -> PublishProjectionSnapshot | None:
    return projection_store.get(object_id)


def clear_publish_projections() -> None:
    projection_store.clear()
