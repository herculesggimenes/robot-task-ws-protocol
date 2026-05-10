#!/usr/bin/env python3
"""Publish SO-100/SO-101 leader arm state to robot-task-ws.

This is the protocol-native version of the hackathon SO leader bridge. It does
not require direct access to the YAM JSON-RPC socket. With --execute it emits
bounded motor.command messages to the coordinator, where an executor can
validate and forward them to hardware.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import types
import uuid
from pathlib import Path
from typing import Any

import websockets

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover - dependency hint for operators
    raise SystemExit("Install numpy or run `python -m pip install -e '.[yam]'`.") from exc

PROTOCOL = "robot-task-ws"
VERSION = "0.1.0"
ARM_SLICES = {"left": slice(0, 7), "right": slice(7, 14)}
SO_MOTORS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]


def envelope(message_type: str, **fields: Any) -> dict[str, Any]:
    return {
        "type": message_type,
        "protocol": PROTOCOL,
        "version": VERSION,
        "timestamp": time.time(),
        **fields,
    }


def install_torch_stub() -> None:
    if "torch" in sys.modules:
        return

    class Device:
        def __init__(self, device_type: str = "cpu"):
            self.type = device_type

        def __str__(self) -> str:
            return self.type

    class Cuda:
        @staticmethod
        def is_available() -> bool:
            return False

    class Backends:
        class mps:
            @staticmethod
            def is_available() -> bool:
                return False

    sys.modules["torch"] = types.SimpleNamespace(
        Tensor=object,
        device=Device,
        dtype=object,
        float64="float64",
        float32="float32",
        cuda=Cuda,
        backends=Backends,
    )


class SOLeader:
    def __init__(self, port: str, kind: str, lerobot_src: Path):
        install_torch_stub()
        sys.path.insert(0, str(lerobot_src))
        if kind == "so100":
            from lerobot.teleoperators.so100_leader import SO100Leader, SO100LeaderConfig

            self.teleop = SO100Leader(SO100LeaderConfig(port=port, id="robot_task_ws_so100"))
        elif kind == "so101":
            from lerobot.teleoperators.so101_leader import SO101Leader, SO101LeaderConfig

            self.teleop = SO101Leader(SO101LeaderConfig(port=port, id="robot_task_ws_so101"))
        else:
            raise ValueError(f"unsupported leader kind: {kind}")
        self.teleop.connect(calibrate=False)

    def close(self) -> None:
        self.teleop.disconnect()

    def read_raw(self) -> np.ndarray:
        values = self.teleop.bus.sync_read("Present_Position", normalize=False)
        return np.asarray([float(values[motor]) for motor in SO_MOTORS], dtype=float)


def parse_ints(raw: str, expected: int, name: str) -> list[int]:
    values = [int(part.strip()) for part in raw.split(",") if part.strip()]
    if len(values) != expected:
        raise ValueError(f"{name} expects {expected} comma-separated integers")
    return values


def parse_floats(raw: str, expected: int, name: str) -> np.ndarray:
    values = [float(part.strip()) for part in raw.split(",") if part.strip()]
    if len(values) != expected:
        raise ValueError(f"{name} expects {expected} comma-separated numbers")
    return np.asarray(values, dtype=float)


def arm_target(
    raw: np.ndarray,
    leader_base: np.ndarray,
    arm_base: np.ndarray,
    args: argparse.Namespace,
) -> np.ndarray:
    joint_map = parse_ints(args.joint_map, 5, "--joint-map")
    signs = parse_floats(args.joint_signs, 5, "--joint-signs")
    target = arm_base.copy()
    delta_raw = raw[:5] - leader_base[:5]
    for src_index, yam_index in enumerate(joint_map):
        delta = float(
            np.clip(
                delta_raw[src_index] * args.raw_to_rad * signs[src_index],
                -args.max_joint_delta,
                args.max_joint_delta,
            )
        )
        target[yam_index] = arm_base[yam_index] + delta
    gripper_norm = float(np.clip((raw[5] - 400.0) / 3200.0, 0.0, 1.0))
    target[6] = args.min_gripper + gripper_norm * (args.max_gripper - args.min_gripper)
    return target


async def main(args: argparse.Namespace) -> None:
    client_id = f"leader-{uuid.uuid4().hex[:8]}"
    lerobot_src = Path(args.lerobot_src).expanduser()
    leader = SOLeader(args.port, args.kind, lerobot_src)
    arm_names = ["left", "right"] if args.arm == "both" else [args.arm]
    q14_base = np.asarray(args.robot_base, dtype=float)
    arm_bases = {name: q14_base[ARM_SLICES[name]].copy() for name in arm_names}
    samples = [leader.read_raw()]
    for _ in range(max(args.sync_samples, 1) - 1):
        await asyncio.sleep(0.02)
        samples.append(leader.read_raw())
    leader_base = np.mean(np.stack(samples, axis=0), axis=0)
    command_arms = {name: arm_bases[name].copy() for name in arm_names}

    try:
        async with websockets.connect(args.coordinator, max_size=32 * 1024 * 1024) as ws:
            await ws.recv()
            await ws.send(
                json.dumps(
                    envelope(
                        "client.register",
                        client_id=client_id,
                        role="leader",
                        capabilities=["leader.state", "motor.command"],
                    )
                )
            )
            dt = 1.0 / max(args.hz, 1.0)
            while True:
                started = time.monotonic()
                raw = leader.read_raw()
                q14 = q14_base.copy()
                for arm_name in arm_names:
                    target = arm_target(raw, leader_base, arm_bases[arm_name], args)
                    step_limits = np.full(7, args.max_step, dtype=float)
                    step_limits[6] = args.max_gripper_step
                    command_arms[arm_name] = command_arms[arm_name] + np.clip(
                        target - command_arms[arm_name],
                        -step_limits,
                        step_limits,
                    )
                    q14[ARM_SLICES[arm_name]] = command_arms[arm_name]

                await ws.send(
                    json.dumps(
                        envelope(
                            "leader.state",
                            leader_id=args.leader_id,
                            kind=args.kind,
                            target_robot_id=args.robot_id,
                            target_arm=args.arm,
                            raw=raw.tolist(),
                            synchronized=True,
                            executing=args.execute,
                            hz=args.hz,
                            joint_pos=q14.tolist(),
                        )
                    )
                )
                if args.execute:
                    await ws.send(
                        json.dumps(
                            envelope(
                                "motor.command",
                                id=f"leader-cmd-{time.time_ns()}",
                                robot_id=args.robot_id,
                                command_space=args.command_space,
                                joint_pos=q14.tolist(),
                                limits={
                                    "max_joint_delta": args.max_step,
                                    "max_gripper_delta": args.max_gripper_step,
                                    "timeout_ms": int(dt * 3000),
                                },
                            )
                        )
                    )
                elapsed = time.monotonic() - started
                if elapsed < dt:
                    await asyncio.sleep(dt - elapsed)
    finally:
        leader.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coordinator", default="ws://127.0.0.1:8765")
    parser.add_argument("--port", default="/dev/cu.usbmodem5B140318401")
    parser.add_argument("--kind", choices=["so100", "so101"], default="so100")
    parser.add_argument("--lerobot-src", default="../hackathon/lerobot-MakerMods/src")
    parser.add_argument("--leader-id", default="so-leader")
    parser.add_argument("--robot-id", default="yam-1")
    parser.add_argument("--arm", choices=["left", "right", "both"], default="right")
    parser.add_argument("--hz", type=float, default=30.0)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--command-space", default="yam_bimanual_14d_absolute")
    parser.add_argument("--raw-to-rad", type=float, default=0.0012)
    parser.add_argument("--joint-map", default="0,1,2,3,4")
    parser.add_argument("--joint-signs", default="1,1,1,1,1")
    parser.add_argument("--max-joint-delta", type=float, default=0.45)
    parser.add_argument("--max-step", type=float, default=0.025)
    parser.add_argument("--max-gripper-step", type=float, default=0.015)
    parser.add_argument("--min-gripper", type=float, default=0.01)
    parser.add_argument("--max-gripper", type=float, default=0.59)
    parser.add_argument("--sync-samples", type=int, default=5)
    parser.add_argument(
        "--robot-base",
        type=json.loads,
        default="[0,0,0,0,0,0,0.3,0,0,0,0,0,0,0.3]",
        help="JSON array used as the initial 14D robot pose baseline.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
