# Concurrent Package Changes

Different packages can publish changes at the same time by sending
`state.patch` messages to the coordinator. The coordinator is the serialization
point: it accepts one patch at a time for each resource, assigns the next
revision, then broadcasts `state.accepted`.

This prevents packages from racing on shared state such as:

- active task graph
- robot command plan
- camera selection
- leader-arm routing
- dashboard configuration
- safety mode

## Message Contract

Every package registers with a stable `package_id`:

```json
{
  "type": "client.register",
  "protocol": "robot-task-ws",
  "version": "0.1.0",
  "client_id": "planner-process-1",
  "package_id": "planner",
  "role": "planner",
  "capabilities": ["state.patch", "task.request"]
}
```

Then it sends a patch:

```json
{
  "type": "state.patch",
  "protocol": "robot-task-ws",
  "version": "0.1.0",
  "change_id": "planner-0001",
  "package_id": "planner",
  "resource_id": "task-plan/current",
  "base_revision": 0,
  "operations": [
    {
      "op": "add",
      "path": "/steps",
      "value": ["locate cup", "move gripper"]
    }
  ]
}
```

If the resource is still at `base_revision`, the coordinator broadcasts:

```json
{
  "type": "state.accepted",
  "protocol": "robot-task-ws",
  "version": "0.1.0",
  "change_id": "planner-0001",
  "package_id": "planner",
  "resource_id": "task-plan/current",
  "revision": 1,
  "state": {
    "steps": ["locate cup", "move gripper"]
  }
}
```

If another package already changed the same resource, the coordinator returns
`state.conflict` to the sender:

```json
{
  "type": "state.conflict",
  "protocol": "robot-task-ws",
  "version": "0.1.0",
  "change_id": "planner-0002",
  "package_id": "planner",
  "resource_id": "task-plan/current",
  "expected_revision": 1,
  "actual_revision": 2,
  "current_state": {
    "steps": ["locate cup", "move gripper", "open gripper"]
  }
}
```

The sender should recompute against `current_state` and retry with
`base_revision` set to `actual_revision`.

## Rules

- `resource_id` names the shared thing being changed.
- `base_revision` is a compare-and-swap guard. Use it when a package depends on
  the current state.
- Omit `base_revision` only for telemetry-style updates where last-write-wins is
  acceptable.
- `change_id` must be unique per package.
- `package_id` identifies the package that authored the change, not the process.
- The coordinator assigns resource revisions; clients do not.
- Consumers should apply `state.accepted` messages in revision order per
  `resource_id`.

## When To Use Domain Messages Instead

Use domain messages for high-rate data:

- `image.frame` for camera frames
- `robot.state` for robot telemetry
- `leader.state` for leader telemetry
- `motor.command` for commands that executors validate immediately

Use `state.patch` for shared durable state that multiple packages may edit.
