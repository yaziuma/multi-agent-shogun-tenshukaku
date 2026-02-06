"""
FastAPI エンドポイントのテスト
TmuxBridge をモックしてテストを実行
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def mock_bridge():
    """TmuxBridge のモック（全テストで共通使用）"""
    with patch("main.TmuxBridge") as MockBridge:
        instance = MockBridge.return_value
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
        yield instance


@pytest.fixture
def client(mock_bridge):
    """FastAPI TestClient"""
    from main import app

    return TestClient(app)


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
        response = client.get("/api/dashboard")
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
        response = client.post("/api/command", data={"instruction": "deploy system"})
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
        response = client.get("/api/history")
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
        response = client.post("/api/special-key", json={"key": "Escape"})
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
