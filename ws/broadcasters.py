"""WebSocket broadcaster components for real-time tmux monitoring."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from fastapi import WebSocket

from .delta import compute_delta
from .runtime import TmuxRuntime
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
            self.current_interval = min(self.max_interval, self.current_interval * 2)


@dataclass
class MonitorBroadcaster:
    """Broadcaster for all multiagent panes with delta updates."""

    tmux: TmuxBridge
    runtime: TmuxRuntime
    poller: AdaptivePoller
    subscribers: set[WebSocket] = field(default_factory=set)
    _pane_lines: dict[str, list[str]] = field(default_factory=dict)
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
        # Send initial full data to new subscriber as reset for each pane
        if self._pane_lines:
            try:
                updates = {}
                for pane_id, lines in self._pane_lines.items():
                    updates[pane_id] = {"type": "reset", "lines": lines}
                payload = {
                    "type": "monitor_update",
                    "updates": updates,
                    "ts": time.time(),
                }
                await ws.send_json(payload)
            except Exception:
                logger.error("Failed to send initial data to new subscriber")
        logger.info(
            "MonitorBroadcaster: subscriber added (total: %d)", len(self.subscribers)
        )

    async def unsubscribe(self, ws: WebSocket) -> None:
        """Unsubscribe a websocket."""
        self.subscribers.discard(ws)
        logger.info(
            "MonitorBroadcaster: subscriber removed (total: %d)", len(self.subscribers)
        )

    async def _loop(self) -> None:
        """Main broadcast loop with delta updates."""
        while self.running:
            try:
                # Capture all panes (locked to serialize tmux access)
                panes_data = await self.runtime.run_locked(self.tmux.capture_all_panes)

                # Convert to dict[str, list[str]] for delta computation
                panes_lines = {
                    item["agent_id"]: item["output"].splitlines() for item in panes_data
                }

                # Compute delta for each pane
                delta_updates = {}
                for pane_id, curr_lines in panes_lines.items():
                    prev_lines = self._pane_lines.get(pane_id, [])
                    delta_result = compute_delta(prev_lines, curr_lines)
                    if delta_result["type"] != "noop":
                        delta_updates[pane_id] = delta_result

                # Update stored state
                self._pane_lines = panes_lines

                # Adjust polling interval
                if delta_updates:
                    self.poller.on_change()
                else:
                    self.poller.on_no_change()

                # Broadcast updates (only if non-empty)
                if delta_updates:
                    payload = {
                        "type": "monitor_update",
                        "updates": delta_updates,
                        "ts": time.time(),
                    }
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
    """Broadcaster for shogun pane output with delta updates."""

    tmux: TmuxBridge
    runtime: TmuxRuntime
    poller: AdaptivePoller
    subscribers: set[WebSocket] = field(default_factory=set)
    _last_lines: list[str] = field(default_factory=list)
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
        # Send current full output to new subscriber as reset
        if self._last_lines:
            try:
                payload = {
                    "type": "reset",
                    "lines": self._last_lines,
                    "ts": time.time(),
                }
                await ws.send_json(payload)
            except Exception:
                logger.error("Failed to send initial output to new subscriber")
        logger.info(
            "ShogunBroadcaster: subscriber added (total: %d)", len(self.subscribers)
        )

    async def unsubscribe(self, ws: WebSocket) -> None:
        """Unsubscribe a websocket."""
        self.subscribers.discard(ws)
        logger.info(
            "ShogunBroadcaster: subscriber removed (total: %d)", len(self.subscribers)
        )

    async def _loop(self) -> None:
        """Main broadcast loop with delta updates."""
        while self.running:
            try:
                # Capture shogun pane (locked to serialize tmux access)
                output = await self.runtime.run_locked(self.tmux.capture_shogun_pane)

                # Split into lines for delta computation
                curr_lines = output.splitlines()

                # Compute delta
                delta_result = compute_delta(self._last_lines, curr_lines)

                # Update stored lines
                self._last_lines = curr_lines

                # Adjust polling interval
                if delta_result["type"] != "noop":
                    self.poller.on_change()
                else:
                    self.poller.on_no_change()

                # Broadcast delta (only if not noop)
                if delta_result["type"] != "noop":
                    payload = {
                        "type": delta_result["type"],
                        "lines": delta_result.get("lines", []),
                        "ts": time.time(),
                    }
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
