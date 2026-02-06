from fastapi import WebSocket
import asyncio
from .tmux_bridge import TmuxBridge


class WebSocketHandler:
    """WebSocket handler for real-time updates from tmux panes."""

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.tmux = TmuxBridge()

    async def handle(self) -> None:
        """
        Accept WebSocket connection and stream tmux output.

        Sends karo pane output every second until connection closes.
        """
        await self.websocket.accept()
        try:
            # Send karo pane output every second
            while True:
                output = self.tmux.capture_karo_pane()
                await self.websocket.send_text(output)
                await asyncio.sleep(1)
        except Exception:
            # Connection closed or error occurred
            pass
