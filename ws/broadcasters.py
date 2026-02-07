"""WebSocket broadcaster components for real-time tmux monitoring."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from fastapi import WebSocket

from .runtime import TmuxRuntime
from .state import PaneState
from .tmux_bridge import TmuxBridge

logger = logging.getLogger(__name__)


@dataclass
class AdaptivePoller:
    """Adaptive polling interval: extends on no-change, shrinks on change."""

    base_interval: float  # seconds
    max_interval: float  # seconds
    no_change_threshold: int
    current_interval: float = field(init=False)
    no_change_count: int = field(default=0)

    def __post_init__(self) -> None:
        self.current_interval = self.base_interval

    def on_change(self) -> None:
        """Reset interval to base when change is detected."""
        self.no_change_count = 0
        self.current_interval = self.base_interval

    def on_no_change(self) -> None:
        """Increase interval when no change is detected."""
        self.no_change_count += 1
        if self.no_change_count >= self.no_change_threshold:
            self.current_interval = min(
                self.max_interval, self.current_interval * 2
            )


@dataclass
class MonitorBroadcaster:
    """Broadcaster for all multiagent panes with differential updates."""

    tmux: TmuxBridge
    runtime: TmuxRuntime
    poller: AdaptivePoller
    subscribers: set[WebSocket] = field(default_factory=set)
    pane_state: PaneState = field(default_factory=lambda: PaneState())
    _last_full_data: dict[str, str] = field(default_factory=dict)
    task: asyncio.Task[None] | None = None
    running: bool = False

    async def start(self) -> None:
        """Start the broadcaster loop."""
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._loop())
        logger.info("MonitorBroadcaster started")

    async def stop(self) -> None:
        """Stop the broadcaster loop."""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("MonitorBroadcaster stopped")

    async def subscribe(self, ws: WebSocket) -> None:
        """Subscribe a websocket to receive updates."""
        self.subscribers.add(ws)
        # Send initial full data to new subscriber
        if self._last_full_data:
            try:
                payload = {"ts": time.time(), "updates": self._last_full_data}
                await ws.send_json(payload)
            except Exception:
                logger.error("Failed to send initial data to new subscriber")
        logger.info("MonitorBroadcaster: subscriber added (total: %d)", len(self.subscribers))

    async def unsubscribe(self, ws: WebSocket) -> None:
        """Unsubscribe a websocket."""
        self.subscribers.discard(ws)
        logger.info("MonitorBroadcaster: subscriber removed (total: %d)", len(self.subscribers))

    async def _loop(self) -> None:
        """Main broadcast loop."""
        while self.running:
            try:
                # Capture all panes (locked to serialize tmux access)
                panes_data = await self.runtime.run_locked(
                    self.tmux.capture_all_panes
                )

                # Convert list[dict] to dict[str, str]
                panes = {
                    item["agent_id"]: item["output"] for item in panes_data
                }

                # Keep full data for new subscribers
                self._last_full_data = panes

                # Compute diff
                updates = self.pane_state.diff(panes)

                # Adjust polling interval
                if updates:
                    self.poller.on_change()
                else:
                    self.poller.on_no_change()

                # Broadcast updates (only if non-empty)
                if updates:
                    payload = {"ts": time.time(), "updates": updates}
                    dead_sockets = []
                    for ws in self.subscribers:
                        try:
                            await ws.send_json(payload)
                        except Exception:
                            dead_sockets.append(ws)
                    # Remove failed websockets
                    for ws in dead_sockets:
                        self.subscribers.discard(ws)

                await asyncio.sleep(self.poller.current_interval)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.error("MonitorBroadcaster loop error", exc_info=True)
                await asyncio.sleep(self.poller.base_interval)


@dataclass
class ShogunBroadcaster:
    """Broadcaster for shogun pane output."""

    tmux: TmuxBridge
    runtime: TmuxRuntime
    poller: AdaptivePoller
    subscribers: set[WebSocket] = field(default_factory=set)
    _last_output: str = ""
    _last_hash: str | None = None
    task: asyncio.Task[None] | None = None
    running: bool = False

    async def start(self) -> None:
        """Start the broadcaster loop."""
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._loop())
        logger.info("ShogunBroadcaster started")

    async def stop(self) -> None:
        """Stop the broadcaster loop."""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("ShogunBroadcaster stopped")

    async def subscribe(self, ws: WebSocket) -> None:
        """Subscribe a websocket to receive updates."""
        self.subscribers.add(ws)
        # Send current output to new subscriber
        if self._last_output:
            try:
                payload = {"ts": time.time(), "output": self._last_output}
                await ws.send_json(payload)
            except Exception:
                logger.error("Failed to send initial output to new subscriber")
        logger.info("ShogunBroadcaster: subscriber added (total: %d)", len(self.subscribers))

    async def unsubscribe(self, ws: WebSocket) -> None:
        """Unsubscribe a websocket."""
        self.subscribers.discard(ws)
        logger.info("ShogunBroadcaster: subscriber removed (total: %d)", len(self.subscribers))

    async def _loop(self) -> None:
        """Main broadcast loop."""
        while self.running:
            try:
                # Capture shogun pane (locked to serialize tmux access)
                output = await self.runtime.run_locked(
                    self.tmux.capture_shogun_pane
                )

                # Hash and diff
                import hashlib

                current_hash = hashlib.sha1(output.encode("utf-8")).hexdigest()
                has_changed = current_hash != self._last_hash

                # Keep output for new subscribers
                self._last_output = output
                self._last_hash = current_hash

                # Adjust polling interval
                if has_changed:
                    self.poller.on_change()
                else:
                    self.poller.on_no_change()

                # Broadcast output (only if changed)
                if has_changed:
                    payload = {"ts": time.time(), "output": output}
                    dead_sockets = []
                    for ws in self.subscribers:
                        try:
                            await ws.send_json(payload)
                        except Exception:
                            dead_sockets.append(ws)
                    # Remove failed websockets
                    for ws in dead_sockets:
                        self.subscribers.discard(ws)

                await asyncio.sleep(self.poller.current_interval)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.error("ShogunBroadcaster loop error", exc_info=True)
                await asyncio.sleep(self.poller.base_interval)
