from fastapi import WebSocket
import asyncio
import json
from .tmux_bridge import TmuxBridge


class WebSocketHandler:
    """WebSocket handler for real-time updates from tmux panes."""

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.tmux = TmuxBridge()

    async def handle(self) -> None:
        """
        Accept WebSocket connection and stream tmux output.

        Sends shogun pane output every second until connection closes.
        """
        await self.websocket.accept()
        try:
            while True:
                output = self.tmux.capture_shogun_pane()
                await self.websocket.send_text(output)
                await asyncio.sleep(1)
        except Exception:
            # Connection closed or error occurred
            pass


class MonitorWebSocketHandler:
    """WebSocket handler for monitoring all multiagent panes."""

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.tmux = TmuxBridge()

    async def handle(self) -> None:
        """
        Accept WebSocket connection and stream all panes output as JSON.

        Sends JSON array of all panes every second until connection closes.
        """
        await self.websocket.accept()
        try:
            while True:
                panes_data = self.tmux.capture_all_panes()
                json_str = json.dumps(panes_data, ensure_ascii=False)
                await self.websocket.send_text(json_str)
                await asyncio.sleep(1)
        except Exception:
            # Connection closed or error occurred
            pass
