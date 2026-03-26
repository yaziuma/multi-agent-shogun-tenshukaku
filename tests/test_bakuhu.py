"""tests/test_bakuhu.py - 幕府間連携プロトコルテスト（設計書: protocol_v2.md）"""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

from app.bakuhu.bakuhu_node import (
    BakuhuNode,
    BakuhuRpcClientMethods,
    BakuhuRpcServerMethods,
    _load_accepted_tokens,
    _mask_token_url,
)
from app.bakuhu.bakuhu_routes import router as bakuhu_router


# ------------------------------------------------------------------ #
# テスト用設定・フィクスチャ
# ------------------------------------------------------------------ #

def make_settings(tmp_path: Path, role: str = "primary", extra: dict | None = None) -> dict:
    base = {
        "bakuhu": {
            "base_path": str(tmp_path),
            "role": role,
            "name": f"{role}-bakuhu",
            "outbound_token": "token-primary",
            "accepted_tokens": {
                "token-secondary-a": "secondary-a",
                "token-secondary-b": "secondary-b",
            },
            "upload_dir": "cross_bakuhu/files",
            "peers": [
                {"id": "secondary-a", "name": "従属幕府A", "base_url": "http://secondary-a.test:30001"},
            ],
        }
    }
    if extra:
        base.update(extra)
    return base


def make_app(settings: dict) -> FastAPI:
    """テスト用FastAPIアプリ（lifespanなし、stateを直接セット）"""
    app = FastAPI()
    app.include_router(bakuhu_router)
    app.state.settings = settings
    app.state.bakuhu_node = BakuhuNode(settings=settings)
    return app


# ------------------------------------------------------------------ #
# TC-AUTH-01～07: 認証テスト
# ------------------------------------------------------------------ #

class TestAuthentication:
    def test_valid_token_accepted(self, tmp_path):
        """TC-AUTH-01相当: 有効tokenで接続成功"""
        settings = make_settings(tmp_path)
        from app.bakuhu.bakuhu_routes import _authenticate_token
        peer_id = _authenticate_token("token-secondary-a", settings)
        assert peer_id == "secondary-a"

    def test_invalid_token_rejected(self, tmp_path):
        """TC-AUTH-02相当: 無効token拒否"""
        settings = make_settings(tmp_path)
        from app.bakuhu.bakuhu_routes import _authenticate_token
        peer_id = _authenticate_token("invalid-token", settings)
        assert peer_id is None

    def test_missing_token_rejected(self, tmp_path):
        """TC-AUTH-03相当: token未指定拒否"""
        settings = make_settings(tmp_path)
        from app.bakuhu.bakuhu_routes import _authenticate_token
        peer_id = _authenticate_token("", settings)
        assert peer_id is None

    def test_token_masking(self):
        """TC-AUTH-04相当: tokenログマスキング"""
        url = "ws://example.com/bakuhu/ws/rpc?token=secret-value"
        masked = _mask_token_url(url)
        assert "secret-value" not in masked
        assert "?token=***" in masked

    def test_env_override(self, tmp_path, monkeypatch):
        """TC-AUTH-05相当: 環境変数上書き"""
        settings = make_settings(tmp_path)
        monkeypatch.setenv("BAKUHU_ACCEPTED_TOKENS_TOKEN_SECONDARY_A", "overridden-peer")
        tokens = _load_accepted_tokens(settings)
        assert tokens.get("token-secondary-a") == "overridden-peer"

    def test_collision_raises(self, tmp_path):
        """TC-AUTH-06相当: 変換キー衝突で起動拒否"""
        settings = make_settings(tmp_path)
        settings["bakuhu"]["accepted_tokens"] = {
            "token-a.b": "peer1",
            "token_a-b": "peer2",  # "TOKEN_A_B" に衝突
        }
        with pytest.raises(RuntimeError, match="collision"):
            _load_accepted_tokens(settings)

    def test_multiple_tokens_loaded(self, tmp_path):
        """複数tokenが全て読み込まれる"""
        settings = make_settings(tmp_path)
        tokens = _load_accepted_tokens(settings)
        assert "token-secondary-a" in tokens
        assert "token-secondary-b" in tokens


# ------------------------------------------------------------------ #
# TC-FT-01～06: ファイル転送テスト
# ------------------------------------------------------------------ #

