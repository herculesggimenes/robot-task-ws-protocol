# Migrated Hackathon Code

This directory preserves the working `can-mac` tree from the hackathon repo in
the same relative layout used by the scripts.

Included:

- `scripts/`: YAM control, camera, leader bridge, execution-loop, and probe scripts
- `schemas/`: YAM executor and pixel-locator schemas
- `web/`: legacy camera viewer
- `can-bridge/`: CAN bridge source without Rust build artifacts
- `_yamtest/`: local YAM test helpers

Excluded:

- runtime logs
- Python virtual environments
- `__pycache__`
- Rust `target/` build artifacts

Protocol-native adapters live in `examples/python/`. New contributors should
use those adapters and the docs in `docs/` when building new packages, while
this migrated tree keeps the current hardware path available.
