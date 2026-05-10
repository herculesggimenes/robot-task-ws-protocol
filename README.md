# Robot Task WebSocket Protocol

An open WebSocket protocol for distributing robot tasks across cooperating
clients and services.

The protocol is designed for hackathon-style and research deployments where
multiple people need to connect independent components to the same system:

- camera/image producers
- task planners
- perception workers
- motor-control executors
- operator dashboards
- safety monitors

The first reference use case is YAM bimanual control, but the wire format is
robot-agnostic.

## Status

Draft v0.1. The repo is intentionally small and schema-first so contributors can
discuss and evolve the protocol without importing a full robot codebase.

## Protocol Shape

All application messages are JSON objects over WebSocket.

Every message has:

- `type`: message kind
- `protocol`: protocol name, currently `robot-task-ws`
- `version`: semantic protocol version

The core flow is:

1. A client connects and receives `hello`.
2. Producers publish image frames or robot state.
3. A coordinator publishes task requests.
4. Workers claim tasks and submit task results.
5. Executors apply validated motor commands.
6. Safety clients can issue `stop` at any time.

See [docs/protocol.md](docs/protocol.md) for the full draft.

## Quick Start

Install the example dependencies:

```bash
python -m pip install -e ".[dev]"
```

Run the reference coordinator:

```bash
python examples/python/coordinator.py
```

In another shell, run a worker:

```bash
python examples/python/worker.py ws://127.0.0.1:8765
```

Publish a demo task:

```bash
python examples/python/submit_task.py ws://127.0.0.1:8765
```

## Repository Layout

- `docs/protocol.md`: human-readable protocol draft
- `schemas/`: JSON Schema definitions for wire messages
- `examples/python/`: minimal reference implementation

## Contributing

This repo is meant to be shared across contributors. Please keep changes
schema-backed and include at least one example payload when adding a message
type.

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
