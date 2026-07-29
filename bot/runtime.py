"""Thread-safe bridge from Flask requests to the Discord event loop."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from concurrent.futures import Future
from typing import Any

_bot: Any = None
_loop: asyncio.AbstractEventLoop | None = None


class BotUnavailable(RuntimeError):
    pass


def register(bot: Any) -> None:
    global _bot, _loop
    _bot = bot
    _loop = asyncio.get_running_loop()


def unregister() -> None:
    global _bot, _loop
    _bot = None
    _loop = None


def is_ready() -> bool:
    return bool(_bot and _loop and _loop.is_running() and _bot.is_ready())


def _submit(coro: Coroutine[Any, Any, Any], timeout: float = 15) -> Any:
    if not _loop or not _loop.is_running():
        coro.close()
        raise BotUnavailable("Der Discord-Bot ist momentan nicht erreichbar.")
    future: Future[Any] = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result(timeout=timeout)


def call(method: str, *args: Any, timeout: float = 15, **kwargs: Any) -> Any:
    if _bot is None:
        raise BotUnavailable("Der Discord-Bot ist momentan nicht erreichbar.")
    handler = getattr(_bot, method, None)
    if handler is None:
        raise BotUnavailable(f"Bot-Funktion {method} ist nicht geladen.")
    return _submit(handler(*args, **kwargs), timeout)
