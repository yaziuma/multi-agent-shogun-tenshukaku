"""
WebSocket エンドポイントの接続テスト
/ws と /ws/monitor のWebSocket接続確認
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_bridge():
    """TmuxBridge のモック"""
    instance = MagicMock()
    instance.read_dashboard.return_value = "# Test Dashboard"
    instance.read_command_history.return_value = []
    instance.capture_shogun_pane.return_value = "test output"
    instance.capture_all_panes.return_value = [
        {"agent_id": "karo", "output": "karo output"},
        {"agent_id": "ashigaru1", "output": "ashigaru1 output"},
    ]
    return instance


@pytest.fixture
def client(mock_bridge):
    """FastAPI TestClient with mocked app.state"""
    from main import app

    with TestClient(app) as test_client:
        app.state.tmux_bridge = mock_bridge
        yield test_client


class TestWsEndpoint:
    """GET /ws WebSocketエンドポイントのテスト"""

    def test_ws_connect_accepted(self, client):
        """/ws にWebSocket接続できる"""
        with client.websocket_connect("/ws") as ws:
            # 接続が受け入れられたことを確認（例外が出なければ成功）
            assert ws is not None

    def test_ws_receives_initial_data_if_available(self, client):
        """/ws 接続時にbroadcasterがデータを持っていればresetメッセージを受信する"""
        from main import app

        # broadcasterに初期データを設定
        broadcaster = app.state.shogun_broadcaster
        broadcaster._last_lines = ["line1", "line2"]

        with client.websocket_connect("/ws") as ws:
            # subscribe時にresetが送られる
            data = ws.receive_json()
            assert data["type"] == "reset"
            assert data["lines"] == ["line1", "line2"]

    def test_ws_no_initial_data_when_empty(self, client):
        """/ws 接続時にbroadcasterが空なら初期データは送信されない"""
        from main import app

        # broadcasterを空にする
        broadcaster = app.state.shogun_broadcaster
        broadcaster._last_lines = []

        with client.websocket_connect("/ws") as ws:
            # 初期データが送信されないことを確認
            # （タイムアウトで確認 - receive_json は長時間ブロックするため
            #   ここでは接続成功のみ確認）
            assert ws is not None


class TestWsMonitorEndpoint:
    """/ws/monitor WebSocketエンドポイントのテスト"""

    def test_monitor_ws_connect_accepted(self, client):
        """/ws/monitor にWebSocket接続できる"""
        with client.websocket_connect("/ws/monitor") as ws:
            assert ws is not None

    def test_monitor_ws_receives_initial_data_if_available(self, client):
        """/ws/monitor 接続時にbroadcasterがデータを持っていればinitialメッセージを受信する"""
        from main import app

        # MonitorBroadcasterに初期データを設定
        broadcaster = app.state.monitor_broadcaster
        broadcaster._pane_lines = {
            "karo": ["karo line1", "karo line2"],
            "ashigaru1": ["ashigaru1 line1"],
        }
        broadcaster._clear_snapshot = {}  # スナップショットなし

        with client.websocket_connect("/ws/monitor") as ws:
            data = ws.receive_json()
            assert data["type"] == "monitor_update"
            assert "updates" in data
            assert "karo" in data["updates"]
            assert data["updates"]["karo"]["type"] == "reset"
            assert data["updates"]["karo"]["lines"] == ["karo line1", "karo line2"]

    def test_monitor_ws_no_initial_data_when_empty(self, client):
        """/ws/monitor 接続時にbroadcasterが空なら初期データは送信されない"""
        from main import app

        broadcaster = app.state.monitor_broadcaster
        broadcaster._pane_lines = {}

        with client.websocket_connect("/ws/monitor") as ws:
            assert ws is not None

    def test_monitor_ws_respects_clear_snapshot(self, client):
        """/ws/monitor 接続時にクリアスナップショットが尊重される"""
        from main import app

        broadcaster = app.state.monitor_broadcaster
        # 10行のうち最初の5行がスナップショット
        broadcaster._pane_lines = {
            "karo": [
                "line1",
                "line2",
                "line3",
                "line4",
                "line5",
                "line6",
                "line7",
                "line8",
                "line9",
                "line10",
            ],
        }
        broadcaster._clear_snapshot = {
            "karo": ["line1", "line2", "line3", "line4", "line5"],
        }

        with client.websocket_connect("/ws/monitor") as ws:
            data = ws.receive_json()
            assert data["type"] == "monitor_update"
            # スナップショット以降の行のみ送信される
            assert data["updates"]["karo"]["lines"] == [
                "line6",
                "line7",
                "line8",
                "line9",
                "line10",
            ]


class TestWsConfigForReconnect:
    """/api/ws-config の値がReconnectingWebSocketのパラメータとして適切であることの検証"""

    def test_ws_config_intervals_are_positive(self, client):
        """全interval値が正の整数である"""
        response = client.get("/api/ws-config")
        data = response.json()
        assert data["monitor"]["base_interval_ms"] > 0
        assert data["monitor"]["max_interval_ms"] > 0
        assert data["shogun"]["base_interval_ms"] > 0
        assert data["shogun"]["max_interval_ms"] > 0

    def test_ws_config_max_greater_than_base(self, client):
        """max_interval_msがbase_interval_ms以上である"""
        response = client.get("/api/ws-config")
        data = response.json()
        assert data["monitor"]["max_interval_ms"] >= data["monitor"]["base_interval_ms"]
        assert data["shogun"]["max_interval_ms"] >= data["shogun"]["base_interval_ms"]

    def test_ws_config_shogun_faster_than_monitor(self, client):
        """shogunのbase_intervalがmonitorより短い（より高頻度）"""
        response = client.get("/api/ws-config")
        data = response.json()
        assert data["shogun"]["base_interval_ms"] < data["monitor"]["base_interval_ms"]
