# Migrating the Hackathon Stack

This document maps the current YAM hackathon WebSockets into the open
`robot-task-ws` protocol.

The working YAM files have also been copied into `migrated/can-mac/` in their
original relative layout so the open repo contains the current hardware path
while native protocol replacements are introduced.

## Current Services

### YAM Control Socket

The existing control socket is JSON-RPC-style:

```text
ws://127.0.0.1:8780/control
```

Known methods:

- `get_joint_pos`
- `command_joint_pos`
- `get_observations`
- `get_robot_info`
- `get_status`
- `reconnect`
- `num_dofs`
- `zero_torque_mode`
- `close`

The compatibility adapter polls `get_status` and `get_joint_pos`, publishes
protocol-native `status.report` and `robot.state`, and forwards
`motor.command` messages back to `command_joint_pos`.

The current YAM control server owns the bimanual bridge process and can start
separate CAN bridge sockets for each arm. The default physical mapping is:

```text
left:can0,right:can1
```

Override only when the two USB/CAN ports are physically swapped:

```bash
uv run yamctl control-server \
  --arm-specs left:can1,right:can0 \
  --host 0.0.0.0
```

```bash
python examples/python/legacy_yam_control_adapter.py \
  --coordinator ws://127.0.0.1:8765 \
  --control ws://127.0.0.1:8780/control
```

### Multi-Camera Socket

The existing camera socket is command-style:

```text
ws://127.0.0.1:8770/cameras
```

Known commands:

- `get_frame`
- `get_all_frames`
- `reset_camera`
- `subscribe`
- `stop`

The compatibility adapter subscribes to legacy frames and republishes each
frame as `image.frame`.

Current YAM lab command for the four-feed setup:

```bash
sudo /opt/homebrew/bin/uv run python migrated/can-mac/scripts/multi_camera_ws_server.py \
  --host 0.0.0.0 \
  --port 8770 \
  --camera-specs 'right:1,left:2,top:orbbec:color,depth:orbbec:depth' \
  --quality 80
```

The `right` and `left` feeds are OpenCV/AVFoundation cameras. The `top` and
`depth` feeds are logical Orbbec SDK feeds from one physical camera. Use
`reset_camera` to recover stuck feeds; OpenCV feeds reset independently and
Orbbec logical feeds restart the shared Orbbec SDK worker.

```bash
python examples/python/legacy_camera_adapter.py \
  --coordinator ws://127.0.0.1:8765 \
  --camera ws://127.0.0.1:8770/cameras \
  --fps 5
```

### SO Leader Bridge

The SO-100/SO-101 bridge publishes `leader.state`. With `--execute`, it also
emits bounded `motor.command` messages to the coordinator. An executor can then
validate and apply those commands.

```bash
python examples/python/so_leader_protocol_bridge.py \
  --coordinator ws://127.0.0.1:8765 \
  --port /dev/cu.usbmodem5B140318401 \
  --kind so100 \
  --arm right \
  --execute
```

Use `--lerobot-src` if the LeRobot checkout is not adjacent to the old
hackathon tree.

## Status Viewer

Run:

```bash
python examples/python/viewer_server.py
```

Open <http://127.0.0.1:8080>.

The viewer can connect to:

- the protocol coordinator
- the legacy YAM control WebSocket
- the legacy camera WebSocket

That lets contributors see both the migrated protocol stream and the old
services while the migration is in progress.
