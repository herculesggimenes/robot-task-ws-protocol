#!/usr/bin/env python3
"""Direct local YAM joint control without Modal policy inference."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "can-bridge"))
sys.path.insert(0, str(ROOT / "scripts"))
STOP_FILE = ROOT / "HARD_STOP"
STOP_REQUESTED = False


def _request_stop(_signum=None, _frame=None) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True


signal.signal(signal.SIGINT, _request_stop)
signal.signal(signal.SIGTERM, _request_stop)


def _install_can_patch() -> None:
    from local_modal_robot_bridge import _install_can_patch as _patch

    _patch()


def _parse_vector(value: str, *, name: str) -> np.ndarray:
    parts = [part.strip() for part in value.replace(",", " ").split() if part.strip()]
    if len(parts) != 7:
        raise argparse.ArgumentTypeError(f"{name} needs exactly 7 numbers")
    return np.asarray([float(part) for part in parts], dtype=float)


def _safety_report(robot) -> dict:
    with robot._state_lock:
        joint_state = robot._joint_state
        if joint_state is None:
            return {"available": False}
        return {
            "available": True,
            "temp_mos": np.asarray(joint_state.temp_mos, dtype=float).tolist(),
            "temp_rotor": np.asarray(joint_state.temp_rotor, dtype=float).tolist(),
            "max_temp_mos": float(np.max(joint_state.temp_mos)),
            "max_temp_rotor": float(np.max(joint_state.temp_rotor)),
        }


def _safety_block_reason(report: dict, args: argparse.Namespace) -> dict | None:
    if not report.get("available", False):
        return {"execution_blocked": "joint_state_unavailable"}
    if report["max_temp_mos"] > args.max_temp_mos:
        return {"execution_blocked": "mos_temperature_too_high", "max_temp_mos": report["max_temp_mos"], "limit": args.max_temp_mos}
    if report["max_temp_rotor"] > args.max_temp_rotor:
        return {"execution_blocked": "rotor_temperature_too_high", "max_temp_rotor": report["max_temp_rotor"], "limit": args.max_temp_rotor}
    return None


def _build_target(current: np.ndarray, args: argparse.Namespace) -> np.ndarray:
    target = np.asarray(current, dtype=float).copy()
    if args.target is not None:
        target = args.target.copy()
    if args.delta is not None:
        target += args.delta
    if args.gripper is not None:
        target[6] = args.gripper
    target[6] = float(np.clip(target[6], args.min_gripper_command, args.max_gripper_command))
    return target


def _limit_target(current: np.ndarray, target: np.ndarray, args: argparse.Namespace) -> np.ndarray:
    limited = np.asarray(current, dtype=float).copy()
    limited += np.clip(np.asarray(target, dtype=float) - limited, -args.max_delta, args.max_delta)
    limited[6] = float(np.clip(limited[6], args.min_gripper_command, args.max_gripper_command))
    return limited


def run(args: argparse.Namespace) -> int:
    if STOP_FILE.exists() and not args.ignore_hard_stop:
        print(f"hard stop exists at {STOP_FILE}; run `yamctl clear-stop` first", file=sys.stderr)
        return 2

    _install_can_patch()

    from i2rt.robots.get_robot import get_yam_robot
    from i2rt.robots.utils import GripperType

    robot = get_yam_robot(
        channel=args.channel,
        gripper_type=GripperType.LINEAR_4310,
        zero_gravity_mode=False,
        clip_commands_to_joint_limits=False,
    )
    try:
        current = np.asarray(robot.get_joint_pos(), dtype=float)
        safety = _safety_report(robot)
        print(json.dumps({"current": current.tolist(), "safety": safety}), flush=True)
        block_reason = _safety_block_reason(safety, args)
        if block_reason is not None:
            print(json.dumps(block_reason), flush=True)
            return 1
        if args.read_only:
            print(
                json.dumps(
                    {
                        "direct_ok": True,
                        "channel": args.channel,
                        "note": "If you see DM motor errors or Bad file descriptor below, they often occur "
                        "during shutdown after a successful read; clear DM faults if motors report errors.",
                    }
                ),
                flush=True,
            )
            return 0

        requested = _build_target(current, args)
        target = _limit_target(current, requested, args)
        print(json.dumps({"requested": requested.tolist(), "target": target.tolist(), "delta": (target - current).tolist()}), flush=True)

        steps = max(1, args.steps)
        for index in range(1, steps + 1):
            if STOP_REQUESTED or STOP_FILE.exists():
                print(json.dumps({"stopped": True, "step": index}), flush=True)
                return 130
            safety = _safety_report(robot)
            block_reason = _safety_block_reason(safety, args)
            if block_reason is not None:
                print(json.dumps({"safety": safety}), flush=True)
                print(json.dumps(block_reason), flush=True)
                return 1
            command = current + (index / steps) * (target - current)
            robot.command_joint_pos(command)
            print(json.dumps({"step": index, "steps": steps, "commanded": command.tolist()}), flush=True)
            if args.duration > 0:
                time.sleep(args.duration / steps)
        return 0
    finally:
        try:
            robot.close()
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"direct_close_error": repr(exc)}), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Direct local YAM joint control without Modal.")
    parser.add_argument(
        "--channel",
        default=os.environ.get("YAM_DIRECT_CAN", "can0"),
        help='SocketCAN iface for this arm (macOS bridges: "can0" -> /tmp/can0.sock). Default can0 = left in typical bimanual wiring.',
    )
    parser.add_argument("--target", type=lambda v: _parse_vector(v, name="--target"))
    parser.add_argument("--delta", type=lambda v: _parse_vector(v, name="--delta"))
    parser.add_argument("--gripper", type=float, help="Set normalized joint 7/gripper command.")
    parser.add_argument("--duration", type=float, default=1.0)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--max-delta", type=float, default=0.20)
    parser.add_argument("--max-temp-mos", type=float, default=55.0)
    parser.add_argument("--max-temp-rotor", type=float, default=100.0)
    parser.add_argument("--min-gripper-command", type=float, default=0.01)
    parser.add_argument("--max-gripper-command", type=float, default=0.59)
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--ignore-hard-stop", action="store_true")
    args = parser.parse_args()
    if not args.read_only and args.target is None and args.delta is None and args.gripper is None:
        parser.error(
            "need --read-only, --target, --delta, or --gripper. "
            "Example: uv run yamctl direct --channel can0 --read-only"
        )
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
