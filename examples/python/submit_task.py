#!/usr/bin/env python3
"""Submit one demo task to a Robot Task WebSocket coordinator."""

from __future__ import annotations

import asyncio
import json
import sys
import time
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
    async with websockets.connect(url) as ws:
        print(await ws.recv(), flush=True)
        await ws.send(
            json.dumps(
                envelope(
                    "client.register",
                    client_id="demo-submitter",
                    role="operator",
                    capabilities=["task.request"],
                )
            )
        )
        await ws.send(
            json.dumps(
                envelope(
                    "task.request",
                    id=f"task-{time.time_ns()}",
                    task={
                        "kind": "perception.locate_pixel",
                        "prompt": "Find the target object and the gripper in the latest image.",
                        "inputs": {"frame_ids": ["latest"]},
                        "constraints": {"timeout_ms": 3000},
                    },
                )
            )
        )

        async for raw in ws:
            message = json.loads(raw)
            print(json.dumps(message, indent=2), flush=True)
            if message.get("type") == "task.result":
                return


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8765"
    asyncio.run(main(target))
