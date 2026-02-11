"""
FastAPI エンドポイントのテスト
TmuxBridge をモックしてテストを実行
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_bridge():
    """TmuxBridge のモック（全テストで共通使用）"""
    instance = MagicMock()
    instance.read_dashboard.return_value = "# Test Dashboard\n\n将軍の指示を待つ"
    instance.read_command_history.return_value = [
        {
            "cmd_id": "cmd_001",
            "status": "done",
            "timestamp": "2026-02-06T00:00:00",
            "instruction": "test command 1",
        },
        {
            "cmd_id": "cmd_002",
            "status": "pending",
            "timestamp": "2026-02-06T00:01:00",
            "instruction": "test command 2",
        },
    ]
    instance.send_to_shogun.return_value = True
    instance.send_special_key.return_value = True
    return instance


@pytest.fixture
def client(mock_bridge):
    """FastAPI TestClient with mocked app.state"""
    from main import app

    # Create TestClient (this will trigger lifespan)
    with TestClient(app) as test_client:
        # Override app.state.tmux_bridge after lifespan
        app.state.tmux_bridge = mock_bridge
        yield test_client


class TestTopPage:
    """GET / のテスト"""

    def test_index_returns_200(self, client):
        """トップページが200を返す"""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_index_contains_html(self, client):
        """トップページがHTMLを含む"""
        response = client.get("/")
        assert b"<!DOCTYPE html>" in response.content or b"<html" in response.content


class TestDashboardAPI:
    """GET /api/dashboard のテスト"""

    def test_dashboard_returns_200(self, client, mock_bridge):
        """ダッシュボードAPIが200を返す"""
        response = client.get("/api/dashboard")
        assert response.status_code == 200

    def test_dashboard_calls_read_dashboard(self, client, mock_bridge):
        """read_dashboard() が呼ばれる"""
        client.get("/api/dashboard")
        mock_bridge.read_dashboard.assert_called_once()

    def test_dashboard_returns_content(self, client, mock_bridge):
        """ダッシュボード内容が返される"""
        response = client.get("/api/dashboard")
        assert "Test Dashboard" in response.text
        assert "将軍の指示を待つ" in response.text

    def test_dashboard_with_error(self, client, mock_bridge):
        """read_dashboard() がエラーを起こした場合"""
        mock_bridge.read_dashboard.side_effect = Exception("Dashboard read error")
        response = client.get("/api/dashboard")
        assert response.status_code == 200
        assert "Error" in response.text


class TestCommandAPI:
    """POST /api/command のテスト"""

    def test_command_returns_200(self, client, mock_bridge):
        """コマンド送信が200を返す"""
        response = client.post("/api/command", data={"instruction": "test"})
        assert response.status_code == 200

    def test_command_calls_send_to_shogun(self, client, mock_bridge):
        """send_to_shogun() が instruction をそのまま渡して呼ばれる"""
        client.post("/api/command", data={"instruction": "deploy system"})
        mock_bridge.send_to_shogun.assert_called_once_with("deploy system")

    def test_command_returns_sent_status(self, client, mock_bridge):
        """レスポンスに status: sent が含まれる（cmd_idは含まれない）"""
        response = client.post("/api/command", data={"instruction": "test"})
        data = response.json()
        assert data["status"] == "sent"
        assert "cmd_id" not in data

    def test_command_with_send_failure(self, client, mock_bridge):
        """send_to_shogun() が False を返した場合"""
        mock_bridge.send_to_shogun.return_value = False
        response = client.post("/api/command", data={"instruction": "test"})
        data = response.json()
        assert data["status"] == "error"
        assert "message" in data

    def test_command_with_exception(self, client, mock_bridge):
        """send_to_shogun() が例外を起こした場合"""
        mock_bridge.send_to_shogun.side_effect = Exception("Send error")
        response = client.post("/api/command", data={"instruction": "test"})
        data = response.json()
        assert data["status"] == "error"
        assert "message" in data

    def test_command_requires_instruction(self, client, mock_bridge):
        """instruction が必須"""
        response = client.post("/api/command", data={})
        assert response.status_code == 422  # Validation error


class TestHistoryAPI:
    """GET /api/history のテスト"""

    def test_history_returns_200(self, client, mock_bridge):
        """履歴APIが200を返す"""
        response = client.get("/api/history")
        assert response.status_code == 200

    def test_history_calls_read_command_history(self, client, mock_bridge):
        """read_command_history() が呼ばれる"""
        client.get("/api/history")
        mock_bridge.read_command_history.assert_called_once()

    def test_history_returns_html(self, client, mock_bridge):
        """履歴がHTMLとして返される"""
        response = client.get("/api/history")
        assert "text/html" in response.headers["content-type"]
        # cmd_id が含まれているか確認（テンプレートがレンダリングされている）
        assert "cmd_001" in response.text or "cmd_002" in response.text

    def test_history_with_error(self, client, mock_bridge):
        """read_command_history() がエラーを起こした場合"""
        mock_bridge.read_command_history.side_effect = Exception("History read error")
        response = client.get("/api/history")
        assert response.status_code == 200
        assert "Error" in response.text


class TestSpecialKeyAPI:
    """POST /api/special-key のテスト"""

    def test_special_key_escape_returns_200(self, client, mock_bridge):
        """Escapeキー送信が200を返す"""
        response = client.post("/api/special-key", json={"key": "Escape"})
        assert response.status_code == 200

    def test_special_key_calls_send_special_key(self, client, mock_bridge):
        """send_special_key() が Escape で呼ばれる"""
        client.post("/api/special-key", json={"key": "Escape"})
        mock_bridge.send_special_key.assert_called_once_with("Escape")

    def test_special_key_returns_sent_status(self, client, mock_bridge):
        """レスポンスに status: sent と key が含まれる"""
        response = client.post("/api/special-key", json={"key": "Escape"})
        data = response.json()
        assert data["status"] == "sent"
        assert data["key"] == "Escape"

    def test_special_key_with_disallowed_key(self, client, mock_bridge):
        """allowlist外のキー（Delete）は400エラー"""
        mock_bridge.send_special_key.side_effect = ValueError(
            "Key 'Delete' is not allowed. Allowed keys: {'Escape'}"
        )
        response = client.post("/api/special-key", json={"key": "Delete"})
        assert response.status_code == 400
        assert "not allowed" in response.json()["detail"]

    def test_special_key_requires_key(self, client, mock_bridge):
        """key が必須（422 バリデーションエラー）"""
        response = client.post("/api/special-key", json={})
        assert response.status_code == 422

    def test_special_key_with_send_failure(self, client, mock_bridge):
        """send_special_key() が False を返した場合"""
        mock_bridge.send_special_key.return_value = False
        response = client.post("/api/special-key", json={"key": "Escape"})
        data = response.json()
        assert data["status"] == "error"
        assert "message" in data


class TestSpecialKeyNewKeys:
    """POST /api/special-key の新キーテスト"""

    def test_special_key_enter(self, client, mock_bridge):
        """Enterキー送信が成功する"""
        response = client.post("/api/special-key", json={"key": "Enter"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "sent"
        assert data["key"] == "Enter"
        mock_bridge.send_special_key.assert_called_once_with("Enter")

    def test_special_key_tab(self, client, mock_bridge):
        """Tabキー送信が成功する"""
        response = client.post("/api/special-key", json={"key": "Tab"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "sent"
        assert data["key"] == "Tab"

    def test_special_key_btab(self, client, mock_bridge):
        """BTab (Shift+Tab) キー送信が成功する"""
        response = client.post("/api/special-key", json={"key": "BTab"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "sent"
        assert data["key"] == "BTab"

    def test_special_key_arrow_keys(self, client, mock_bridge):
        """矢印キー送信が成功する"""
        for key in ["Up", "Down", "Left", "Right"]:
            mock_bridge.reset_mock()
            response = client.post("/api/special-key", json={"key": key})
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "sent"
            assert data["key"] == key
            mock_bridge.send_special_key.assert_called_once_with(key)

    def test_special_key_numbers(self, client, mock_bridge):
        """数字キー送信が成功する"""
        for num in range(10):
            mock_bridge.reset_mock()
            key = str(num)
            response = client.post("/api/special-key", json={"key": key})
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "sent"
            assert data["key"] == key
            mock_bridge.send_special_key.assert_called_once_with(key)

    def test_special_key_yes_no(self, client, mock_bridge):
        """y/n キー送信が成功する"""
        for key in ["y", "n"]:
            mock_bridge.reset_mock()
            response = client.post("/api/special-key", json={"key": key})
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "sent"
            assert data["key"] == key
            mock_bridge.send_special_key.assert_called_once_with(key)

    def test_special_key_space(self, client, mock_bridge):
        """Spaceキー送信が成功する"""
        response = client.post("/api/special-key", json={"key": "Space"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "sent"
        assert data["key"] == "Space"

    def test_special_key_bspace(self, client, mock_bridge):
        """BSpace (Backspace) キー送信が成功する"""
        response = client.post("/api/special-key", json={"key": "BSpace"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "sent"
        assert data["key"] == "BSpace"


class TestWsConfigAPI:
    """GET /api/ws-config のテスト"""

    def test_ws_config_returns_200(self, client):
        """ws-config APIが200を返す"""
        response = client.get("/api/ws-config")
        assert response.status_code == 200

    def test_ws_config_returns_json(self, client):
        """ws-config APIがJSONを返す"""
        response = client.get("/api/ws-config")
        assert "application/json" in response.headers["content-type"]

    def test_ws_config_contains_monitor_section(self, client):
        """レスポンスにmonitorセクションが含まれる"""
        response = client.get("/api/ws-config")
        data = response.json()
        assert "monitor" in data
        assert "base_interval_ms" in data["monitor"]
        assert "max_interval_ms" in data["monitor"]

    def test_ws_config_contains_shogun_section(self, client):
        """レスポンスにshogunセクションが含まれる"""
        response = client.get("/api/ws-config")
        data = response.json()
        assert "shogun" in data
        assert "base_interval_ms" in data["shogun"]
        assert "max_interval_ms" in data["shogun"]

    def test_ws_config_monitor_values_match_settings(self, client):
        """monitor値がsettings.yamlの値と一致する"""
        response = client.get("/api/ws-config")
        data = response.json()
        # config/settings.yaml: monitor.base_interval_ms=5000, max_interval_ms=10000
        assert data["monitor"]["base_interval_ms"] == 5000
        assert data["monitor"]["max_interval_ms"] == 10000

    def test_ws_config_shogun_values_match_settings(self, client):
        """shogun値がsettings.yamlの値と一致する"""
        response = client.get("/api/ws-config")
        data = response.json()
        # config/settings.yaml: shogun.base_interval_ms=1000, max_interval_ms=3000
        assert data["shogun"]["base_interval_ms"] == 1000
        assert data["shogun"]["max_interval_ms"] == 3000

    def test_ws_config_values_are_integers(self, client):
        """全ての値が整数型である"""
        response = client.get("/api/ws-config")
        data = response.json()
        assert isinstance(data["monitor"]["base_interval_ms"], int)
        assert isinstance(data["monitor"]["max_interval_ms"], int)
        assert isinstance(data["shogun"]["base_interval_ms"], int)
        assert isinstance(data["shogun"]["max_interval_ms"], int)

    def test_ws_config_with_custom_settings(self, client):
        """app.state.settingsを変更した場合の値が反映される"""
        from main import app

        # カスタム設定を注入
        original_settings = app.state.settings
        app.state.settings = {
            "monitor": {"base_interval_ms": 3000, "max_interval_ms": 8000},
            "shogun": {"base_interval_ms": 500, "max_interval_ms": 2000},
        }
        try:
            response = client.get("/api/ws-config")
            data = response.json()
            assert data["monitor"]["base_interval_ms"] == 3000
            assert data["monitor"]["max_interval_ms"] == 8000
            assert data["shogun"]["base_interval_ms"] == 500
            assert data["shogun"]["max_interval_ms"] == 2000
        finally:
            app.state.settings = original_settings

    def test_ws_config_with_missing_monitor_key(self, client):
        """settingsにmonitorキーがない場合はデフォルト値を使用"""
        from main import app

        original_settings = app.state.settings
        app.state.settings = {
            "shogun": {"base_interval_ms": 1000, "max_interval_ms": 3000},
        }
        try:
            response = client.get("/api/ws-config")
            data = response.json()
            # デフォルト値: monitor.base_interval_ms=5000, max_interval_ms=10000
            assert data["monitor"]["base_interval_ms"] == 5000
            assert data["monitor"]["max_interval_ms"] == 10000
        finally:
            app.state.settings = original_settings

    def test_ws_config_with_missing_shogun_key(self, client):
        """settingsにshogunキーがない場合はデフォルト値を使用"""
        from main import app

        original_settings = app.state.settings
        app.state.settings = {
            "monitor": {"base_interval_ms": 5000, "max_interval_ms": 10000},
        }
        try:
            response = client.get("/api/ws-config")
            data = response.json()
            # デフォルト値: shogun.base_interval_ms=1000, max_interval_ms=3000
            assert data["shogun"]["base_interval_ms"] == 1000
            assert data["shogun"]["max_interval_ms"] == 3000
        finally:
            app.state.settings = original_settings

    def test_ws_config_with_empty_settings(self, client):
        """settingsが空の場合は全てデフォルト値"""
        from main import app

        original_settings = app.state.settings
        app.state.settings = {}
        try:
            response = client.get("/api/ws-config")
            data = response.json()
            assert data["monitor"]["base_interval_ms"] == 5000
            assert data["monitor"]["max_interval_ms"] == 10000
            assert data["shogun"]["base_interval_ms"] == 1000
            assert data["shogun"]["max_interval_ms"] == 3000
        finally:
            app.state.settings = original_settings


class TestMonitorClearAPI:
    """POST /api/monitor/clear のテスト"""

    def test_monitor_clear_returns_200(self, client):
        """モニタークリアAPIが200を返す"""
        response = client.post("/api/monitor/clear")
        assert response.status_code == 200

    def test_monitor_clear_returns_cleared_status(self, client):
        """レスポンスに status: cleared が含まれる"""
        response = client.post("/api/monitor/clear")
        data = response.json()
        assert data["status"] == "cleared"
