"""Reference coordinator implementation."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import websockets

from .change_store import ChangeConflict, ChangeStore
from .protocol import PROTOCOL, envelope


@dataclass
class CoordinatorState:
    clients: dict[Any, dict[str, Any]] = field(default_factory=dict)
    pending_tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    claimed_tasks: dict[str, str] = field(default_factory=dict)
    latest: dict[str, dict[str, Any]] = field(default_factory=dict)
    changes: ChangeStore = field(default_factory=ChangeStore)


class Coordinator:
    def __init__(self) -> None:
        self.state = CoordinatorState()

    async def broadcast(self, message: dict[str, Any], *, exclude: Any | None = None) -> None:
        if not self.state.clients:
            return
        payload = json.dumps(message)
        await asyncio.gather(
            *(client.send(payload) for client in self.state.clients if client != exclude),
            return_exceptions=True,
        )

    async def handle_message(self, ws: Any, message: dict[str, Any]) -> None:
        message_type = message.get("type")

        if message.get("protocol") != PROTOCOL:
            await ws.send(json.dumps(envelope("error", error={"code": "wrong_protocol"})))
            return

        if message_type == "client.register":
            self.state.clients[ws] = message
            await ws.send(json.dumps(self.snapshot()))
            for task in self.state.pending_tasks.values():
                await ws.send(json.dumps(task))
            return

        if message_type == "task.request":
            task_id = message["id"]
            self.state.pending_tasks[task_id] = message
            await self.broadcast(message, exclude=ws)
            return

        if message_type == "task.claim":
            await self.handle_task_claim(ws, message)
            return

        if message_type == "task.result":
            task_id = message["task_id"]
            self.state.pending_tasks.pop(task_id, None)
            self.state.claimed_tasks.pop(task_id, None)
            await self.broadcast(message)
            return

        if message_type in {"image.frame", "robot.state", "leader.state", "status.report"}:
            self.remember_latest(message)
            await self.broadcast(message, exclude=ws)
            return

        if message_type == "state.patch":
            await self.handle_state_patch(ws, message)
            return

        if message_type in {"motor.command", "stop"}:
            await self.broadcast(message, exclude=ws)
            return

        await ws.send(
            json.dumps(
                envelope(
                    "error",
                    error={"code": "unknown_type", "message": f"unknown message type: {message_type}"},
                )
            )
        )

    async def handle_task_claim(self, ws: Any, message: dict[str, Any]) -> None:
        task_id = message["task_id"]
        client_id = message["client_id"]
        if task_id in self.state.claimed_tasks:
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
        self.state.claimed_tasks[task_id] = client_id
        await self.broadcast(message)

    async def handle_state_patch(self, ws: Any, message: dict[str, Any]) -> None:
        try:
            resource = self.state.changes.apply(
                resource_id=message["resource_id"],
                base_revision=message.get("base_revision"),
                operations=message.get("operations", []),
                package_id=message["package_id"],
                change_id=message["change_id"],
            )
        except ChangeConflict as conflict:
            await ws.send(
                json.dumps(
                    envelope(
                        "state.conflict",
                        change_id=message.get("change_id"),
                        package_id=message.get("package_id"),
                        resource_id=conflict.resource_id,
                        expected_revision=conflict.expected,
                        actual_revision=conflict.actual,
                        current_state=self.state.changes.get(conflict.resource_id).state,
                    )
                )
            )
            return
        except Exception as exc:
            await ws.send(
                json.dumps(
                    envelope(
                        "error",
                        id=message.get("change_id"),
                        error={"code": "invalid_patch", "message": str(exc)},
                    )
                )
            )
            return

        accepted = envelope(
            "state.accepted",
            change_id=message["change_id"],
            package_id=message["package_id"],
            resource_id=message["resource_id"],
            revision=resource.revision,
            state=resource.state,
            operations=message.get("operations", []),
        )
        self.remember_latest(accepted)
        await self.broadcast(accepted)

    def remember_latest(self, message: dict[str, Any]) -> None:
        message_type = message["type"]
        if message_type == "image.frame":
            key = f"image.frame:{message.get('camera_id', 'unknown')}"
        elif message_type == "robot.state":
            key = f"robot.state:{message.get('robot_id', 'unknown')}"
        elif message_type == "leader.state":
            key = f"leader.state:{message.get('leader_id', 'unknown')}"
        elif message_type == "status.report":
            key = f"status.report:{message.get('component_id', 'unknown')}"
        elif message_type == "state.accepted":
            key = f"state.accepted:{message.get('resource_id', 'unknown')}"
        else:
            key = message_type
        self.state.latest[key] = message

    def snapshot(self) -> dict[str, Any]:
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
                        "package_id": client.get("package_id"),
                    }
                    for client in self.state.clients.values()
                    if client
                ],
                "pending_tasks": list(self.state.pending_tasks),
                "claimed_tasks": self.state.claimed_tasks,
                "latest": list(self.state.latest.values()),
                "resources": self.state.changes.snapshot(),
            },
        )

    async def handler(self, ws: Any) -> None:
        self.state.clients[ws] = {}
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
                        "state_patches",
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
                await self.handle_message(ws, message)
        finally:
            self.state.clients.pop(ws, None)


async def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    coordinator = Coordinator()
    async with websockets.serve(coordinator.handler, host, port):
        print(f"robot-task-ws coordinator listening on ws://{host}:{port}", flush=True)
        await asyncio.Future()
