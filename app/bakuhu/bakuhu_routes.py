"""bakuhu_routes.py - 幕府間連携APIルーター（設計書: protocol_v2.md）"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import httpx
import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketException, status
from fastapi_websocket_pubsub import PubSubEndpoint
from fastapi_websocket_rpc import WebsocketRPCEndpoint
from pydantic import BaseModel

from .bakuhu_node import BakuhuNode, BakuhuRpcServerMethods, audit_logger, _mask_token_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bakuhu", tags=["bakuhu"])

MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200MB

# ------------------------------------------------------------------ #
# 認証ユーティリティ
# ------------------------------------------------------------------ #

def _get_node(websocket_or_request) -> BakuhuNode:
    """app.stateからBakuhuNodeを取得"""
    try:
        return websocket_or_request.app.state.bakuhu_node
    except AttributeError as exc:
        raise RuntimeError("BakuhuNode not initialized") from exc


def _authenticate_token(token: str, settings: dict) -> str | None:
    """tokenをaccepted_tokensで検証し、peer_idを返す。無効な場合はNone。"""
    bakuhu_cfg = settings.get("bakuhu", {})
    accepted = dict(bakuhu_cfg.get("accepted_tokens") or {})
    return accepted.get(token)


def _validate_token_ws(token: str | None, settings: dict) -> str:
    """WebSocket用トークン検証。失敗時はWebSocketException(4003)。"""
    if not token:
        raise WebSocketException(code=4003, reason="missing token")
    peer_id = _authenticate_token(token, settings)
    if peer_id is None:
        raise WebSocketException(code=4003, reason="invalid token")
    return peer_id


# ------------------------------------------------------------------ #
# ヘルスチェック
# ------------------------------------------------------------------ #

@router.get("/healthz")
async def healthz():
    """到達確認（初回接続時のみ使用）"""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ------------------------------------------------------------------ #
# Peer管理
# ------------------------------------------------------------------ #

class ConnectRequest(BaseModel):
    peer_id: str
    base_url: str
    name: str = ""
    token: str = ""


@router.post("/connect")
async def bakuhu_connect(request: Request, body: ConnectRequest, token: str = Query(default="")):
    """peer登録（primaryへの従属申請。primaryからのみ実行可能）"""
    node: BakuhuNode = _get_node(request)
    settings = request.app.state.settings

    # 認証（UIからのtoken、または直接API呼び出しのtoken）
    if token:
        peer_id = _authenticate_token(token, settings)
        if peer_id is None:
            raise HTTPException(status_code=403, detail="invalid token")
        # secondary からの逆方向接続は禁止
        cfg = settings.get("bakuhu", {})
        role = cfg.get("role", "secondary")
        if role == "secondary":
            raise HTTPException(status_code=403, detail="secondary cannot call connect")

    # healthzで到達確認
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{body.base_url.rstrip('/')}/bakuhu/healthz")
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail="healthz failed")
    except httpx.TimeoutException:
        raise HTTPException(status_code=502, detail="healthz timeout")
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"healthz unreachable: {exc}")

    # peerをsettings + nodeに登録（実行時のみ。永続化はsettings.yaml書き込みが必要な場合は別途）
    cfg = settings.get("bakuhu", {})
    peers = list(cfg.get("peers") or [])

    # 冪等: 既存peer_idがあれば更新
    existing = next((p for p in peers if p.get("id") == body.peer_id), None)
    if existing:
        existing["base_url"] = body.base_url
        if body.name:
            existing["name"] = body.name
    else:
        peers.append({"id": body.peer_id, "name": body.name or body.peer_id, "base_url": body.base_url})

    cfg["peers"] = peers
    settings["bakuhu"] = cfg

    # maintain_rpc_client/maintain_pubsub_clientを動的に起動
    if body.peer_id not in node._peer_shutdowns:
        import asyncio
        ev = asyncio.Event()
        node._peer_shutdowns[body.peer_id] = ev
        node._peer_status[body.peer_id] = {"rpc": False, "pubsub": False, "last_seen": 0.0}

        peer_config = {"id": body.peer_id, "base_url": body.base_url, "name": body.name}
        t1 = asyncio.create_task(node.maintain_rpc_client(body.peer_id, peer_config, ev))
        t2 = asyncio.create_task(node.maintain_pubsub_client(body.peer_id, peer_config, ev))
        node._tasks.extend([t1, t2])

    audit_logger.info(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "peer_id": body.peer_id,
        "action": "connect",
        "result": "accepted",
    }))

    return {"connected": True, "peer": body.peer_id}


@router.post("/disconnect")
async def bakuhu_disconnect(request: Request, peer_id: str = Query(...), token: str = Query(default="")):
    """peer解除"""
    node: BakuhuNode = _get_node(request)

    if token:
        settings = request.app.state.settings
        auth_peer = _authenticate_token(token, settings)
        if auth_peer is None:
            raise HTTPException(status_code=403, detail="invalid token")

    ev = node._peer_shutdowns.get(peer_id)
    if ev:
        ev.set()
        del node._peer_shutdowns[peer_id]
        if peer_id in node._peer_status:
            node._peer_status[peer_id]["rpc"] = False
            node._peer_status[peer_id]["pubsub"] = False

    return {"disconnected": True, "peer_id": peer_id}


@router.get("/peers")
async def bakuhu_peers(request: Request):
    """peer一覧（RPC接続状態含む）"""
    node: BakuhuNode = _get_node(request)
    return {"peers": node.get_peer_statuses()}


# ------------------------------------------------------------------ #
# ファイル転送
# ------------------------------------------------------------------ #

@router.post("/files")
async def bakuhu_files(
    request: Request,
    file: UploadFile,
    request_id: str = Query(...),
    from_bakuhu: str = Query(...),
    token: str = Query(default=""),
):
    """ファイル受信（multipart/form-data, 200MB上限）"""
    settings = request.app.state.settings

    # 認証
    if token:
        peer_id = _authenticate_token(token, settings)
        if peer_id is None:
            raise HTTPException(status_code=403, detail="invalid token")
        # from_bakuhu整合チェック
        if peer_id != from_bakuhu:
            raise HTTPException(
                status_code=422,
                detail={"error": "peer_mismatch", "detail": f"token resolves to {peer_id}, not {from_bakuhu}"}
            )

    # ファイル名サニタイズ
    safe_name = os.path.basename(file.filename or "upload.bin")
    if not safe_name or safe_name in (".", ".."):
        safe_name = "upload.bin"

    ext = Path(safe_name).suffix
    save_name = f"tenshukaku_upload_{uuid.uuid4()}{ext}"

    # upload_dir取得
    cfg = settings.get("bakuhu", {})
    base_path = Path(cfg.get("base_path", "/home/quieter/projects/multi-agent-bakuhu"))
    upload_dir_rel = cfg.get("upload_dir", "queue/cross_bakuhu/files")
    upload_dir = base_path / upload_dir_rel
    upload_dir.mkdir(parents=True, exist_ok=True)

    save_path = upload_dir / save_name
    # パストラバーサル防止
    if not str(save_path.resolve()).startswith(str(upload_dir.resolve())):
        raise HTTPException(status_code=422, detail={"error": "path_traversal", "detail": "invalid path"})

    # サイズチェックしながら保存
    node: BakuhuNode = _get_node(request)
    try:
        total = 0
        with open(save_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    f.close()
                    save_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=422,
                        detail={"error": "size_exceeded", "detail": f"file exceeds 200MB limit"}
                    )
                f.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        save_path.unlink(missing_ok=True)
        # push_result失敗通知をキューへ
        node.enqueue_push_result({
            "from_bakuhu": from_bakuhu,
            "request_id": request_id,
            "status": "failed",
            "error_detail": "file_save_error",
        })
        raise HTTPException(
            status_code=500,
            detail={"error": "file_save_error", "detail": str(exc)}
        )

    return {
        "status": "saved",
        "artifact_path": str(save_path),
        "request_id": request_id,
        "from_bakuhu": from_bakuhu,
        "size_bytes": total,
    }


# ------------------------------------------------------------------ #
# WebSocket エンドポイント
# ------------------------------------------------------------------ #

# RPCエンドポイント（サーバ側: secondaryが公開するメソッドを提供）
_rpc_endpoint: WebsocketRPCEndpoint | None = None
_pubsub_endpoint: PubSubEndpoint | None = None


def get_rpc_endpoint(node: BakuhuNode) -> WebsocketRPCEndpoint:
    global _rpc_endpoint
    if _rpc_endpoint is None:
        _rpc_endpoint = WebsocketRPCEndpoint(BakuhuRpcServerMethods(node))
    return _rpc_endpoint


def get_pubsub_endpoint() -> PubSubEndpoint:
    global _pubsub_endpoint
    if _pubsub_endpoint is None:
        _pubsub_endpoint = PubSubEndpoint()
    return _pubsub_endpoint


@router.websocket("/ws/rpc")
async def bakuhu_ws_rpc(websocket: WebSocket, token: str = Query(default="")):
    """WebSocket RPC エンドポイント（fastapi-websocket-rpc）"""
    settings = websocket.app.state.settings
    peer_id = _validate_token_ws(token, settings)

    node: BakuhuNode = _get_node(websocket)

    audit_logger.info(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "peer_id": peer_id,
        "action": "rpc_connect",
        "result": "accepted",
    }))

    endpoint = get_rpc_endpoint(node)
    await endpoint.main_loop(websocket)


@router.websocket("/ws/pubsub")
async def bakuhu_ws_pubsub(websocket: WebSocket, token: str = Query(default="")):
    """WebSocket PubSub エンドポイント（fastapi-websocket-pubsub）"""
    settings = websocket.app.state.settings
    peer_id = _validate_token_ws(token, settings)

    audit_logger.info(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "peer_id": peer_id,
        "action": "pubsub_connect",
        "result": "accepted",
    }))

    endpoint = get_pubsub_endpoint()
    await endpoint.main_loop(websocket)
