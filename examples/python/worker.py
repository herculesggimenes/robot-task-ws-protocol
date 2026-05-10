#!/usr/bin/env python3
"""Example worker that claims perception tasks and returns a dummy result."""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from typing import Any

import websockets

PROTOCOL = "robot-task-ws"
VERSION = "0.1.0"


def envelope(message_type: str, **fields: Any) -> dict[str, Any]:
    return {
        "type": message_type,
        "protocol": PROTOCOL,
        "version": VERSION,
        "timestamp": time.time(),
        **fields,
    }


async def main(url: str) -> None:
    client_id = f"worker-{uuid.uuid4().hex[:8]}"
    async with websockets.connect(url) as ws:
        print(await ws.recv(), flush=True)
        await ws.send(
            json.dumps(
                envelope(
                    "client.register",
                    client_id=client_id,
                    role="perception",
                    capabilities=["perception.locate_pixel"],
                )
            )
        )

        async for raw in ws:
            message = json.loads(raw)
            if message.get("type") != "task.request":
                continue
            task = message.get("task", {})
            if task.get("kind") != "perception.locate_pixel":
                continue

            task_id = message["id"]
            await ws.send(json.dumps(envelope("task.claim", task_id=task_id, client_id=client_id)))
            await ws.send(
                json.dumps(
                    envelope(
                        "task.result",
                        task_id=task_id,
                        client_id=client_id,
                        ok=True,
                        result={
                            "target_u": 320,
                            "target_v": 240,
                            "gripper_u": 400,
                            "gripper_v": 240,
                            "confidence": 0.5,
                            "reason": "dummy reference worker result",
                        },
                    )
                )
            )


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8765"
    asyncio.run(main(target))
