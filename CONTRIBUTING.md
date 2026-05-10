# Contributing

Thanks for helping make the protocol usable across robots, cameras, policies,
and operator tools.

## Principles

- Keep the wire protocol small and explicit.
- Prefer additive changes over breaking changes.
- Include JSON Schema updates for message changes.
- Include example payloads for new fields or message types.
- Treat motor-control messages as safety-critical API surface.

## Development

Install development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Validate schemas:

```bash
python -m json.tool schemas/message.schema.json >/dev/null
python -m json.tool schemas/task.schema.json >/dev/null
python -m json.tool schemas/motor-command.schema.json >/dev/null
```

Run the examples:

```bash
python examples/python/coordinator.py
python examples/python/worker.py ws://127.0.0.1:8765
python examples/python/submit_task.py ws://127.0.0.1:8765
```

## Versioning

Protocol versions use semantic versioning. Before v1.0, breaking changes are
allowed but should be called out in the pull request.
