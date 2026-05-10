#!/usr/bin/env python3
"""Minimal in-memory coordinator for the Robot Task WebSocket protocol."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import websockets
from websockets.server import WebSocketServerProtocol

PROTOCOL = "robot-task-ws"
VERSION = "0.1.0"


@dataclass
class CoordinatorState:
    clients: dict[WebSocketServerProtocol, dict[str, Any]] = field(default_factory=dict)
    pending_tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    claimed_tasks: dict[str, str] = field(default_factory=dict)


state = CoordinatorState()


def envelope(message_type: str, **fields: Any) -> dict[str, Any]:
    return {
        "type": message_type,
        "protocol": PROTOCOL,
        "version": VERSION,
        "timestamp": time.time(),
        **fields,
    }


async def broadcast(message: dict[str, Any], *, exclude: WebSocketServerProtocol | None = None) -> None:
    if not state.clients:
        return
    payload = json.dumps(message)
    await asyncio.gather(
        *(client.send(payload) for client in state.clients if client != exclude),
        return_exceptions=True,
    )


async def handle_message(ws: WebSocketServerProtocol, message: dict[str, Any]) -> None:
    message_type = message.get("type")

    if message.get("protocol") != PROTOCOL:
        await ws.send(json.dumps(envelope("error", error={"code": "wrong_protocol"})))
        return

    if message_type == "client.register":
        state.clients[ws] = message
        for task in state.pending_tasks.values():
            await ws.send(json.dumps(task))
        return

    if message_type == "task.request":
        task_id = message["id"]
        state.pending_tasks[task_id] = message
        await broadcast(message, exclude=ws)
        return

    if message_type == "task.claim":
        task_id = message["task_id"]
        client_id = message["client_id"]
        if task_id in state.claimed_tasks:
            await ws.send(
                json.dumps(
                    envelope(
                        "error",
                        id=task_id,
                        error={"code": "already_claimed", "message": "task already claimed"},
                    )
                )
            )
            return
        state.claimed_tasks[task_id] = client_id
        await broadcast(message)
        return

    if message_type == "task.result":
        task_id = message["task_id"]
        state.pending_tasks.pop(task_id, None)
        state.claimed_tasks.pop(task_id, None)
        await broadcast(message)
        return

    if message_type in {"image.frame", "robot.state", "motor.command", "stop"}:
        await broadcast(message, exclude=ws)
        return

    await ws.send(
        json.dumps(
            envelope(
                "error",
                error={"code": "unknown_type", "message": f"unknown message type: {message_type}"},
            )
        )
    )


async def handler(ws: WebSocketServerProtocol) -> None:
    state.clients[ws] = {}
    await ws.send(
        json.dumps(
            envelope(
                "hello",
                server_id="reference-coordinator",
                capabilities=["task_queue", "image_frames", "motor_commands"],
            )
        )
    )
    try:
        async for raw in ws:
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send(json.dumps(envelope("error", error={"code": "invalid_json"})))
                continue
            await handle_message(ws, message)
    finally:
        state.clients.pop(ws, None)


async def main() -> None:
    async with websockets.serve(handler, "127.0.0.1", 8765):
        print("robot-task-ws coordinator listening on ws://127.0.0.1:8765", flush=True)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
