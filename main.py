import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

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