class TestFileTransfer:
    @pytest.mark.asyncio
    async def test_normal_upload(self, tmp_path):
        """TC-FT-01相当: 正常転送（小サイズ）"""
        settings = make_settings(tmp_path)
        app = make_app(settings)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            content = b"hello bakuhu" * 100
            response = await client.post(
                "/bakuhu/files?request_id=req001&from_bakuhu=secondary-a&token=token-secondary-a",
                files={"file": ("test.txt", content, "text/plain")},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "saved"
        assert "tenshukaku_upload_" in data["artifact_path"]
        assert Path(data["artifact_path"]).exists()

    @pytest.mark.asyncio
    async def test_size_exceeded(self, tmp_path):
        """TC-FT-03相当: 上限超過（200MB+1byte）"""
        settings = make_settings(tmp_path)
        app = make_app(settings)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 小さなファイルでMAX_UPLOAD_BYTESを一時的に0にしてテスト
            with patch("app.bakuhu.bakuhu_routes.MAX_UPLOAD_BYTES", 10):
                content = b"a" * 11
                response = await client.post(
                    "/bakuhu/files?request_id=req002&from_bakuhu=secondary-a&token=token-secondary-a",
                    files={"file": ("big.bin", content, "application/octet-stream")},
                )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_path_traversal_sanitized(self, tmp_path):
        """TC-FT-04相当: ファイル名サニタイズ"""
        settings = make_settings(tmp_path)
        app = make_app(settings)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            content = b"malicious"
            response = await client.post(
                "/bakuhu/files?request_id=req003&from_bakuhu=secondary-a&token=token-secondary-a",
                files={"file": ("../../../etc/passwd", content, "text/plain")},
            )
        assert response.status_code == 200
        data = response.json()
        # basenameになっているのでパストラバーサルなし
        assert ".." not in data["artifact_path"]
        assert "/etc/passwd" not in data["artifact_path"]

    @pytest.mark.asyncio
    async def test_peer_mismatch_rejected(self, tmp_path):
        """TC-FT-05相当: from_bakuhu不一致で422"""
        settings = make_settings(tmp_path)
        app = make_app(settings)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            content = b"test"
            response = await client.post(
                "/bakuhu/files?request_id=req004&from_bakuhu=wrong-peer&token=token-secondary-a",
                files={"file": ("test.txt", content, "text/plain")},
            )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_token_rejected(self, tmp_path):
        """無効tokenは403"""
        settings = make_settings(tmp_path)
        app = make_app(settings)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/bakuhu/files?request_id=req005&from_bakuhu=secondary-a&token=invalid",
                files={"file": ("test.txt", b"data", "text/plain")},
            )
        assert response.status_code == 403


# ------------------------------------------------------------------ #
# TC-DEL-01～04: 委任フローテスト（BakuhuRpcServerMethods）
# ------------------------------------------------------------------ #

class TestDelegation:
    @pytest.mark.asyncio
    async def test_submit_delegation_accepted(self, tmp_path):
        """TC-DEL-01相当: submit_delegation正常受付"""
        settings = make_settings(tmp_path)
        node = BakuhuNode(settings=settings)
        methods = BakuhuRpcServerMethods(node)

        result = await methods.submit_delegation(
            request_id="req-001",
            content="タスクを実行せよ",
            from_bakuhu="primary-bakuhu",
            priority="normal",
        )
        assert result["accepted"] is True
        assert result["request_id"] == "req-001"
        assert result["status"] == "received"

        # inboxに書き込まれているか確認
        inbox_path = node._inbox_path("shogun")
        assert inbox_path.exists()
        with open(inbox_path) as f:
            data = yaml.safe_load(f)
        assert any(m.get("request_id") == "req-001" for m in data.get("messages", []))

    @pytest.mark.asyncio
    async def test_submit_delegation_duplicate(self, tmp_path):
        """TC-DEL-02相当: 重複抑止"""
        settings = make_settings(tmp_path)
        node = BakuhuNode(settings=settings)
        methods = BakuhuRpcServerMethods(node)

        await methods.submit_delegation(
            request_id="req-dup", content="初回", from_bakuhu="primary", priority="normal"
        )
        result2 = await methods.submit_delegation(
            request_id="req-dup", content="重複", from_bakuhu="primary", priority="normal"
        )
        assert result2["accepted"] is False
        assert result2["reason"] == "duplicate"

        # inboxは1件のみ
        inbox_path = node._inbox_path("shogun")
        with open(inbox_path) as f:
            data = yaml.safe_load(f)
        entries = [m for m in data.get("messages", []) if m.get("request_id") == "req-dup"]
        assert len(entries) == 1

    @pytest.mark.asyncio
    async def test_submit_delegation_concurrent_dedup(self, tmp_path):
        """TC-DEL-03相当: 同時実行競合でも1件のみ受付"""
        settings = make_settings(tmp_path)
        node = BakuhuNode(settings=settings)
        methods = BakuhuRpcServerMethods(node)

        results = await asyncio.gather(
            *[
                methods.submit_delegation(
                    request_id="req-concurrent", content="並列", from_bakuhu="primary", priority="normal"
                )
                for _ in range(10)
            ]
        )

        accepted = [r for r in results if r["accepted"]]
        duplicates = [r for r in results if not r["accepted"]]
        assert len(accepted) == 1
        assert len(duplicates) == 9

    @pytest.mark.asyncio
    async def test_submit_delegation_invalid_priority(self, tmp_path):
        """TC-DEL-04相当: 無効priorityはエラー"""
        settings = make_settings(tmp_path)
        node = BakuhuNode(settings=settings)
        methods = BakuhuRpcServerMethods(node)

        result = await methods.submit_delegation(
            request_id="req-inv", content="test", from_bakuhu="primary", priority="urgent"
        )
        assert result["accepted"] is False
        assert "invalid_priority" in result["reason"]

    @pytest.mark.asyncio
    async def test_submit_delegation_missing_fields(self, tmp_path):
        """必須フィールド欠落でエラー"""
        settings = make_settings(tmp_path)
        node = BakuhuNode(settings=settings)
        methods = BakuhuRpcServerMethods(node)

        result = await methods.submit_delegation(request_id="", content="", from_bakuhu="")
        assert result["accepted"] is False


