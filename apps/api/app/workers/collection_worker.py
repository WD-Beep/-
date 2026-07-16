"""Standalone collection worker process entrypoint."""

from __future__ import annotations

import asyncio
import logging
import sys

from app.workers.collection_worker_pool import run_standalone_worker_pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


def main() -> int:
    try:
        asyncio.run(run_standalone_worker_pool())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
