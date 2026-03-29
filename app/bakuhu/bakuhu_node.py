"""BakuhuNode - 幕府間RPC/PubSubノード実装（設計書: protocol_v2.md）"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi_websocket_pubsub import PubSubClient
from fastapi_websocket_rpc import RpcMethodsBase, WebSocketRpcClient

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("bakuhu.audit")

BAKUHU_EVENTS_TOPIC = "bakuhu.events"
MAX_NORMAL_DELAY = 60.0
MAX_AUTH_DELAY = 300.0
DEDUP_TTL_SECONDS = 60
PEERS_CACHE_TTL = 30.0  # 設計書 L363: /bakuhu/peers キャッシュTTL


class AuthConfigError(Exception):
    """認証/設定系エラー（バックオフ分岐用）"""


def _mask_token_url(url: str) -> str:
    """URLの ?token=<value> をマスクして返す"""
    return re.sub(r"(\?token=)[^&\s]+", r"\1***", url)


def _load_accepted_tokens(settings: dict) -> dict[str, str]:
    """accepted_tokensをsettings + 環境変数から構築。衝突時は起動拒否。"""
    bakuhu_cfg = settings.get("bakuhu", {})
    tokens: dict[str, str] = dict(bakuhu_cfg.get("accepted_tokens") or {})

    # 環境変数上書き: BAKUHU_ACCEPTED_TOKENS_<KEY>=<peer_id>
    env_prefix = "BAKUHU_ACCEPTED_TOKENS_"
    env_tokens: dict[
        str, tuple[str, str]
    ] = {}  # normalized_key -> (orig_token, peer_id)

    for orig_token, peer_id in list(tokens.items()):
        norm = re.sub(r"[^A-Z0-9]", "_", str(orig_token).upper())
        env_tokens[norm] = (str(orig_token), str(peer_id))

    # 既存tokenのnorm衝突チェック
    norm_seen: dict[str, str] = {}
    for orig_token in list(tokens.keys()):
        norm = re.sub(r"[^A-Z0-9]", "_", str(orig_token).upper())
        if norm in norm_seen:
            raise RuntimeError(
                f"accepted_tokens key collision: '{norm_seen[norm]}' and '{orig_token}' "
                f"both normalize to '{norm}'. Startup rejected."
            )
        norm_seen[norm] = orig_token

    for key, value in os.environ.items():
        if key.startswith(env_prefix):
            suffix = key[len(env_prefix) :]
            # 環境変数から対応するtokenを探す
            if suffix in env_tokens:
                orig_token, _ = env_tokens[suffix]
                tokens[orig_token] = value
            else:
                # 新規追加（norm keyからtokenを推定できないのでキーそのままで追加）
                # 実用上は設定ファイル側で定義したtokenを上書きするのが主目的
                pass

    return tokens


class BakuhuRpcClientMethods(RpcMethodsBase):
    """Primary側がsecondaryから受け取るcallbackメソッド群"""

    def __init__(self, node: BakuhuNode):
        super().__init__()
        self._node = node

    async def push_result(
        self,
        request_id: str = "",
        summary: str = "",
        status: str = "",
        artifact_path: str = "",
        from_bakuhu: str = "",
        **kwargs: Any,
    ) -> dict:
        """委任結果の返却 (secondary → primary callback)"""
        # バリデーション
        if not request_id or not status:
            logger.warning(
                "[push_result] missing required fields: request_id=%s status=%s",
                request_id,
                status,
            )
            return {"accepted": False, "reason": "missing_required_fields"}

        valid_statuses = {"succeeded", "failed", "expired", "canceled"}
        if status not in valid_statuses:
            logger.warning("[push_result] invalid status: %s", status)
            return {"accepted": False, "reason": "invalid_status"}

        # 重複排除
        dedup_key = f"push_result:{from_bakuhu}:{request_id}:{status}"
        if self._node.is_duplicate(dedup_key):
            logger.debug("[push_result] duplicate suppressed: %s", dedup_key)
            return {"accepted": False, "reason": "duplicate"}

        # primary inboxに永続化
        self._node._persist_to_inbox(
            "shogun",
            {
                "type": "bakuhu_result",
                "request_id": request_id,
                "from_bakuhu": from_bakuhu,
                "summary": summary,
                "status": status,
                "artifact_path": artifact_path,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        # 完了済みとしてマーク（後続の push_status を無視するため）
        self._node.mark_completed(request_id)

        audit_logger.info(
            json.dumps(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "peer_id": from_bakuhu,
                    "action": "push_result",
                    "result": "accepted",
                    "request_id": request_id,
                }
            )
        )

        return {"accepted": True, "request_id": request_id}

    async def push_status(
        self,
        request_id: str = "",
        status: str = "",
        progress: dict | None = None,
        from_bakuhu: str = "",
        **kwargs: Any,
    ) -> dict:
        """状態変更の中間通知 (secondary → primary callback)"""
        valid_statuses = {"validated", "queued", "in_progress"}
        if not request_id or status not in valid_statuses:
            logger.warning(
                "[push_status] invalid: request_id=%s status=%s", request_id, status
            )
            return {"accepted": False, "reason": "invalid_status"}

        # 重複排除
        dedup_key = f"push_status:{from_bakuhu}:{request_id}:{status}"
        if self._node.is_duplicate(dedup_key):
            return {"accepted": False, "reason": "duplicate"}

        # 完了済みの場合は警告
        if self._node.is_completed(request_id):
            audit_logger.warning(
                json.dumps(
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "peer_id": from_bakuhu,
                        "action": "push_status_after_complete",
                        "result": "ignored",
                        "request_id": request_id,
                    }
                )
            )
            return {"accepted": False, "reason": "already_completed"}

        self._node._persist_to_inbox(
            "shogun",
            {
                "type": "bakuhu_status",
                "request_id": request_id,
                "from_bakuhu": from_bakuhu,
                "status": status,
                "progress": progress or {},
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        return {"accepted": True}


class BakuhuRpcServerMethods(RpcMethodsBase):
    """Secondary側が公開するメソッド群（primaryが呼び出す）"""

    def __init__(self, node: BakuhuNode):
        super().__init__()
        self._node = node

    async def submit_delegation(
        self,
        request_id: str = "",
        content: str = "",
        from_bakuhu: str = "",
        priority: str = "normal",
        **kwargs: Any,
    ) -> dict:
        """委任依頼の受付"""
        # channelを保存（push_result再送時に使用）
        if self.channel is not None:
            self._node._incoming_channels[from_bakuhu] = self.channel

        # バリデーション
        if not request_id or not content or not from_bakuhu:
            return {"accepted": False, "reason": "missing_required_fields"}

        valid_priorities = {"high", "normal", "low"}
        if priority not in valid_priorities:
            return {"accepted": False, "reason": f"invalid_priority: {priority}"}

        # TODO(TC-AUTH-07): submit_delegationはprimary peer_idからのみ受付すべき
        # 現在の実装では認可チェック未実装（設計書 L379 の要件が未達）
        # 実際には接続時のトークンで認証済みだが、ロールマッピングが設定仕様にないため
        # peer_id レベルの制限は将来実装とする

        # 冪等性チェック（flock + 複合キー）
        idempotency_key = f"{from_bakuhu}:{request_id}"

        try:
            result = self._node._atomic_write_inbox(
                "shogun",
                idempotency_key,
                {
                    "type": "bakuhu_delegation",
                    "request_id": request_id,
                    "from_bakuhu": from_bakuhu,
                    "content": content,
                    "priority": priority,
                    "read": False,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        except Exception as exc:
            logger.error("[submit_delegation] inbox write error: %s", exc)
            return {"accepted": False, "reason": "internal_error"}

        if not result:
            audit_logger.info(
                json.dumps(
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "peer_id": from_bakuhu,
                        "action": "submit_delegation",
                        "result": "duplicate",
                        "request_id": request_id,
                    }
                )
            )
            return {"accepted": False, "reason": "duplicate"}

        audit_logger.info(
            json.dumps(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "peer_id": from_bakuhu,
                    "action": "submit_delegation",
                    "result": "accepted",
                    "request_id": request_id,
                }
            )
        )

        return {"accepted": True, "request_id": request_id, "status": "received"}

    async def register_peer(
        self,
        from_bakuhu: str = "",
        base_url: str = "",
        **kwargs: Any,
    ) -> dict:
        """primary接続確立時の通知（primaryが呼ぶ）。incoming_channelsに登録する。"""
        if from_bakuhu and self.channel is not None:
            self._node._incoming_channels[from_bakuhu] = self.channel
            self._node.invalidate_peers_cache()
            logger.info(
                "[RPC] registered incoming peer: %s (base_url=%s)",
                from_bakuhu,
                base_url,
            )
        return {"registered": bool(from_bakuhu)}

    async def get_bakuhu_info(self, **kwargs: Any) -> dict:
        """幕府の状態情報取得"""
        cfg = self._node._settings.get("bakuhu", {})
        return {
            "name": cfg.get("name", "unknown"),
            "role": cfg.get("role", "secondary"),
            "rpc_connected": self._node.is_any_peer_connected(),
        }


class BakuhuNode:
    """幕府間RPC/PubSubノード。primaryのみ発呼。"""

    def __init__(self, settings: dict):
        self._settings = settings
        self._shutdown = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        # peer_id -> asyncio.Event (shutdown per-peer)
        self._peer_shutdowns: dict[str, asyncio.Event] = {}
        # peer_id -> {"rpc": bool, "pubsub": bool, "last_seen": float}
        self._peer_status: dict[str, dict] = {}
        # 重複排除キャッシュ: key -> expire_time
        self._dedup_cache: dict[str, float] = {}
        # 完了済みrequest_idキャッシュ
        self._completed: set[str] = set()
        # 再送キュー処理タスク
        self._retry_task: asyncio.Task | None = None
        # /bakuhu/peers キャッシュ（TTL 30秒: 設計書 L363）
        self._peers_cache_time: float = 0.0
        self._peers_cache_data: list[dict] = []

        # peer_id -> WebSocketRpcClient（接続中のみ格納）
        self._rpc_clients: dict[str, Any] = {}
        # from_bakuhu (peer_id) -> incoming RPC channel（secondaryがcallbackに使用）
        self._incoming_channels: dict[str, Any] = {}

        # accepted_tokensをロード（起動時衝突チェック）
        self._accepted_tokens = _load_accepted_tokens(settings)

    # ------------------------------------------------------------------ #
    # 起動・停止
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        """起動: primaryの場合、全peerへの接続を開始"""
        cfg = self._settings.get("bakuhu", {})
        role = cfg.get("role", "secondary")
        peers = cfg.get("peers") or []

        if role == "primary":
            for peer in peers:
                peer_id = peer.get("id", "")
                if not peer_id:
                    continue
                ev = asyncio.Event()
                self._peer_shutdowns[peer_id] = ev
                self._peer_status[peer_id] = {
                    "rpc": False,
                    "pubsub": False,
                    "last_seen": 0.0,
                }

                t1 = asyncio.create_task(self.maintain_rpc_client(peer_id, peer, ev))
                t2 = asyncio.create_task(self.maintain_pubsub_client(peer_id, peer, ev))
                self._tasks.extend([t1, t2])

        self._retry_task = asyncio.create_task(self._process_retry_queue())
        logger.info("[BakuhuNode] started (role=%s, peers=%d)", role, len(peers))

    async def stop(self) -> None:
        """停止"""
        self._shutdown.set()
        for ev in self._peer_shutdowns.values():
            ev.set()

        all_tasks = self._tasks[:]
        if self._retry_task:
            all_tasks.append(self._retry_task)

        for t in all_tasks:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        logger.info("[BakuhuNode] stopped")

    # ------------------------------------------------------------------ #
    # 接続管理（primaryのみ発呼）
    # ------------------------------------------------------------------ #

    async def maintain_rpc_client(
        self, peer_id: str, peer_config: dict, shutdown_event: asyncio.Event
    ) -> None:
        """RPC接続の維持（指数バックオフ）"""
        cfg = self._settings.get("bakuhu", {})
        outbound_token = cfg.get("outbound_token", "changeme")
        base_url = peer_config.get("base_url", "")
        rpc_url = f"ws://{base_url.rstrip('/').replace('http://', '').replace('https://', '')}/bakuhu/ws/rpc?token={outbound_token}"

        delay = 2.0

        while not shutdown_event.is_set() and not self._shutdown.is_set():
            masked_url = _mask_token_url(rpc_url)
            try:
                logger.info("[RPC] connecting to %s (peer=%s)", masked_url, peer_id)
                async with WebSocketRpcClient(
                    rpc_url,
                    BakuhuRpcClientMethods(self),
                    retry_config=False,
                    keep_alive=20,
                    open_timeout=3,
                ) as client:
                    self._rpc_clients[peer_id] = client
                    self._peer_status[peer_id]["rpc"] = True
                    self._peer_status[peer_id]["last_seen"] = time.monotonic()
                    delay = 2.0  # 接続成功でリセット
                    logger.info("[RPC] connected to peer=%s", peer_id)
                    audit_logger.info(
                        json.dumps(
                            {
                                "timestamp": datetime.now(UTC).isoformat(),
                                "action": "rpc_client_connected",
                                "peer_id": peer_id,
                            }
                        )
                    )
                    # secondaryにpeer登録通知（secondary側でincoming_channelsに登録させる）
                    _my_cfg = self._settings.get("bakuhu", {})
                    _my_name = _my_cfg.get("name", "")
                    if _my_name:
                        try:
                            await client.other.register_peer(
                                from_bakuhu=_my_name, base_url=base_url
                            )
                        except Exception as _e:
                            logger.warning(
                                "[RPC] register_peer failed for peer=%s: %s",
                                peer_id,
                                _e,
                            )
                    try:
                        await client.wait_on_reader()
                    finally:
                        self._rpc_clients.pop(peer_id, None)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                is_auth_error = self._is_auth_error(exc)
                logger.warning("[RPC] disconnected from peer=%s: %s", peer_id, exc)
                audit_logger.info(
                    json.dumps(
                        {
                            "timestamp": datetime.now(UTC).isoformat(),
                            "action": "rpc_client_disconnected",
                            "peer_id": peer_id,
                        }
                    )
                )
                self._peer_status[peer_id]["rpc"] = False

                if is_auth_error:
                    delay = min(max(delay, 10.0) * 2, MAX_AUTH_DELAY)
                else:
                    delay = min(delay * 2, MAX_NORMAL_DELAY)

            if not shutdown_event.is_set() and not self._shutdown.is_set():
                await asyncio.sleep(delay)

    async def maintain_pubsub_client(
        self, peer_id: str, peer_config: dict, shutdown_event: asyncio.Event
    ) -> None:
        """PubSub接続の維持（指数バックオフ + 再購読）"""
        cfg = self._settings.get("bakuhu", {})
        outbound_token = cfg.get("outbound_token", "changeme")
        base_url = peer_config.get("base_url", "")
        pubsub_url = f"ws://{base_url.rstrip('/').replace('http://', '').replace('https://', '')}/bakuhu/ws/pubsub?token={outbound_token}"

        delay = 2.0
        auth_delay = 10.0

        while not shutdown_event.is_set() and not self._shutdown.is_set():
            masked_url = _mask_token_url(pubsub_url)
            try:
                logger.info("[PubSub] connecting to %s (peer=%s)", masked_url, peer_id)
                async with PubSubClient(server_uri=pubsub_url) as client:
                    await client.subscribe(BAKUHU_EVENTS_TOPIC, self._on_event)
                    self._peer_status[peer_id]["pubsub"] = True
                    delay = 2.0  # 接続成功でリセット
                    logger.info("[PubSub] connected and subscribed to peer=%s", peer_id)
                    await client.wait_until_done()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                is_auth = self._is_auth_error(exc)
                self._peer_status[peer_id]["pubsub"] = False
                logger.warning("[PubSub] disconnected from peer=%s: %s", peer_id, exc)

                if is_auth:
                    delay = min(max(delay, auth_delay) * 2, MAX_AUTH_DELAY)
                else:
                    delay = min(delay * 2, MAX_NORMAL_DELAY)

            if not shutdown_event.is_set() and not self._shutdown.is_set():
                await asyncio.sleep(delay)

    # ------------------------------------------------------------------ #
    # 委任（primary → secondary）
    # ------------------------------------------------------------------ #

    async def delegate(
        self,
        peer_id: str,
        instruction: str,
        request_id: str | None = None,
        priority: str = "normal",
    ) -> dict:
        """primaryからsecondaryへ委任依頼（RPC呼び出し）"""
        client = self._rpc_clients.get(peer_id)
        if client is None:
            raise RuntimeError(f"peer {peer_id!r} not connected")
        cfg = self._settings.get("bakuhu", {})
        my_name = cfg.get("name", "primary-bakuhu")
        if not request_id:
            request_id = f"req_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}_{peer_id}"
        audit_logger.info(
            json.dumps(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "action": "delegate_initiated",
                    "target_peer": peer_id,
                    "request_id": request_id,
                }
            )
        )
        result = await client.other.submit_delegation(
            request_id=request_id,
            content=instruction,
            from_bakuhu=my_name,
            priority=priority,
        )
        return result

    # ------------------------------------------------------------------ #
    # PubSubイベント受信
    # ------------------------------------------------------------------ #

    async def _on_event(
        self, data: dict | str, topic: str = BAKUHU_EVENTS_TOPIC
    ) -> None:
        """PubSubイベント受信ハンドラ"""
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return

        request_id = data.get("request_id", "")
        from_bakuhu = data.get("from_bakuhu", "")
        status = data.get("status", "")

        # 重複排除
        dedup_key = f"pubsub:{from_bakuhu}:{request_id}:{status}"
        if self.is_duplicate(dedup_key):
            logger.debug("[PubSub] duplicate event suppressed: %s", dedup_key)
            return

        logger.info("[PubSub] event received: %s", data)

    # ------------------------------------------------------------------ #
    # push_result再送キュー
    # ------------------------------------------------------------------ #

    async def _process_retry_queue(self) -> None:
        """接続回復後に pending_results.yaml から再送"""
        while not self._shutdown.is_set():
            try:
                await asyncio.sleep(10)
                await self._flush_retry_queue()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("[RetryQueue] error: %s", exc)

    async def _flush_retry_queue(self) -> None:
        """再送キューから送信を試みる"""
        pending_path = self._pending_results_path()
        if not pending_path.exists():
            return

        # Read under flock（enqueue_push_result と同じ a+ パターン）
        with open(pending_path, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                data = yaml.safe_load(f) or {}
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

        pending = data.get("pending", [])
        if not pending:
            return

        remaining = []
        for item in pending:
            from_bakuhu = item.get("from_bakuhu", "")
            channel = self._incoming_channels.get(from_bakuhu)
            if channel is None:
                remaining.append(item)
                continue
            # 冪等チェック
            idem_key = f"{from_bakuhu}:{item.get('request_id')}:{item.get('status')}"
            if self.is_duplicate(idem_key):
                continue  # 既送信 → 削除対象
            try:
                await channel.other.push_result(
                    request_id=item.get("request_id", ""),
                    summary=item.get("summary", ""),
                    status=item.get("status", ""),
                    artifact_path=item.get("artifact_path", ""),
                    from_bakuhu=from_bakuhu,
                )
                logger.info("[RetryQueue] re-sent: %s", idem_key)
            except Exception as exc:
                logger.warning("[RetryQueue] retry failed: %s: %s", idem_key, exc)
                remaining.append(item)

        # pending_results.yaml を更新（flock使用: enqueue_push_result と同パターン）
        with open(pending_path, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                f.truncate()
                yaml.safe_dump({"pending": remaining}, f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def enqueue_push_result(self, payload: dict) -> None:
        """push_result失敗時にローカル永続キューへ積む"""
        pending_path = self._pending_results_path()
        pending_path.parent.mkdir(parents=True, exist_ok=True)

        # 冪等キー
        idem_key = f"{payload.get('from_bakuhu')}:{payload.get('request_id')}:{payload.get('status')}"

        # _atomic_write_inbox() と同じパターン: 単一flockスコープで read→加工→write を完結させる
        with open(pending_path, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                try:
                    data = yaml.safe_load(f) or {}
                except yaml.YAMLError:
                    data = {}

                pending = data.get("pending", [])
                for item in pending:
                    if item.get("idempotency_key") == idem_key:
                        return  # 重複

                pending.append({"idempotency_key": idem_key, **payload})
                data["pending"] = pending

                f.seek(0)
                f.truncate()
                yaml.dump(data, f, allow_unicode=True)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    # ------------------------------------------------------------------ #
    # ユーティリティ
    # ------------------------------------------------------------------ #

    def is_duplicate(self, key: str) -> bool:
        """重複排除キャッシュチェック（TTL 60秒）"""
        now = time.time()
        # 期限切れエントリをクリーンアップ
        expired = [k for k, exp in self._dedup_cache.items() if now > exp]
        for k in expired:
            del self._dedup_cache[k]

        if key in self._dedup_cache:
            return True
        self._dedup_cache[key] = now + DEDUP_TTL_SECONDS
        return False

    def is_completed(self, request_id: str) -> bool:
        return request_id in self._completed

    def mark_completed(self, request_id: str) -> None:
        self._completed.add(request_id)

    def is_any_peer_connected(self) -> bool:
        return any(s.get("rpc") for s in self._peer_status.values())

    def get_peer_statuses(self) -> list[dict]:
        """peer状態一覧を返す（TTL 30秒キャッシュ: 設計書 L363）"""
        now = time.monotonic()
        if now - self._peers_cache_time < PEERS_CACHE_TTL and self._peers_cache_data:
            return list(self._peers_cache_data)

        cfg = self._settings.get("bakuhu", {})
        peers = cfg.get("peers") or []
        role = cfg.get("role", "secondary")  # ループ前に移動
        result = []
        for peer in peers:
            peer_id = peer.get("id", "")
            status = self._peer_status.get(peer_id, {})
            rpc_ok = status.get("rpc", False)
            # secondary roleの場合: _incoming_channelsにactive channelがあればonline
            if not rpc_ok and role != "primary":
                inc_channel = self._incoming_channels.get(peer_id)
                if inc_channel is not None and not inc_channel.isClosed():
                    rpc_ok = True
            result.append(
                {
                    "id": peer_id,
                    "name": peer.get("name", peer_id),
                    "base_url": peer.get("base_url", ""),
                    "status": "online" if rpc_ok else "offline",
                    "rpc_connected": rpc_ok,
                    "pubsub_connected": status.get("pubsub", False),
                }
            )
        # secondary向け: incoming_rpc_channelsに登録されたprimary接続も表示
        # （設計書 protocol_v2.md L454: SNodeはincoming_rpc_channelsにchannelを登録）
        # ※ roleは上で定義済み
        if role != "primary":
            existing_ids = {r["id"] for r in result}
            stale_keys = []
            for from_bakuhu, channel in list(self._incoming_channels.items()):
                if channel.isClosed():
                    stale_keys.append(from_bakuhu)
                    continue
                if from_bakuhu not in existing_ids:
                    inc_status = self._peer_status.get(from_bakuhu, {})
                    result.append(
                        {
                            "id": from_bakuhu,
                            "name": from_bakuhu,
                            "base_url": "",
                            "status": "online",
                            "rpc_connected": True,
                            "pubsub_connected": inc_status.get("pubsub", False),
                        }
                    )
            for key in stale_keys:
                del self._incoming_channels[key]

        self._peers_cache_time = now
        self._peers_cache_data = list(result)
        return result

    def invalidate_peers_cache(self) -> None:
        """peers キャッシュを明示的に無効化する（状態変化時に呼ぶ）"""
        self._peers_cache_time = 0.0
        self._peers_cache_data = []

    def _is_auth_error(self, exc: Exception) -> bool:
        """認証/設定系エラーか判定"""
        msg = str(exc).lower()
        return any(
            kw in msg for kw in ["401", "403", "unauthorized", "forbidden", "auth"]
        )

    # ------------------------------------------------------------------ #
    # 永続化
    # ------------------------------------------------------------------ #

    def _get_base_path(self) -> Path:
        cfg = self._settings.get("bakuhu", {})
        _base = cfg.get("base_path")
        if not _base:
            raise ValueError(
                "bakuhu.base_path is required in settings.yaml "
                "(absolute path to the multi-agent-bakuhu repository)"
            )
        return Path(_base)

    def _inbox_path(self, agent: str) -> Path:
        return self._get_base_path() / "queue" / "inbox" / f"{agent}.yaml"

    def _pending_results_path(self) -> Path:
        return self._get_base_path() / "queue" / "cross_bakuhu" / "pending_results.yaml"

    def _persist_to_inbox(self, agent: str, entry: dict) -> None:
        """inboxに非原子的書き込み（push_result/push_status用）"""
        inbox_path = self._inbox_path(agent)
        inbox_path.parent.mkdir(parents=True, exist_ok=True)

        with open(inbox_path, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                try:
                    data = yaml.safe_load(f) or {}
                except yaml.YAMLError:
                    data = {}
                messages = data.get("messages") or []
                messages.append(entry)
                data["messages"] = messages
                f.seek(0)
                f.truncate()
                yaml.dump(data, f, allow_unicode=True)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def _atomic_write_inbox(
        self, agent: str, idempotency_key: str, entry: dict
    ) -> bool:
        """flockによる原子的inbox書き込み。重複時はFalseを返す。"""
        inbox_path = self._inbox_path(agent)
        inbox_path.parent.mkdir(parents=True, exist_ok=True)

        with open(inbox_path, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                try:
                    data = yaml.safe_load(f) or {}
                except yaml.YAMLError:
                    data = {}

                messages = data.get("messages") or []

                # 複合キー重複チェック
                for msg in messages:
                    if msg.get("_idempotency_key") == idempotency_key:
                        return False

                entry["_idempotency_key"] = idempotency_key
                messages.append(entry)
                data["messages"] = messages

                f.seek(0)
                f.truncate()
                yaml.dump(data, f, allow_unicode=True)
                return True
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
