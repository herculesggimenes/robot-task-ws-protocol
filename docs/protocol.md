# Protocol Draft v0.1

## Transport

The protocol runs over WebSocket. JSON text frames are required. Binary frames
are reserved for future high-throughput image and tensor payloads.

A server may expose multiple endpoints, but the default endpoint is:

```text
/ws
```

## Message Envelope

Every JSON message uses this envelope:

```json
{
  "type": "task.request",
  "protocol": "robot-task-ws",
  "version": "0.1.0",
  "id": "task-001",
  "timestamp": 1778448000.0
}
```

## Message Types

### `hello`

Sent by the server immediately after connection.

```json
{
  "type": "hello",
  "protocol": "robot-task-ws",
  "version": "0.1.0",
  "server_id": "lab-coordinator-1",
  "capabilities": ["task_queue", "image_frames", "motor_commands"]
}
```

### `client.register`

Sent by clients to describe their role.

```json
{
  "type": "client.register",
  "protocol": "robot-task-ws",
  "version": "0.1.0",
  "client_id": "planner-a",
  "role": "planner",
  "capabilities": ["task.plan", "task.result"]
}
```

Common roles:

- `camera`
- `planner`
- `perception`
- `executor`
- `operator`
- `safety`
- `monitor`
- `leader`

### `image.frame`

Publishes a camera frame. The draft uses base64 JPEG for compatibility.
Future versions may add binary side-channel frame transfer.

```json
{
  "type": "image.frame",
  "protocol": "robot-task-ws",
  "version": "0.1.0",
  "frame_id": "front-1778448000",
  "camera_id": "front",
  "content_type": "image/jpeg",
  "encoding": "base64",
  "captured_at": 1778448000.0,
  "data": "/9j/4AAQSkZJRgABAQAAAQABAAD..."
}
```

Depth-capable feeds may include raw metric depth beside the JPEG preview:

```json
{
  "type": "image.frame",
  "protocol": "robot-task-ws",
  "version": "0.1.0",
  "frame_id": "depth-1778448000",
  "camera_id": "depth",
  "content_type": "image/jpeg",
  "encoding": "base64",
  "captured_at": 1778448000.0,
  "data": "/9j/4AAQSkZJRgABAQAAAQABAAD...",
  "depth": {
    "content_type": "application/octet-stream",
    "encoding": "base64",
    "format": "uint16",
    "byte_order": "little",
    "unit": "meter",
    "scale_to_meters": 0.001,
    "width": 640,
    "height": 400,
    "data": "<base64 little-endian uint16>"
  }
}
```

### `robot.state`

Publishes the current robot state.

```json
{
  "type": "robot.state",
  "protocol": "robot-task-ws",
  "version": "0.1.0",
  "robot_id": "yam-1",
  "joint_pos": [0, 0, 0, 0, 0, 0, 0.3, 0, 0, 0, 0, 0, 0, 0.3],
  "state_space": "yam_bimanual_14d"
}
```

### `leader.state`

Publishes the live state of a leader arm or other teleoperation input device.
This is separate from `robot.state` because leader devices may have different
kinematics, joint counts, calibration state, buttons, or sync mode.

```json
{
  "type": "leader.state",
  "protocol": "robot-task-ws",
  "version": "0.1.0",
  "leader_id": "so100-right",
  "kind": "so100",
  "target_robot_id": "yam-1",
  "target_arm": "right",
  "raw": [2048, 2100, 1980, 1800, 2200, 1200],
  "buttons": [0, 1],
  "synchronized": true,
  "executing": true,
  "hz": 30.0
}
```

### `status.report`

Publishes component health for dashboards and monitors.

```json
{
  "type": "status.report",
  "protocol": "robot-task-ws",
  "version": "0.1.0",
  "component_id": "yam-control-adapter",
  "role": "executor",
  "status": "ok",
  "details": {
    "control_url": "ws://127.0.0.1:8780/control",
    "arms": {
      "left": {"connected": true},
      "right": {"connected": true}
    }
  }
}
```

### `task.request`

Creates a task to be handled by any compatible worker.

```json
{
  "type": "task.request",
  "protocol": "robot-task-ws",
  "version": "0.1.0",
  "id": "task-001",
  "task": {
    "kind": "perception.locate_pixel",
    "prompt": "Find the cup and the right gripper.",
    "inputs": {
      "frame_ids": ["front-1778448000"]
    },
    "constraints": {
      "timeout_ms": 3000
    }
  }
}
```

### `task.claim`

Claims a task for a worker.

```json
{
  "type": "task.claim",
  "protocol": "robot-task-ws",
  "version": "0.1.0",
  "task_id": "task-001",
  "client_id": "perception-worker-a"
}
```

### `task.result`

Returns a task result.

```json
{
  "type": "task.result",
  "protocol": "robot-task-ws",
  "version": "0.1.0",
  "task_id": "task-001",
  "client_id": "perception-worker-a",
  "ok": true,
  "result": {
    "target_u": 328,
    "target_v": 214,
    "gripper_u": 402,
    "gripper_v": 241,
    "confidence": 0.82
  }
}
```

### `motor.command`

Requests robot motion. Motor commands should be accepted only by authenticated
executor clients in real deployments.

```json
{
  "type": "motor.command",
  "protocol": "robot-task-ws",
  "version": "0.1.0",
  "id": "cmd-001",
  "robot_id": "yam-1",
  "command_space": "yam_bimanual_14d_absolute",
  "joint_pos": [0, 0, 0, 0, 0, 0, 0.3, 0, 0, 0, 0, 0, 0, 0.3],
  "limits": {
    "max_joint_delta": 0.05,
    "max_gripper_delta": 0.02
  }
}
```

### `stop`

Requests immediate stop. Any safety-aware client may emit it.

```json
{
  "type": "stop",
  "protocol": "robot-task-ws",
  "version": "0.1.0",
  "reason": "operator_requested"
}
```

### `state.patch`

Packages use `state.patch` to send simultaneous changes to shared resources.
The coordinator serializes patches per `resource_id`, assigns revisions, and
broadcasts `state.accepted` or returns `state.conflict`.

See [concurrency.md](concurrency.md) for the full flow.

### Legacy YAM Compatibility

The existing hackathon YAM control socket uses JSON-RPC-style messages:

```json
{
  "id": "cmd-1",
  "method": "command_joint_pos",
  "params": {
    "joint_pos": [0, 0, 0, 0, 0, 0, 0.3, 0, 0, 0, 0, 0, 0, 0.3]
  }
}
```

During migration, adapters translate that endpoint to protocol-native
`robot.state`, `status.report`, and `motor.command` messages. New components
should prefer the protocol-native message types.

### `error`

Reports an error.

```json
{
  "type": "error",
  "protocol": "robot-task-ws",
  "version": "0.1.0",
  "id": "task-001",
  "error": {
    "code": "invalid_payload",
    "message": "missing task.kind"
  }
}
```

## Safety Notes

The protocol separates task distribution from physical execution, but the wire
format can still carry motor commands. Production deployments should add:

- authentication
- authorization by role
- command bounds checking
- rate limits
- deadman / heartbeat behavior
- physical emergency stop outside this protocol
