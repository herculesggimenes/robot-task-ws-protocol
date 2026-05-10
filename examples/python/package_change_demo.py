#!/usr/bin/env python3
"""Demonstrate simultaneous state.patch messages from two packages."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any

import websockets

from robot_task_ws.protocol import PROTOCOL, VERSION, client_register


async def package_client(url: str, package_id: str, patch: dict[str, Any]) -> None:
    async with websockets.connect(url) as ws:
        await ws.recv()
        await ws.send(
            json.dumps(
                {
                    **client_register(
                        client_id=f"{package_id}-demo",
                        role="demo",
                        capabilities=["state.patch"],
                    ),
                    "package_id": package_id,
                }
            )
        )
        await ws.recv()
        await ws.send(json.dumps(patch))
        async for raw in ws:
            message = json.loads(raw)
            if message.get("type") in {"state.accepted", "state.conflict"} and message.get("change_id") == patch["change_id"]:
                print(f"{package_id}: {json.dumps(message, indent=2)}", flush=True)
                return
            if message.get("type") == "error":
                print(f"{package_id}: {json.dumps(message, indent=2)}", flush=True)
                return


async def main(url: str) -> None:
    resource_id = "demo/shared-plan"
    base = {
        "type": "state.patch",
        "protocol": PROTOCOL,
        "version": VERSION,
        "resource_id": resource_id,
        "base_revision": 0,
    }
    await asyncio.gather(
        package_client(
            url,
            "planner",
            {
                **base,
                "change_id": f"planner-{time.time_ns()}",
                "package_id": "planner",
                "operations": [{"op": "add", "path": "/planner_step", "value": "locate target"}],
            },
        ),
        package_client(
            url,
            "safety",
            {
                **base,
                "change_id": f"safety-{time.time_ns()}",
                "package_id": "safety",
                "operations": [{"op": "add", "path": "/max_speed", "value": 0.1}],
            },
        ),
    )


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8765"
    asyncio.run(main(target))
