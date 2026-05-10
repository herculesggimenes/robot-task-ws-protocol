#!/usr/bin/env python3
"""Bridge the legacy YAM JSON-RPC control WebSocket into robot-task-ws."""

from __future__ import annotations

import argparse
import asyncio
import json
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


async def legacy_rpc(
    ws: Any,
    lock: asyncio.Lock,
    method: str,
    params: dict[str, Any] | None = None,
) -> Any:
    request_id = f"{method}-{time.time_ns()}"
    async with lock:
        await ws.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        while True:
            response = json.loads(await ws.recv())
            if response.get("type") == "hello":
                continue
            if response.get("id") != request_id:
                continue
            if not response.get("ok"):
                raise RuntimeError(response.get("error", response))
            return response.get("result")


async def publish_status(protocol_ws: Any, component_id: str, control_url: str, status: str, details: dict[str, Any]) -> None:
    await protocol_ws.send(
        json.dumps(
            envelope(
                "status.report",
                component_id=component_id,
                role="executor",
                status=status,
                details={"control_url": control_url, **details},
            )
        )
    )


async def poll_legacy(protocol_ws: Any, legacy_ws: Any, legacy_lock: asyncio.Lock, args: argparse.Namespace) -> None:
    while True:
        try:
            status = await legacy_rpc(legacy_ws, legacy_lock, "get_status")
            await publish_status(protocol_ws, args.component_id, args.control, "ok", status)
            joint_pos = await legacy_rpc(legacy_ws, legacy_lock, "get_joint_pos")
            await protocol_ws.send(
                json.dumps(
                    envelope(
                        "robot.state",
                        robot_id=args.robot_id,
                        state_space=args.state_space,
                        joint_pos=joint_pos,
                    )
                )
            )
        except Exception as exc:
            await publish_status(
                protocol_ws,
                args.component_id,
                args.control,
                "error",
                {"error": str(exc)},
            )
        await asyncio.sleep(args.poll_seconds)


async def forward_commands(protocol_ws: Any, legacy_ws: Any, legacy_lock: asyncio.Lock, args: argparse.Namespace) -> None:
    async for raw in protocol_ws:
        message = json.loads(raw)
        if message.get("type") == "motor.command" and message.get("robot_id") == args.robot_id:
            joint_pos = message.get("joint_pos")
            if joint_pos is not None:
                await legacy_rpc(legacy_ws, legacy_lock, "command_joint_pos", {"joint_pos": joint_pos})
        elif message.get("type") == "stop":
            try:
                await legacy_rpc(legacy_ws, legacy_lock, "zero_torque_mode")
            except Exception:
                pass


async def main(args: argparse.Namespace) -> None:
    client_id = f"{args.component_id}-{uuid.uuid4().hex[:8]}"
    async with websockets.connect(args.coordinator, max_size=32 * 1024 * 1024) as protocol_ws:
        await protocol_ws.recv()
        await protocol_ws.send(
            json.dumps(
                envelope(
                    "client.register",
                    client_id=client_id,
                    role="executor",
                    capabilities=["robot.state", "status.report", "motor.command", "stop"],
                )
            )
        )
        async with websockets.connect(args.control, max_size=32 * 1024 * 1024) as legacy_ws:
            first = await legacy_ws.recv()
            try:
                await publish_status(
                    protocol_ws,
                    args.component_id,
                    args.control,
                    "ok",
                    {"legacy_hello": json.loads(first)},
                )
            except json.JSONDecodeError:
                pass
            legacy_lock = asyncio.Lock()
            await asyncio.gather(
                poll_legacy(protocol_ws, legacy_ws, legacy_lock, args),
                forward_commands(protocol_ws, legacy_ws, legacy_lock, args),
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coordinator", default="ws://127.0.0.1:8765")
    parser.add_argument("--control", default="ws://127.0.0.1:8780/control")
    parser.add_argument("--robot-id", default="yam-1")
    parser.add_argument("--component-id", default="yam-control-adapter")
    parser.add_argument("--state-space", default="yam_bimanual_14d")
    parser.add_argument("--poll-seconds", type=float, default=0.25)
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
