"""Entrypoint: ``python -m app.simulation``."""

import asyncio

from app.simulation.runner import main

if __name__ == "__main__":
    asyncio.run(main())
