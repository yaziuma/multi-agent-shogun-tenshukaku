"""Tests for monitor WebSocket endpoint and capture_all_panes functionality."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from ws.handlers import MonitorWebSocketHandler
from ws.tmux_bridge import TmuxBridge


class TestCaptureAllPanes:
    """Test TmuxBridge.capture_all_panes() method."""

    def test_capture_all_panes_no_session(self):
        """Test capture_all_panes when multiagent session is not found."""
        with patch("libtmux.Server") as mock_server:
            mock_server.return_value.sessions.get.return_value = None
            bridge = TmuxBridge()
            result = bridge.capture_all_panes()
            assert result == []

    def test_capture_all_panes_with_agent_ids(self):
        """Test capture_all_panes with @agent_id set on panes."""
        with patch("libtmux.Server") as mock_server:
            # Mock multiagent session with 2 panes
            mock_session = Mock()
            mock_pane1 = Mock()
            mock_pane1.pane_index = "0"
            mock_pane1.show_option.return_value = "karo"
            mock_pane1.capture_pane.return_value = ["line1", "line2", "line3"]

            mock_pane2 = Mock()
            mock_pane2.pane_index = "1"
            mock_pane2.show_option.return_value = "ashigaru1"
            mock_pane2.capture_pane.return_value = ["output1", "output2"]

            mock_session.panes = [mock_pane1, mock_pane2]
            mock_server.return_value.sessions.get.return_value = mock_session

            bridge = TmuxBridge()
            result = bridge.capture_all_panes()

            assert len(result) == 2
            assert result[0]["agent_id"] == "karo"
            assert result[0]["pane_index"] == 0
            assert result[0]["output"] == "line1\nline2\nline3"
            assert result[1]["agent_id"] == "ashigaru1"
            assert result[1]["pane_index"] == 1
            assert result[1]["output"] == "output1\noutput2"

    def test_capture_all_panes_without_agent_ids(self):
        """Test capture_all_panes when @agent_id is not set."""
        with patch("libtmux.Server") as mock_server:
            mock_session = Mock()
            mock_pane = Mock()
            mock_pane.pane_index = "3"
            mock_pane.show_option.return_value = None
            mock_pane.capture_pane.return_value = ["output"]

            mock_session.panes = [mock_pane]
            mock_server.return_value.sessions.get.return_value = mock_session

            bridge = TmuxBridge()
            result = bridge.capture_all_panes()

            assert len(result) == 1
            assert result[0]["agent_id"] == "pane_3"
            assert result[0]["pane_index"] == 3

    def test_capture_all_panes_with_error(self):
        """Test capture_all_panes when pane capture fails."""
        with patch("libtmux.Server") as mock_server:
            mock_session = Mock()
            mock_pane = Mock()
            mock_pane.pane_index = "0"
            mock_pane.show_option.return_value = "karo"
            mock_pane.capture_pane.side_effect = Exception("Capture failed")

            mock_session.panes = [mock_pane]
            mock_server.return_value.sessions.get.return_value = mock_session

            bridge = TmuxBridge()
            result = bridge.capture_all_panes()

            assert len(result) == 1
            assert result[0]["output"] == "Error: failed to capture pane"

    def test_capture_all_panes_limits_lines(self):
        """Test that capture_all_panes respects the lines parameter."""
        with patch("libtmux.Server") as mock_server:
            mock_session = Mock()
            mock_pane = Mock()
            mock_pane.pane_index = "0"
            mock_pane.show_option.return_value = "karo"
            # Return 10 lines
            mock_pane.capture_pane.return_value = [f"line{i}" for i in range(10)]

            mock_session.panes = [mock_pane]
            mock_server.return_value.sessions.get.return_value = mock_session

            bridge = TmuxBridge()
            result = bridge.capture_all_panes(lines=5)

            # Should only get the last 5 lines
            assert result[0]["output"] == "line5\nline6\nline7\nline8\nline9"


class TestMonitorWebSocketHandler:
    """Test MonitorWebSocketHandler class."""

    @pytest.mark.asyncio
    async def test_monitor_handler_with_broadcaster(self):
        """Test that MonitorWebSocketHandler works with broadcaster pattern."""
        mock_websocket = AsyncMock()
        mock_broadcaster = AsyncMock()

        handler = MonitorWebSocketHandler(mock_broadcaster)

        # Mock receive_text to raise WebSocketDisconnect after subscribe
        from fastapi import WebSocketDisconnect

        mock_websocket.receive_text.side_effect = WebSocketDisconnect()

        # Run handler
        await handler.handle(mock_websocket)

        # Verify websocket.accept was called
        mock_websocket.accept.assert_called_once()

        # Verify subscribe/unsubscribe were called
        mock_broadcaster.subscribe.assert_called_once_with(mock_websocket)
        mock_broadcaster.unsubscribe.assert_called_once_with(mock_websocket)

    @pytest.mark.asyncio
    async def test_monitor_handler_handles_exception(self):
        """Test that MonitorWebSocketHandler handles exceptions gracefully."""
        mock_websocket = AsyncMock()
        mock_broadcaster = AsyncMock()

        handler = MonitorWebSocketHandler(mock_broadcaster)

        # Mock receive_text to raise a generic exception
        mock_websocket.receive_text.side_effect = Exception("Connection error")

        # Should not raise exception and exit gracefully
        await handler.handle(mock_websocket)

        # Verify accept was called
        mock_websocket.accept.assert_called_once()

        # Verify subscribe/unsubscribe were called
        mock_broadcaster.subscribe.assert_called_once_with(mock_websocket)
        mock_broadcaster.unsubscribe.assert_called_once_with(mock_websocket)
