import asyncio
import base64
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import uvicorn
import yaml
from fastapi import FastAPI, Form, HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import escape
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

from ws.broadcasters import AdaptivePoller, MonitorBroadcaster, ShogunBroadcaster
from ws.handlers import MonitorWebSocketHandler, WebSocketHandler
from ws.runtime import TmuxRuntime
from ws.tmux_bridge import TmuxBridge


# ── File-paste constants & helpers ──────────────────────────────────────────
IMAGE_SAVE_DIR = "/tmp/tenshukaku-images"
IMAGE_MAX_FILES = 50
IMAGE_TTL_SECONDS = 30 * 60  # 30 minutes

_MIME_TO_EXT = {
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/gif": "gif",
    "image/webp": "webp",
}


def _get_file_ext(mime_type: str, file_name: str) -> str:
    if mime_type in _MIME_TO_EXT:
        return _MIME_TO_EXT[mime_type]
    ext = os.path.splitext(file_name)[1].lstrip(".")
    ext = re.sub(r"[^a-zA-Z0-9]", "", ext)
    return ext.lower() if ext else "bin"


def _build_save_path(ext: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    hash8 = str(uuid.uuid4()).replace("-", "")[:8]
    filename = f"tenshukaku_{timestamp}_{hash8}.{ext}"
    path = os.path.join(IMAGE_SAVE_DIR, filename)
    resolved = os.path.realpath(path)
    save_dir_real = os.path.realpath(IMAGE_SAVE_DIR) + os.sep
    if not resolved.startswith(save_dir_real):
        raise ValueError(f"Path traversal detected: {resolved}")
    return resolved


def _init_image_save_dir() -> None:
    os.makedirs(IMAGE_SAVE_DIR, exist_ok=True)
    os.chmod(IMAGE_SAVE_DIR, 0o700)
    for f in Path(IMAGE_SAVE_DIR).glob("tenshukaku_*"):
        try:
            f.unlink()
        except OSError:
            pass
    logger.info("[IMAGE-SAVE] initialized %s, old files removed", IMAGE_SAVE_DIR)


def _cleanup_old_images() -> None:
    now = datetime.now().timestamp()
    save_dir = Path(IMAGE_SAVE_DIR)
    files = sorted(save_dir.glob("tenshukaku_*"), key=lambda p: p.stat().st_mtime)
    for f in files:
        try:
            if now - f.stat().st_mtime > IMAGE_TTL_SECONDS:
                f.unlink()
        except OSError:
            pass
    remaining = sorted(save_dir.glob("tenshukaku_*"), key=lambda p: p.stat().st_mtime)
    while len(remaining) > IMAGE_MAX_FILES:
        try:
            remaining.pop(0).unlink()
        except OSError:
            remaining.pop(0)


async def _periodic_cleanup() -> None:
    while True:
        await asyncio.sleep(5 * 60)
        try:
            _cleanup_old_images()
        except Exception as exc:
            logger.warning("[IMAGE-CLEANUP] error: %s", exc)


_TARGET_RE = re.compile(r"^[A-Za-z0-9_-]+:\d+\.\d+$")


def _build_allowed_targets(settings: dict) -> set[str]:
    tmux = settings.get("tmux", {})
    allowed = set()
    session = tmux.get("shogun_session", "shogun")
    pane = tmux.get("shogun_pane", "0.0")
    allowed.add(f"{session}:{pane}")
    return allowed


# ── Pydantic models ──────────────────────────────────────────────────────────
class FilePasteRequest(BaseModel):
    target: str = ""
    file_b64: str
    file_name: str = "file.bin"
    file_size: int = 0
    mime_type: str = "application/octet-stream"
    message_prefix: str = ""


class ImagePasteRequest(BaseModel):
    """Backward-compatible alias for FilePasteRequest."""
    target: str = ""
    image_b64: str
    file_name: str = "image.png"
    file_size: int = 0
    mime_type: str = "image/png"
    message_prefix: str = ""


# ── Application lifespan ─────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown hooks."""
    # Startup
    _init_image_save_dir()
    cleanup_task = asyncio.create_task(_periodic_cleanup())

    settings = load_settings()
    tmux_bridge = TmuxBridge()
    runtime = TmuxRuntime(
        max_workers=settings.get("runtime", {}).get("thread_pool_workers", 2)
    )

    # Create adaptive pollers from settings
    monitor_settings = settings.get("monitor", {})
    monitor_poller = AdaptivePoller(
        base_interval=monitor_settings.get("base_interval_ms", 5000) / 1000,
        max_interval=monitor_settings.get("max_interval_ms", 10000) / 1000,
        no_change_threshold=monitor_settings.get("no_change_threshold", 2),
    )

    shogun_settings = settings.get("shogun", {})
    shogun_poller = AdaptivePoller(
        base_interval=shogun_settings.get("base_interval_ms", 1000) / 1000,
        max_interval=shogun_settings.get("max_interval_ms", 3000) / 1000,
        no_change_threshold=shogun_settings.get("no_change_threshold", 2),
    )

    # Create broadcasters
    monitor_broadcaster = MonitorBroadcaster(
        tmux=tmux_bridge, runtime=runtime, poller=monitor_poller
    )
    shogun_broadcaster = ShogunBroadcaster(
        tmux=tmux_bridge, runtime=runtime, poller=shogun_poller
    )

    # Start broadcasters
    await monitor_broadcaster.start()
    await shogun_broadcaster.start()

    # Store in app.state for access in handlers/APIs
    app.state.tmux_bridge = tmux_bridge
    app.state.runtime = runtime
    app.state.monitor_broadcaster = monitor_broadcaster
    app.state.shogun_broadcaster = shogun_broadcaster
    app.state.settings = settings

    yield

    # Shutdown
    cleanup_task.cancel()
    await monitor_broadcaster.stop()
    await shogun_broadcaster.stop()
    runtime.shutdown()


app = FastAPI(title="Shogun Web Panel", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render main dashboard page."""
    try:
        bridge = request.app.state.tmux_bridge
        commands = bridge.read_command_history()
        commands.reverse()
    except Exception:
        commands = []

    # X-Forwarded-Prefix ヘッダからbase_pathを取得（nginx対応）
    base_path = request.headers.get("X-Forwarded-Prefix", "")

    return templates.TemplateResponse(
        "index.html",
        {"request": request, "commands": commands, "base_path": base_path},
    )


@app.get("/api/dashboard", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    """Return dashboard.md content with raw markdown in a data container."""
    try:
        bridge = request.app.state.tmux_bridge
        content = bridge.read_dashboard()
        escaped = escape(content)
        return (
            f'<div id="dashboard-raw-data" style="display:none">{escaped}</div>'
            f'<div id="dashboard-display"></div>'
        )
    except Exception as e:
        escaped_err = escape(str(e))
        return f"<pre>Error: {escaped_err}</pre>"


class SpecialKeyRequest(BaseModel):
    key: str


@app.post("/api/command")
async def send_command(request: Request, instruction: str = Form(...)):
    """
    Send command directly to shogun pane via tmux send-keys.

    Args:
        instruction: Command string to send to shogun

    Returns:
        Status of command submission
    """
    try:
        bridge = request.app.state.tmux_bridge
        success = bridge.send_to_shogun(instruction)
        if success:
            return {"status": "sent"}
        else:
            return {"status": "error", "message": "Failed to send to shogun pane"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/special-key")
async def send_special_key(request: Request, body: SpecialKeyRequest):
    """
    Send a special key to the shogun pane.

    Args:
        body: JSON body with "key" field (e.g., {"key": "Escape"})

    Returns:
        Status of key submission

    Raises:
        HTTPException: 400 if the key is not allowed
    """
    try:
        bridge = request.app.state.tmux_bridge
        success = bridge.send_special_key(body.key)
        if success:
            return {"status": "sent", "key": body.key}
        else:
            return {"status": "error", "message": "Failed to send key to shogun pane"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/history", response_class=HTMLResponse)
async def get_history(request: Request):
    """Return command history as HTML."""
    try:
        bridge = request.app.state.tmux_bridge
        commands = bridge.read_command_history()
        commands.reverse()  # 最新順

        # X-Forwarded-Prefix ヘッダからbase_pathを取得
        base_path = request.headers.get("X-Forwarded-Prefix", "")

        return templates.TemplateResponse(
            "partials/history.html",
            {"request": request, "commands": commands, "base_path": base_path},
        )
    except Exception as e:
        return HTMLResponse(f"<pre>Error: {e}</pre>")


@app.post("/api/monitor/clear")
async def clear_monitor(request: Request):
    """
    Clear monitor display by setting snapshot.

    Saves current pane content as snapshot. New subscribers and reconnecting
    clients will only receive content generated after this clear point.
    Does NOT affect tmux pane history (non-destructive).

    Returns:
        Status of clear operation
    """
    try:
        broadcaster = request.app.state.monitor_broadcaster
        await broadcaster.clear_all()
        return {"status": "cleared"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/ws-config")
async def get_ws_config(request: Request):
    """Return WebSocket reconnection config derived from settings.yaml intervals."""
    settings = request.app.state.settings
    monitor = settings.get("monitor", {})
    shogun = settings.get("shogun", {})
    return {
        "monitor": {
            "base_interval_ms": monitor.get("base_interval_ms", 5000),
            "max_interval_ms": monitor.get("max_interval_ms", 10000),
        },
        "shogun": {
            "base_interval_ms": shogun.get("base_interval_ms", 1000),
            "max_interval_ms": shogun.get("max_interval_ms", 3000),
        },
    }


@app.post("/api/file-paste")
async def file_paste(request: Request, body: FilePasteRequest):
    """Save a file to disk and send its path to the shogun tmux pane via send-keys."""
    logger.info("[FILE-PASTE] file_name=%s, mime_type=%s", body.file_name, body.mime_type)

    try:
        file_data = base64.b64decode(body.file_b64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid base64 data: {exc}") from exc

    bridge = request.app.state.tmux_bridge
    settings = request.app.state.settings

    target = body.target
    if not target:
        tmux_settings = settings.get("tmux", {})
        target = (
            f"{tmux_settings.get('shogun_session', 'shogun')}"
            f":{tmux_settings.get('shogun_pane', '0.0')}"
        )

    if not _TARGET_RE.match(target):
        raise HTTPException(status_code=400, detail="Invalid target format.")
    allowed_targets = _build_allowed_targets(settings)
    if target not in allowed_targets:
        raise HTTPException(status_code=403, detail=f"Target '{target}' not allowed.")

    try:
        ext = _get_file_ext(body.mime_type, body.file_name)
        file_path = _build_save_path(ext)
        with open(file_path, "wb") as f:
            f.write(file_data)
        logger.info("[FILE-PASTE] saved to %s (%d bytes)", file_path, len(file_data))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {exc}") from exc

    safe_prefix = re.sub(r"[\x00-\x1f\x7f]", "", body.message_prefix)[:200]
    sent_message = f"{safe_prefix}: {file_path}" if safe_prefix else f"ファイル: {file_path}"

    success = bridge.send_to_shogun(sent_message)
    if success:
        return {"status": "sent", "target": target, "file_path": file_path, "sent_message": sent_message}
    else:
        raise HTTPException(status_code=500, detail="Failed to send file path via tmux send-keys")


@app.post("/api/image-paste")
async def image_paste(request: Request, body: ImagePasteRequest):
    """Backward-compatible alias for /api/file-paste."""
    file_req = FilePasteRequest(
        target=body.target,
        file_b64=body.image_b64,
        file_name=body.file_name,
        file_size=body.file_size,
        mime_type=body.mime_type,
        message_prefix=body.message_prefix,
    )
    return await file_paste(request, file_req)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time shogun pane output."""
    handler = WebSocketHandler(app.state.shogun_broadcaster)
    await handler.handle(websocket)


@app.websocket("/ws/monitor")
async def monitor_websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for monitoring all multiagent panes."""
    handler = MonitorWebSocketHandler(app.state.monitor_broadcaster)
    await handler.handle(websocket)


def load_settings():
    """Load settings from config/settings.yaml."""
    settings_path = Path(__file__).parent / "config" / "settings.yaml"
    with open(settings_path) as f:
        return yaml.safe_load(f)


if __name__ == "__main__":
    settings = load_settings()
    uvicorn.run(
        app,
        host=settings["server"]["host"],
        port=settings["server"]["port"],
    )