# ------------------------------------------------------------------ #
# push_result / push_status テスト
# ------------------------------------------------------------------ #

class TestPushCallbacks:
    @pytest.mark.asyncio
    async def test_push_result_accepted(self, tmp_path):
        """push_result正常受付"""
        settings = make_settings(tmp_path)
        node = BakuhuNode(settings=settings)
        methods = BakuhuRpcClientMethods(node)

        result = await methods.push_result(
            request_id="req-r01",
            summary="完了しました",
            status="succeeded",
            artifact_path="/tmp/result.txt",
            from_bakuhu="secondary-a",
        )
        assert result["accepted"] is True

    @pytest.mark.asyncio
    async def test_push_result_invalid_status(self, tmp_path):
        """TC-ERR-03相当: 無効status拒否"""
        settings = make_settings(tmp_path)
        node = BakuhuNode(settings=settings)
        methods = BakuhuRpcClientMethods(node)

        result = await methods.push_result(
            request_id="req-inv", summary="", status="done", from_bakuhu="secondary-a"
        )
        assert result["accepted"] is False

    @pytest.mark.asyncio
    async def test_push_result_duplicate_suppressed(self, tmp_path):
        """TC-RQ-03相当: 重複push_result抑止"""
        settings = make_settings(tmp_path)
        node = BakuhuNode(settings=settings)
        methods = BakuhuRpcClientMethods(node)

        await methods.push_result(
            request_id="req-r02", summary="完了", status="succeeded", from_bakuhu="secondary-a"
        )
        result2 = await methods.push_result(
            request_id="req-r02", summary="重複", status="succeeded", from_bakuhu="secondary-a"
        )
        assert result2["accepted"] is False
        assert result2["reason"] == "duplicate"

    @pytest.mark.asyncio
    async def test_push_status_normal(self, tmp_path):
        """TC-PS-01相当: push_status正常受付"""
        settings = make_settings(tmp_path)
        node = BakuhuNode(settings=settings)
        methods = BakuhuRpcClientMethods(node)

        for status in ["validated", "queued", "in_progress"]:
            result = await methods.push_status(
                request_id=f"req-ps01",
                status=status,
                from_bakuhu="secondary-a",
            )
            assert result["accepted"] is True

    @pytest.mark.asyncio
    async def test_push_status_invalid_value(self, tmp_path):
        """TC-PS-03相当: 不正status拒否"""
        settings = make_settings(tmp_path)
        node = BakuhuNode(settings=settings)
        methods = BakuhuRpcClientMethods(node)

        result = await methods.push_status(
            request_id="req-ps02", status="done", from_bakuhu="secondary-a"
        )
        assert result["accepted"] is False

    @pytest.mark.asyncio
    async def test_push_status_after_complete_ignored(self, tmp_path):
        """TC-PS-04相当: 完了後の中間通知は無視"""
        settings = make_settings(tmp_path)
        node = BakuhuNode(settings=settings)
        node.mark_completed("req-ps03")
        methods = BakuhuRpcClientMethods(node)

        result = await methods.push_status(
            request_id="req-ps03", status="in_progress", from_bakuhu="secondary-a"
        )
        assert result["accepted"] is False
        assert result["reason"] == "already_completed"


# ------------------------------------------------------------------ #
# 重複排除キャッシュ TTLテスト
# ------------------------------------------------------------------ #

