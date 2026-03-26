"""
FastAPI エンドポイントのテスト
Detroit学派（古典学派）: 実オブジェクト + 状態検証
"""

import subprocess
from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    """FastAPI TestClient with real TmuxBridge; bakuhu_base redirected to tmp_path."""
    from main import app

    with TestClient(app) as test_client:
        app.state.tmux_bridge.bakuhu_base = tmp_path
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

    def test_dashboard_returns_200(self, client):
        """ダッシュボードAPIが200を返す"""
        response = client.get("/api/dashboard")
        assert response.status_code == 200

    def test_dashboard_returns_content(self, client, tmp_path):
        """ダッシュボード内容が返される"""
        (tmp_path / "dashboard.md").write_text("# Test Dashboard\n\n将軍の指示を待つ")
        response = client.get("/api/dashboard")
        assert "Test Dashboard" in response.text
        assert "将軍の指示を待つ" in response.text

    def test_dashboard_with_error(self, client, tmp_path):
        """読み取り不能なdashboard（ディレクトリ）の場合はErrorが返される"""
        (tmp_path / "dashboard.md").mkdir()  # ディレクトリにすると read_text() が失敗
        response = client.get("/api/dashboard")
        assert response.status_code == 200
        assert "Error" in response.text


class TestCommandAPI:
    """POST /api/command のテスト"""

    def test_command_returns_200(self, client):
        """コマンド送信が200を返す"""
        with patch("subprocess.run"):
            response = client.post("/api/command", data={"instruction": "test"})
        assert response.status_code == 200

    def test_command_returns_sent_status(self, client):
        """レスポンスに status: sent が含まれる（cmd_idは含まれない）"""
        with patch("subprocess.run"):
            response = client.post("/api/command", data={"instruction": "test"})
        data = response.json()
        assert data["status"] == "sent"
        assert "cmd_id" not in data

    def test_command_with_send_failure(self, client):
        """tmuxコマンド失敗時にstatus: errorが返される"""
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "tmux")):
            response = client.post("/api/command", data={"instruction": "test"})
        data = response.json()
        assert data["status"] == "error"
        assert "message" in data

    def test_command_with_exception(self, client):
        """予期せぬ例外時にstatus: errorが返される"""
        with patch("subprocess.run", side_effect=Exception("Send error")):
            response = client.post("/api/command", data={"instruction": "test"})
        data = response.json()
        assert data["status"] == "error"
        assert "message" in data

    def test_command_requires_instruction(self, client):
        """instruction が必須"""
        response = client.post("/api/command", data={})
        assert response.status_code == 422  # Validation error


class TestHistoryAPI:
    """GET /api/history のテスト"""

    def test_history_returns_200(self, client):
        """履歴APIが200を返す"""
        response = client.get("/api/history")
        assert response.status_code == 200

    def test_history_returns_html(self, client, tmp_path):
        """履歴がHTMLとして返される"""
        queue_dir = tmp_path / "queue"
        queue_dir.mkdir()
        (queue_dir / "shogun_to_karo.yaml").write_text(
            yaml.dump({
                "commands": [
                    {"cmd_id": "cmd_001", "instruction": "test command 1",
                     "status": "done", "timestamp": "2026-02-06T00:00:00"},
                    {"cmd_id": "cmd_002", "instruction": "test command 2",
                     "status": "pending", "timestamp": "2026-02-06T00:01:00"},
                ]
            })
        )
        response = client.get("/api/history")
        assert "text/html" in response.headers["content-type"]
        assert "cmd_001" in response.text or "cmd_002" in response.text

    def test_history_with_error(self, client, tmp_path):
        """read_command_history() がエラーを起こした場合"""
        queue_dir = tmp_path / "queue"
        queue_dir.mkdir()
        (queue_dir / "shogun_to_karo.yaml").mkdir()  # ディレクトリにすると open() が失敗
        response = client.get("/api/history")
        assert response.status_code == 200
        assert "Error" in response.text


class TestSpecialKeyAPI:
    """POST /api/special-key のテスト"""

    def test_special_key_escape_returns_200(self, client):
        """Escapeキー送信が200を返す"""
        with patch("subprocess.run"):
            response = client.post("/api/special-key", json={"key": "Escape"})
        assert response.status_code == 200

    def test_special_key_returns_sent_status(self, client):
        """レスポンスに status: sent と key が含まれる"""
        with patch("subprocess.run"):
            response = client.post("/api/special-key", json={"key": "Escape"})
        data = response.json()
        assert data["status"] == "sent"
        assert data["key"] == "Escape"

    def test_special_key_with_disallowed_key(self, client):
        """allowlist外のキー（Delete）は400エラー"""
        response = client.post("/api/special-key", json={"key": "Delete"})
        assert response.status_code == 400
        assert "not allowed" in response.json()["detail"]

    def test_special_key_requires_key(self, client):
        """key が必須（422 バリデーションエラー）"""
        response = client.post("/api/special-key", json={})
        assert response.status_code == 422

    def test_special_key_with_send_failure(self, client):
        """tmuxコマンド失敗時にstatus: errorが返される"""
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "tmux")):
            response = client.post("/api/special-key", json={"key": "Escape"})
        data = response.json()
        assert data["status"] == "error"
        assert "message" in data


class TestSpecialKeyNewKeys:
    """POST /api/special-key の新キーテスト"""

    def test_special_key_enter(self, client):
        """Enterキー送信が成功する"""
        with patch("subprocess.run"):
            response = client.post("/api/special-key", json={"key": "Enter"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "sent"
        assert data["key"] == "Enter"

    def test_special_key_tab(self, client):
        """Tabキー送信が成功する"""
        with patch("subprocess.run"):
            response = client.post("/api/special-key", json={"key": "Tab"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "sent"
        assert data["key"] == "Tab"

    def test_special_key_btab(self, client):
        """BTab (Shift+Tab) キー送信が成功する"""
        with patch("subprocess.run"):
            response = client.post("/api/special-key", json={"key": "BTab"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "sent"
        assert data["key"] == "BTab"

    def test_special_key_arrow_keys(self, client):
        """矢印キー送信が成功する"""
        for key in ["Up", "Down", "Left", "Right"]:
            with patch("subprocess.run"):
                response = client.post("/api/special-key", json={"key": key})
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "sent"
            assert data["key"] == key

    def test_special_key_numbers(self, client):
        """数字キー送信が成功する"""
        for num in range(10):
            key = str(num)
            with patch("subprocess.run"):
                response = client.post("/api/special-key", json={"key": key})
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "sent"
            assert data["key"] == key

    def test_special_key_yes_no(self, client):
        """y/n キー送信が成功する"""
        for key in ["y", "n"]:
            with patch("subprocess.run"):
                response = client.post("/api/special-key", json={"key": key})
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "sent"
            assert data["key"] == key

    def test_special_key_space(self, client):
        """Spaceキー送信が成功する"""
        with patch("subprocess.run"):
            response = client.post("/api/special-key", json={"key": "Space"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "sent"
        assert data["key"] == "Space"

    def test_special_key_bspace(self, client):
        """BSpace (Backspace) キー送信が成功する"""
        with patch("subprocess.run"):
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
