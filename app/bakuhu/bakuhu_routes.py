"""bakuhu_routes.py - 幕府間連携APIルーター（設計書: protocol_v2.md）"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketException,
)
from fastapi_websocket_pubsub import PubSubEndpoint
from fastapi_websocket_rpc import WebsocketRPCEndpoint
from pydantic import BaseModel

from .bakuhu_node import (
    BakuhuNode,
    BakuhuRpcServerMethods,
    audit_logger,
)

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


def _authenticate_token(token: str, accepted_tokens: dict) -> str | None:
    """tokenをaccepted_tokensで検証し、peer_idを返す。無効な場合はNone。"""
    return accepted_tokens.get(token)


def _validate_token_ws(token: str | None, accepted_tokens: dict) -> str:
    """WebSocket用トークン検証。失敗時はWebSocketException(4003)。"""
    if not token:
        raise WebSocketException(code=4003, reason="missing token")
    peer_id = _authenticate_token(token, accepted_tokens)
    if peer_id is None:
        raise WebSocketException(code=4003, reason="invalid token")
    return peer_id


# ------------------------------------------------------------------ #
# ヘルスチェック
# ------------------------------------------------------------------ #


@router.get("/healthz")
async def healthz():
    """到達確認（初回接続時のみ使用）"""
    return {"status": "ok", "timestamp": datetime.now(UTC).isoformat()}


# ------------------------------------------------------------------ #
# Peer管理
# ------------------------------------------------------------------ #


class ConnectRequest(BaseModel):
    peer_id: str
    base_url: str
    name: str = ""
    token: str = ""


@router.post("/connect")
async def bakuhu_connect(
    request: Request, body: ConnectRequest, token: str = Query(default="")
):
    """peer登録（primaryへの従属申請。primaryからのみ実行可能）"""
    node: BakuhuNode = _get_node(request)
    settings = request.app.state.settings

    # 認証（UIからのtoken、または直接API呼び出しのtoken）
    if token:
        peer_id = _authenticate_token(token, node._accepted_tokens)
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
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=502, detail="healthz timeout") from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502, detail=f"healthz unreachable: {exc}"
        ) from exc

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
        peers.append(
            {
                "id": body.peer_id,
                "name": body.name or body.peer_id,
                "base_url": body.base_url,
            }
        )

    cfg["peers"] = peers
    settings["bakuhu"] = cfg

    # maintain_rpc_client/maintain_pubsub_clientを動的に起動
    if body.peer_id not in node._peer_shutdowns:
        import asyncio

        ev = asyncio.Event()
        node._peer_shutdowns[body.peer_id] = ev
        node._peer_status[body.peer_id] = {
            "rpc": False,
            "pubsub": False,
            "last_seen": 0.0,
        }

        peer_config = {"id": body.peer_id, "base_url": body.base_url, "name": body.name}
        t1 = asyncio.create_task(
            node.maintain_rpc_client(body.peer_id, peer_config, ev)
        )
        t2 = asyncio.create_task(
            node.maintain_pubsub_client(body.peer_id, peer_config, ev)
        )
        node._tasks.extend([t1, t2])

    audit_logger.info(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "peer_id": body.peer_id,
                "action": "connect",
                "result": "accepted",
            }
        )
    )

    return {"connected": True, "peer": body.peer_id}


@router.post("/disconnect")
async def bakuhu_disconnect(
    request: Request, peer_id: str = Query(...), token: str = Query(default="")
):
    """peer解除"""
    node: BakuhuNode = _get_node(request)

    if not token:
        raise HTTPException(status_code=403, detail="missing token")
    auth_peer = _authenticate_token(token, node._accepted_tokens)
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
async def bakuhu_peers(request: Request, token: str = Query(default="")):
    """peer一覧（RPC接続状態含む）"""
    node: BakuhuNode = _get_node(request)
    if not token:
        raise HTTPException(status_code=403, detail="missing token")
    if _authenticate_token(token, node._accepted_tokens) is None:
        raise HTTPException(status_code=403, detail="invalid token")
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
    node: BakuhuNode = _get_node(request)

    # 認証（token必須）
    if not token:
        raise HTTPException(status_code=403, detail="missing token")
    peer_id = _authenticate_token(token, node._accepted_tokens)
    if peer_id is None:
        raise HTTPException(status_code=403, detail="invalid token")
    # from_bakuhu整合チェック
    if peer_id != from_bakuhu:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "peer_mismatch",
                    "detail": f"token resolves to {peer_id}, not {from_bakuhu}",
                },
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
        raise HTTPException(
            status_code=422,
            detail={"error": "path_traversal", "detail": "invalid path"},
        )

    # サイズチェックしながら保存
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
                        detail={
                            "error": "size_exceeded",
                            "detail": "file exceeds 200MB limit",
                        },
                    )
                f.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        save_path.unlink(missing_ok=True)
        # push_result失敗通知をキューへ
        node.enqueue_push_result(
            {
                "from_bakuhu": from_bakuhu,
                "request_id": request_id,
                "status": "failed",
                "error_detail": "file_save_error",
            }
        )
        raise HTTPException(
            status_code=500, detail={"error": "file_save_error", "detail": str(exc)}
        ) from exc

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


# _get_rpc_endpoint は bakuhu_ws_rpc() がper-connection endpointに移行したため不使用
# def _get_rpc_endpoint(request_or_ws) -> WebsocketRPCEndpoint:


def _get_pubsub_endpoint(request_or_ws) -> PubSubEndpoint:
    """app.stateからPubSubエンドポイントを取得。未初期化なら生成してキャッシュする。"""
    app = request_or_ws.app
    endpoint = getattr(app.state, "bakuhu_pubsub_endpoint", None)
    if endpoint is None:
        endpoint = PubSubEndpoint()
        app.state.bakuhu_pubsub_endpoint = endpoint
    return endpoint


@router.websocket("/ws/rpc")
async def bakuhu_ws_rpc(websocket: WebSocket, token: str = Query(default="")):
    """WebSocket RPC エンドポイント（fastapi-websocket-rpc）"""
    node = _get_node(websocket)
    peer_id = _validate_token_ws(token, node._accepted_tokens)

    audit_logger.info(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "peer_id": peer_id,
                "action": "rpc_connect",
                "result": "accepted",
            }
        )
    )

    async def _on_rpc_connect(channel, **kwargs):
        """incoming RPC接続確立時にpeer_idとchannelを_incoming_channelsに登録"""
        node._incoming_channels[peer_id] = channel
        node.invalidate_peers_cache()
        logger.info("[RPC] server-side incoming registered: peer=%s", peer_id)

    async def _on_rpc_disconnect(channel, **kwargs):
        """切断時にincoming_channelsから削除"""
        node._incoming_channels.pop(peer_id, None)
        node.invalidate_peers_cache()
        logger.info("[RPC] server-side incoming removed: peer=%s", peer_id)

    endpoint = WebsocketRPCEndpoint(
        BakuhuRpcServerMethods(node),
        on_connect=[_on_rpc_connect],
        on_disconnect=[_on_rpc_disconnect],
    )
    await endpoint.main_loop(websocket)


@router.websocket("/ws/pubsub")
async def bakuhu_ws_pubsub(websocket: WebSocket, token: str = Query(default="")):
    """WebSocket PubSub エンドポイント（fastapi-websocket-pubsub）"""
    node = _get_node(websocket)
    peer_id = _validate_token_ws(token, node._accepted_tokens)

    audit_logger.info(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "peer_id": peer_id,
                "action": "pubsub_connect",
                "result": "accepted",
            }
        )
    )

    # PubSub接続確立: secondary側でpeer_statusのpubsubフラグを更新
    node._peer_status.setdefault(peer_id, {})["pubsub"] = True
    node.invalidate_peers_cache()
    logger.info("[PubSub] incoming peer connected: %s", peer_id)

    endpoint = _get_pubsub_endpoint(websocket)
    try:
        await endpoint.main_loop(websocket)
    finally:
        node._peer_status.setdefault(peer_id, {})["pubsub"] = False
        node.invalidate_peers_cache()
        logger.info("[PubSub] incoming peer disconnected: %s", peer_id)
