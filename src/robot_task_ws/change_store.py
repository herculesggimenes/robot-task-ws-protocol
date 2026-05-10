"""Revisioned resource store for concurrent package updates."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


class ChangeConflict(RuntimeError):
    def __init__(self, resource_id: str, expected: int, actual: int):
        super().__init__(f"revision conflict for {resource_id}: expected {expected}, actual {actual}")
        self.resource_id = resource_id
        self.expected = expected
        self.actual = actual


@dataclass
class Resource:
    revision: int = 0
    state: dict[str, Any] = field(default_factory=dict)
    last_change_id: str | None = None
    last_package_id: str | None = None


class ChangeStore:
    """Applies JSON-pointer-style patches with compare-and-swap revisions."""

    def __init__(self) -> None:
        self.resources: dict[str, Resource] = {}

    def snapshot(self) -> dict[str, Any]:
        return {
            resource_id: {
                "revision": resource.revision,
                "state": copy.deepcopy(resource.state),
                "last_change_id": resource.last_change_id,
                "last_package_id": resource.last_package_id,
            }
            for resource_id, resource in self.resources.items()
        }

    def get(self, resource_id: str) -> Resource:
        return self.resources.setdefault(resource_id, Resource())

    def apply(
        self,
        *,
        resource_id: str,
        base_revision: int | None,
        operations: list[dict[str, Any]],
        package_id: str,
        change_id: str,
    ) -> Resource:
        resource = self.get(resource_id)
        if base_revision is not None and base_revision != resource.revision:
            raise ChangeConflict(resource_id, base_revision, resource.revision)

        next_state = copy.deepcopy(resource.state)
        for operation in operations:
            apply_operation(next_state, operation)

        resource.revision += 1
        resource.state = next_state
        resource.last_change_id = change_id
        resource.last_package_id = package_id
        return resource


def apply_operation(document: dict[str, Any], operation: dict[str, Any]) -> None:
    op = operation.get("op")
    path = operation.get("path")
    if op not in {"add", "replace", "remove"}:
        raise ValueError(f"unsupported operation: {op}")
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError(f"invalid JSON pointer path: {path!r}")

    parent, key = resolve_parent(document, path)
    if op == "remove":
        if isinstance(parent, list):
            parent.pop(int(key))
        else:
            parent.pop(key, None)
        return

    value = operation.get("value")
    if isinstance(parent, list):
        index = len(parent) if key == "-" else int(key)
        if op == "add":
            parent.insert(index, value)
        else:
            parent[index] = value
    else:
        parent[key] = value


def resolve_parent(document: dict[str, Any], pointer: str) -> tuple[Any, str]:
    parts = [decode_pointer_part(part) for part in pointer.split("/")[1:]]
    if not parts:
        raise ValueError("path must point inside the document")
    current: Any = document
    for part in parts[:-1]:
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current.setdefault(part, {})
    return current, parts[-1]


def decode_pointer_part(part: str) -> str:
    return part.replace("~1", "/").replace("~0", "~")
