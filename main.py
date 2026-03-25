import asyncio
import base64
import logging
import os
import re
import tempfile
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

import uvicorn
import yaml
from fastapi import FastAPI, Form, HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import escape
from pydantic import BaseModel

from ws.broadcasters import AdaptivePoller, MonitorBroadcaster, ShogunBroadcaster
from ws.handlers import MonitorWebSocketHandler, WebSocketHandler
from ws.runtime import TmuxRuntime
from ws.tmux_bridge import TmuxBridge


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

    settings = request.app.state.settings
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "commands": commands,
            "base_path": base_path,
            "settings": settings,
        },
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Render settings page."""
    base_path = request.headers.get("X-Forwarded-Prefix", "")
    settings = request.app.state.settings
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "settings": settings,
            "base_path": base_path,
        },
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


class TemplatePhrase(BaseModel):
    label: str
    text: str


class MonitorSettingsUpdate(BaseModel):
    base_interval_ms: int
    max_interval_ms: int


class ShogunSettingsUpdate(BaseModel):
    base_interval_ms: int
    max_interval_ms: int


class UISettingsUpdate(BaseModel):
    textarea_max_rows: int
    template_phrases: list[TemplatePhrase]


class SettingsPayload(BaseModel):
    monitor: MonitorSettingsUpdate
    shogun: ShogunSettingsUpdate
    ui: UISettingsUpdate


MAX_FILE_BYTES = 0  # No size limit

# 画像一時保存ディレクトリ
IMAGE_SAVE_DIR = "/tmp/tenshukaku-images"
IMAGE_MAX_FILES = 50
IMAGE_TTL_SECONDS = 30 * 60  # 30分

_MIME_TO_EXT = {
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/gif": "gif",
    "image/webp": "webp",
}
def _get_file_ext(mime_type: str, file_name: str) -> str:
    """Return safe file extension: MIME-table for images, filename-based for others."""
    if mime_type in _MIME_TO_EXT:
        return _MIME_TO_EXT[mime_type]
    ext = os.path.splitext(file_name)[1].lstrip(".")
    # Sanitize: allow only alphanumeric (prevents traversal via crafted extensions)
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
    logger.info("[IMAGE-SAVE] initialized %s", IMAGE_SAVE_DIR)


def _cleanup_old_images() -> None:
    now = datetime.now().timestamp()
    save_dir = Path(IMAGE_SAVE_DIR)
    files = sorted(save_dir.glob("tenshukaku_*"), key=lambda p: p.stat().st_mtime)

    # TTL超過ファイルを削除
    for f in files:
        try:
            if now - f.stat().st_mtime > IMAGE_TTL_SECONDS:
                f.unlink()
        except OSError:
            pass

    # ファイル数上限: 最古から削除
    remaining = sorted(save_dir.glob("tenshukaku_*"), key=lambda p: p.stat().st_mtime)
    while len(remaining) > IMAGE_MAX_FILES:
        try:
            remaining.pop(0).unlink()
        except OSError:
            remaining.pop(0)


async def _periodic_cleanup() -> None:
    while True:
        await asyncio.sleep(5 * 60)  # 5分おき
        try:
            _cleanup_old_images()
        except Exception as exc:
            logger.warning("[IMAGE-CLEANUP] error: %s", exc)


class FilePasteRequest(BaseModel):
    target: str = ""  # tmux target pane (empty = shogun pane from settings)
    file_b64: str  # Base64-encoded file data (raw, without data URI prefix)
    file_name: str = "file.bin"
    file_size: int = 0  # optional, informational only
    mime_type: str = "application/octet-stream"
    message_prefix: str = ""  # optional prefix for the tmux send-keys message


class ImagePasteRequest(BaseModel):
    """Backward-compatible alias for FilePasteRequest (image-only legacy clients)."""

    target: str = ""
    image_b64: str
    file_name: str = "image.png"
    file_size: int = 0
    mime_type: str = "image/png"
    message_prefix: str = ""


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


SETTINGS_PATH = Path(__file__).parent / "config" / "settings.yaml"


@app.get("/api/settings")
async def get_settings(request: Request):
    """Return user-configurable settings."""
    s = request.app.state.settings
    monitor = s.get("monitor", {})
    shogun = s.get("shogun", {})
    ui = s.get("ui", {})
    return {
        "monitor": {
            "base_interval_ms": monitor.get("base_interval_ms", 5000),
            "max_interval_ms": monitor.get("max_interval_ms", 10000),
        },
        "shogun": {
            "base_interval_ms": shogun.get("base_interval_ms", 1000),
            "max_interval_ms": shogun.get("max_interval_ms", 3000),
        },
        "ui": {
            "textarea_max_rows": ui.get("textarea_max_rows", 8),
            "template_phrases": ui.get("template_phrases") or [],
        },
    }


@app.put("/api/settings")
async def update_settings(request: Request, body: SettingsPayload):
    """Update user-configurable settings and write to settings.yaml atomically."""
    # Validation
    for name, val in [
        ("monitor.base_interval_ms", body.monitor.base_interval_ms),
        ("monitor.max_interval_ms", body.monitor.max_interval_ms),
        ("shogun.base_interval_ms", body.shogun.base_interval_ms),
        ("shogun.max_interval_ms", body.shogun.max_interval_ms),
    ]:
        if not (100 <= val <= 60000):
            raise HTTPException(
                status_code=422, detail=f"{name} must be between 100 and 60000"
            )
    if body.monitor.max_interval_ms < body.monitor.base_interval_ms:
        raise HTTPException(
            status_code=422,
            detail="monitor.max_interval_ms must be >= base_interval_ms",
        )
    if body.shogun.max_interval_ms < body.shogun.base_interval_ms:
        raise HTTPException(
            status_code=422, detail="shogun.max_interval_ms must be >= base_interval_ms"
        )
    if not (1 <= body.ui.textarea_max_rows <= 50):
        raise HTTPException(
            status_code=422, detail="ui.textarea_max_rows must be between 1 and 50"
        )

    # Load current full settings (to preserve non-editable fields)
    with open(SETTINGS_PATH) as f:
        full = yaml.safe_load(f)

    # Apply updates
    full.setdefault("monitor", {})
    full["monitor"]["base_interval_ms"] = body.monitor.base_interval_ms
    full["monitor"]["max_interval_ms"] = body.monitor.max_interval_ms
    full.setdefault("shogun", {})
    full["shogun"]["base_interval_ms"] = body.shogun.base_interval_ms
    full["shogun"]["max_interval_ms"] = body.shogun.max_interval_ms
    full.setdefault("ui", {})
    full["ui"]["textarea_max_rows"] = body.ui.textarea_max_rows
    full["ui"]["template_phrases"] = [p.model_dump() for p in body.ui.template_phrases]

    # Atomic write: write to tmp then rename
    dir_ = SETTINGS_PATH.parent
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".yaml.tmp")
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(full, f, allow_unicode=True, default_flow_style=False)
        os.replace(tmp_path, SETTINGS_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    # Update in-memory state
    request.app.state.settings = full
    return {"status": "saved"}


# Allow-list: only these tmux target formats are accepted for image paste.
# Format: "session_name:window_index.pane_index" (e.g., "shogun:0.0")
# Regex: alphanumeric/underscore/hyphen session names, numeric window/pane indices.
_TARGET_RE = re.compile(r"^[A-Za-z0-9_-]+:\d+\.\d+$")


def _build_allowed_targets(settings: dict) -> set[str]:
    """Build the set of allowed tmux targets from settings.yaml."""
    tmux = settings.get("tmux", {})
    allowed = set()
    # Shogun pane is always allowed
    session = tmux.get("shogun_session", "shogun")
    pane = tmux.get("shogun_pane", "0.0")
    allowed.add(f"{session}:{pane}")
    return allowed


@app.post("/api/file-paste")
async def file_paste(request: Request, body: FilePasteRequest):
    """Save a file to disk and send its path to the shogun tmux pane via send-keys.

    Supports any file type. Claude Code can read images, PDFs, text, code, etc. via
    the file path. For image MIMEs, magic bytes validation is applied. For other types,
    the extension is derived from the filename.

    Args:
        body: JSON with file_b64 (Base64 data), file_name, mime_type,
              and optional message_prefix, target

    Returns:
        {"status": "sent", "target": "...", "file_path": "...", "sent_message": "..."}

    Raises:
        HTTPException 400: Invalid target format or target not in allow-list
        HTTPException 413: File exceeds 10MB limit
        HTTPException 415: Image magic bytes mismatch
        HTTPException 500: File save or send-keys failed
    """
    logger.info(
        "[FILE-PASTE] endpoint called, file_name=%s, mime_type=%s",
        body.file_name,
        body.mime_type,
    )

    # Decode base64
    try:
        file_data = base64.b64decode(body.file_b64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid base64 data: {exc}") from exc

    bridge = request.app.state.tmux_bridge
    settings = request.app.state.settings

    # Resolve target pane (default: shogun pane from settings)
    target = body.target
    if not target:
        tmux_settings = settings.get("tmux", {})
        target = (
            f"{tmux_settings.get('shogun_session', 'shogun')}"
            f":{tmux_settings.get('shogun_pane', '0.0')}"
        )

    # Allow-list validation
    if not _TARGET_RE.match(target):
        raise HTTPException(
            status_code=400,
            detail="Invalid target format. Expected 'session:window.pane' (e.g., 'shogun:0.0')",
        )
    allowed_targets = _build_allowed_targets(settings)
    if target not in allowed_targets:
        raise HTTPException(
            status_code=403,
            detail=f"Target '{target}' is not in the allowed list: {sorted(allowed_targets)}",
        )

    # Save file
    try:
        ext = _get_file_ext(body.mime_type, body.file_name)
        file_path = _build_save_path(ext)
        with open(file_path, "wb") as f:
            f.write(file_data)
        logger.info("[FILE-PASTE] saved to %s (%d bytes)", file_path, len(file_data))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {exc}") from exc

    # Build send-keys message
    safe_prefix = re.sub(r"[\x00-\x1f\x7f]", "", body.message_prefix)[:200]
    if safe_prefix:
        sent_message = f"{safe_prefix}: {file_path}"
    else:
        sent_message = f"ファイル: {file_path}"

    # Send file path to shogun pane via tmux send-keys
    success = bridge.send_to_shogun(sent_message)
    logger.info("[FILE-PASTE] send_to_shogun result=%s, message=%s", success, sent_message)

    if success:
        return {
            "status": "sent",
            "target": target,
            "file_path": file_path,
            "sent_message": sent_message,
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to send file path via tmux send-keys")


@app.delete("/api/files/{filename}")
async def delete_file(filename: str):
    """Delete a specific file from the image save directory.

    Args:
        filename: filename only (no path separators allowed)

    Returns:
        {"status": "deleted", "filename": "..."}

    Raises:
        HTTPException 400: Invalid filename (path traversal attempt)
        HTTPException 404: File not found
        HTTPException 500: Failed to delete file
    """
    # Path traversal防止: ファイル名にパスセパレータを禁止
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = Path(IMAGE_SAVE_DIR) / filename

    # IMAGE_SAVE_DIR 外へのパストラバーサル防止
    save_dir_real = os.path.realpath(IMAGE_SAVE_DIR) + os.sep
    if not os.path.realpath(file_path).startswith(save_dir_real):
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    try:
        file_path.unlink()
        logger.info("[FILE-DELETE] deleted %s", file_path)
        return {"status": "deleted", "filename": filename}
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {exc}") from exc


@app.post("/api/image-paste")
async def image_paste(request: Request, body: ImagePasteRequest):
    """Backward-compatible alias for /api/file-paste (image-only legacy clients)."""
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
