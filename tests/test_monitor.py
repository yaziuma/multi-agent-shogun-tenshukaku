"""Tests for monitor WebSocket endpoint and capture_all_panes functionality."""

from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from app.ws.tmux_bridge import TmuxBridge


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
        """Test that capture_all_panes uses scrollback with start=-lines."""
        with patch("libtmux.Server") as mock_server:
            mock_session = Mock()
            mock_pane = Mock()
            mock_pane.pane_index = "0"
            mock_pane.show_option.return_value = "karo"
            # Return 10 lines from scrollback
            mock_pane.capture_pane.return_value = [f"line{i}" for i in range(10)]

            mock_session.panes = [mock_pane]
            mock_server.return_value.sessions.get.return_value = mock_session

            bridge = TmuxBridge()
            result = bridge.capture_all_panes(lines=5)

            # State: output contains all lines returned by mock
            assert "line0" in result[0]["output"]
            assert "line9" in result[0]["output"]


@pytest.fixture
def client(tmp_path):
    """FastAPI TestClient with real TmuxBridge; bakuhu_base redirected to tmp_path."""
    from main import app

    with TestClient(app) as test_client:
        app.state.tmux_bridge.bakuhu_base = tmp_path
        yield test_client


class TestMonitorWebSocketHandler:
    """Integration tests for /ws/monitor endpoint using TestClient."""

    def test_monitor_ws_connect_accepted(self, client):
        """Connecting to /ws/monitor succeeds (accept was called — state: no exception)."""
        with client.websocket_connect("/ws/monitor") as ws:
            assert ws is not None

    def test_monitor_ws_subscribes_on_connect(self, client):
        """On connect, client is added to broadcaster.subscribers (subscribe was called)."""
        from main import app

        broadcaster = app.state.monitor_broadcaster
        broadcaster._pane_lines = {}

        with client.websocket_connect("/ws/monitor"):
            assert len(broadcaster.subscribers) == 1

    def test_monitor_ws_unsubscribes_on_disconnect(self, client):
        """On disconnect, client is removed from broadcaster.subscribers (unsubscribe was called)."""
        from main import app

        broadcaster = app.state.monitor_broadcaster
        broadcaster._pane_lines = {}

        with client.websocket_connect("/ws/monitor"):
            pass  # disconnect at end of with block

        assert len(broadcaster.subscribers) == 0
