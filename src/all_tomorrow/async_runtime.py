"""Process-local asyncio entry point compatible with psycopg on Windows."""
import asyncio
import sys


def run_async(coro):
    if sys.platform == "win32":
        return asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
    return asyncio.run(coro)
