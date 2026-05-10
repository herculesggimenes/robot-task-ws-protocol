"""Protocol constants and envelope helpers."""

from __future__ import annotations

import time
from typing import Any

PROTOCOL = "robot-task-ws"
VERSION = "0.1.0"


def envelope(message_type: str, **fields: Any) -> dict[str, Any]:
    """Build a protocol envelope."""
    return {
        "type": message_type,
        "protocol": PROTOCOL,
        "version": VERSION,
        "timestamp": time.time(),
        **fields,
    }


def client_register(client_id: str, role: str, capabilities: list[str]) -> dict[str, Any]:
    return envelope(
        "client.register",
        client_id=client_id,
        role=role,
        capabilities=capabilities,
    )
