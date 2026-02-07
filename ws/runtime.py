"""
Tmux Runtime Module.

Provides safe async execution of blocking tmux operations using a thread pool.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, TypeVar

T = TypeVar("T")


@dataclass
class TmuxRuntime:
    """tmux操作の専用スレッドプール + 直列化ロック"""

    max_workers: int = 2
    executor: ThreadPoolExecutor = field(init=False)
    lock: asyncio.Lock = field(init=False)

    def __post_init__(self) -> None:
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        self.lock = asyncio.Lock()

    async def run_locked(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """tmux操作（ブロッキング）をLock付きでスレッドプールで実行"""
        async with self.lock:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                self.executor, lambda: fn(*args, **kwargs)
            )

    async def run_unlocked(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """ファイルI/O等、Lock不要な操作をスレッドプールで実行"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, lambda: fn(*args, **kwargs))

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False)
