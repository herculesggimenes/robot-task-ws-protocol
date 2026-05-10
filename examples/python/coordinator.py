#!/usr/bin/env python3
"""Minimal in-memory coordinator for the Robot Task WebSocket protocol."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import websockets

PROTOCOL = "robot-task-ws"
VERSION = "0.1.0"


@dataclass
class CoordinatorState:
    clients: dict[Any, dict[str, Any]] = field(default_factory=dict)
    pending_tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    claimed_tasks: dict[str, str] = field(default_factory=dict)
    latest: dict[str, dict[str, Any]] = field(default_factory=dict)


state = CoordinatorState()


def envelope(message_type: str, **fields: Any) -> dict[str, Any]:
    return {
        "type": message_type,
        "protocol": PROTOCOL,
        "version": VERSION,
        "timestamp": time.time(),
        **fields,
    }


async def broadcast(message: dict[str, Any], *, exclude: Any | None = None) -> None:
    if not state.clients:
        return
    payload = json.dumps(message)
    await asyncio.gather(
        *(client.send(payload) for client in state.clients if client != exclude),
        return_exceptions=True,
    )


async def handle_message(ws: Any, message: dict[str, Any]) -> None:
    message_type = message.get("type")

    if message.get("protocol") != PROTOCOL:
        await ws.send(json.dumps(envelope("error", error={"code": "wrong_protocol"})))
        return

    if message_type == "client.register":
        state.clients[ws] = message
        await ws.send(json.dumps(snapshot()))
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

    if message_type in {"image.frame", "robot.state", "leader.state", "status.report"}:
        remember_latest(message)
        await broadcast(message, exclude=ws)
        return

    if message_type in {"motor.command", "stop"}:
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


def remember_latest(message: dict[str, Any]) -> None:
    message_type = message["type"]
    if message_type == "image.frame":
        key = f"image.frame:{message.get('camera_id', 'unknown')}"
    elif message_type == "robot.state":
        key = f"robot.state:{message.get('robot_id', 'unknown')}"
    elif message_type == "leader.state":
        key = f"leader.state:{message.get('leader_id', 'unknown')}"
    elif message_type == "status.report":
        key = f"status.report:{message.get('component_id', 'unknown')}"
    else:
        key = message_type
    state.latest[key] = message


def snapshot() -> dict[str, Any]:
    return envelope(
        "status.report",
        component_id="reference-coordinator",
        role="coordinator",
        status="ok",
        details={
            "clients": [
                {
                    "client_id": client.get("client_id"),
                    "role": client.get("role"),
                    "capabilities": client.get("capabilities", []),
                }
                for client in state.clients.values()
                if client
            ],
            "pending_tasks": list(state.pending_tasks),
            "claimed_tasks": state.claimed_tasks,
            "latest": list(state.latest.values()),
        },
    )


async def handler(ws: Any) -> None:
    state.clients[ws] = {}
    await ws.send(
        json.dumps(
            envelope(
                "hello",
                server_id="reference-coordinator",
                capabilities=[
                    "task_queue",
                    "image_frames",
                    "robot_state",
                    "leader_state",
                    "status_reports",
                    "motor_commands",
                ],
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
