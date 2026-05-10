#!/usr/bin/env python3
"""Run the reference Robot Task WebSocket coordinator."""

from __future__ import annotations

import asyncio

from robot_task_ws.coordinator import serve


async def main() -> None:
    await serve("127.0.0.1", 8765)


if __name__ == "__main__":
    asyncio.run(main())
