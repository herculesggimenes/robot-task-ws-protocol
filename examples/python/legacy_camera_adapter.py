#!/usr/bin/env python3
"""Bridge the legacy multi-camera WebSocket into robot-task-ws image.frame."""

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


def normalize_frame(frame: dict[str, Any]) -> dict[str, Any] | None:
    if frame.get("type") != "frame" or frame.get("encoding") != "base64":
        return None
    camera_id = str(frame.get("camera_id") or "camera")
    captured_at = float(frame.get("captured_at") or time.time())
    return envelope(
        "image.frame",
        frame_id=f"{camera_id}-{int(captured_at * 1_000_000)}",
        camera_id=camera_id,
        content_type=frame.get("content_type", "image/jpeg"),
        encoding="base64",
        captured_at=captured_at,
        sent_at=frame.get("sent_at"),
        source=frame.get("source") or frame.get("camera_index"),
        data=frame["data"],
        depth=frame.get("depth"),
        intrinsics=frame.get("intrinsics"),
        orientation=frame.get("orientation"),
    )


async def main(args: argparse.Namespace) -> None:
    client_id = f"camera-adapter-{uuid.uuid4().hex[:8]}"
    async with websockets.connect(args.coordinator, max_size=64 * 1024 * 1024) as protocol_ws:
        await protocol_ws.recv()
        await protocol_ws.send(
            json.dumps(
                envelope(
                    "client.register",
                    client_id=client_id,
                    role="camera",
                    capabilities=["image.frame", "status.report"],
                )
            )
        )
        async with websockets.connect(args.camera, max_size=64 * 1024 * 1024) as camera_ws:
            hello = json.loads(await camera_ws.recv())
            await protocol_ws.send(
                json.dumps(
                    envelope(
                        "status.report",
                        component_id="legacy-camera-adapter",
                        role="camera",
                        status="ok",
                        details={"camera_url": args.camera, "legacy_hello": hello},
                    )
                )
            )
            await camera_ws.send(
                json.dumps(
                    {
                        "type": "subscribe",
                        "fps": args.fps,
                        "cameras": args.cameras,
                        "bundle": True,
                    }
                )
            )
            async for raw in camera_ws:
                payload = json.loads(raw)
                frames = payload.get("frames", []) if payload.get("type") == "frames" else [payload]
                for frame in frames:
                    normalized = normalize_frame(frame)
                    if normalized is not None:
                        await protocol_ws.send(json.dumps(normalized))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coordinator", default="ws://127.0.0.1:8765")
    parser.add_argument("--camera", default="ws://127.0.0.1:8770/cameras")
    parser.add_argument("--fps", type=float, default=5.0)
    parser.add_argument("--cameras", default="all")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