class TestDedupCache:
    def test_dedup_ttl_fresh(self, tmp_path):
        """同一キーは60秒以内に重複判定"""
        settings = make_settings(tmp_path)
        node = BakuhuNode(settings=settings)

        assert node.is_duplicate("key-a") is False  # 初回
        assert node.is_duplicate("key-a") is True   # 2回目

    def test_dedup_ttl_expired(self, tmp_path):
        """60秒後は重複判定クリア"""
        from freezegun import freeze_time

        settings = make_settings(tmp_path)
        node = BakuhuNode(settings=settings)

        with freeze_time("2026-01-01 00:00:00"):
            node.is_duplicate("key-b")  # 登録

        with freeze_time("2026-01-01 00:01:01"):  # 61秒後
            result = node.is_duplicate("key-b")

        assert result is False  # 期限切れで再登録可能


# ------------------------------------------------------------------ #
# Peer状態 / healthz テスト
# ------------------------------------------------------------------ #

class TestPeerStatus:
    @pytest.mark.asyncio
    async def test_healthz_returns_ok(self, tmp_path):
        """TC-MGMT相当: /bakuhu/healthz が200を返す"""
        settings = make_settings(tmp_path)
        app = make_app(settings)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/bakuhu/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_peers_returns_list(self, tmp_path):
        """GET /bakuhu/peers がpeerリストを返す"""
        settings = make_settings(tmp_path)
        app = make_app(settings)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/bakuhu/peers")
        assert response.status_code == 200
        data = response.json()
        assert "peers" in data
        assert isinstance(data["peers"], list)

    @pytest.mark.asyncio
    async def test_peer_status_offline_when_not_connected(self, tmp_path):
        """接続していないpeerはoffline"""
        settings = make_settings(tmp_path)
        node = BakuhuNode(settings=settings)
        statuses = node.get_peer_statuses()
        assert all(s["status"] == "offline" for s in statuses)

    def test_is_any_peer_connected_false(self, tmp_path):
        """未接続時はis_any_peer_connectedがFalse"""
        settings = make_settings(tmp_path)
        node = BakuhuNode(settings=settings)
        assert node.is_any_peer_connected() is False


# ------------------------------------------------------------------ #
# 再送キューテスト
# ------------------------------------------------------------------ #

class TestRetryQueue:
    def test_enqueue_push_result(self, tmp_path):
        """TC-RQ-01相当: push_result失敗時にキューへ積む"""
        settings = make_settings(tmp_path)
        node = BakuhuNode(settings=settings)

        node.enqueue_push_result({
            "from_bakuhu": "secondary-a",
            "request_id": "req-rq01",
            "status": "succeeded",
            "summary": "完了",
        })

        pending_path = node._pending_results_path()
        assert pending_path.exists()
        with open(pending_path) as f:
            data = yaml.safe_load(f)
        assert len(data.get("pending", [])) == 1

    def test_enqueue_idempotent(self, tmp_path):
        """TC-RQ-03相当: 同一キーは重複追加されない"""
        settings = make_settings(tmp_path)
        node = BakuhuNode(settings=settings)

        payload = {
            "from_bakuhu": "secondary-a",
            "request_id": "req-rq02",
            "status": "succeeded",
        }
        node.enqueue_push_result(payload)
        node.enqueue_push_result(payload)  # 重複

        pending_path = node._pending_results_path()
        with open(pending_path) as f:
            data = yaml.safe_load(f)
        assert len(data.get("pending", [])) == 1


# ------------------------------------------------------------------ #
# 管理APIテスト
# ------------------------------------------------------------------ #

class TestManagementAPI:
    @pytest.mark.asyncio
    async def test_disconnect(self, tmp_path):
        """TC-MGMT-02相当: disconnect実行"""
        settings = make_settings(tmp_path)
        app = make_app(settings)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # まずピアのシャットダウンイベントを登録
            response = await client.post("/bakuhu/disconnect?peer_id=secondary-a")
        assert response.status_code == 200
        data = response.json()
        assert data["disconnected"] is True

    @pytest.mark.asyncio
    async def test_connect_healthz_failure(self, tmp_path):
        """TC-ERR-01相当: healthz到達不可時のconnect失敗"""
        settings = make_settings(tmp_path)
        app = make_app(settings)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/bakuhu/connect",
                json={
                    "peer_id": "test-peer",
                    "base_url": "http://nonexistent.test:30001",
                    "name": "Test Peer",
                }
            )
        assert response.status_code == 502


# ------------------------------------------------------------------ #
# get_bakuhu_info テスト
# ------------------------------------------------------------------ #

class TestGetBakuhuInfo:
    @pytest.mark.asyncio
    async def test_get_bakuhu_info_returns_required_fields(self, tmp_path):
        """TC-WS-05相当: get_bakuhu_infoの必須フィールド確認"""
        settings = make_settings(tmp_path)
        node = BakuhuNode(settings=settings)
        methods = BakuhuRpcServerMethods(node)

        info = await methods.get_bakuhu_info()
        assert "name" in info
        assert "role" in info
        assert "rpc_connected" in info
        assert info["role"] == "primary"
        assert info["rpc_connected"] is False  # 未接続
