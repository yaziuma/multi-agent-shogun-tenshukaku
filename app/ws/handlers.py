"""WebSocket handlers for real-time updates."""

import logging

from fastapi import WebSocket, WebSocketDisconnect

from .broadcasters import MonitorBroadcaster, ShogunBroadcaster

logger = logging.getLogger(__name__)


class WebSocketHandler:
    """WebSocket handler for shogun pane real-time updates."""

    def __init__(self, broadcaster: ShogunBroadcaster) -> None:
        self.broadcaster = broadcaster

    async def handle(self, ws: WebSocket) -> None:
        """
        Handle WebSocket connection for shogun pane output.

        Subscribes the client to the broadcaster and keeps connection alive.
        """
        await ws.accept()
        await self.broadcaster.subscribe(ws)
        try:
            while True:
                await ws.receive_text()  # Keep-alive (client messages)
        except WebSocketDisconnect:
            pass  # Normal disconnection
        except Exception:
            logger.error("WebSocket error in shogun handler", exc_info=True)
        finally:
            await self.broadcaster.unsubscribe(ws)


class MonitorWebSocketHandler:
    """WebSocket handler for all multiagent panes monitoring."""

    def __init__(self, broadcaster: MonitorBroadcaster) -> None:
        self.broadcaster = broadcaster

    async def handle(self, ws: WebSocket) -> None:
        """
        Handle WebSocket connection for all panes monitoring.

        Subscribes the client to the broadcaster and keeps connection alive.
        """
        await ws.accept()
        await self.broadcaster.subscribe(ws)
        try:
            while True:
                await ws.receive_text()  # Keep-alive (client messages)
        except WebSocketDisconnect:
            pass  # Normal disconnection
        except Exception:
            logger.error("WebSocket error in monitor handler", exc_info=True)
        finally:
            await self.broadcaster.unsubscribe(ws)
