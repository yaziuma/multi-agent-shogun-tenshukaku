from fastapi import FastAPI, Request, WebSocket, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import uvicorn
import yaml
from pathlib import Path
from ws.handlers import WebSocketHandler
from ws.tmux_bridge import TmuxBridge

app = FastAPI(title="Shogun Web Panel")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render main dashboard page."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/dashboard", response_class=HTMLResponse)
async def get_dashboard():
    """Return dashboard.md content."""
    try:
        bridge = TmuxBridge()
        content = bridge.read_dashboard()
        return f"<pre>{content}</pre>"
    except Exception as e:
        return f"<pre>Error: {e}</pre>"


@app.post("/api/command")
async def send_command(instruction: str = Form(...)):
    """
    Send command to shogun via queue/shogun_to_karo.yaml.

    Args:
        instruction: Command string to send to shogun

    Returns:
        Status of command submission
    """
    try:
        bridge = TmuxBridge()
        cmd_id = bridge.add_command(instruction)
        bridge.send_to_shogun(
            f"queue/shogun_to_karo.yaml に新しい指示がある。{cmd_id} を確認して実行せよ。"
        )
        return {"status": "sent", "cmd_id": cmd_id}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/history", response_class=HTMLResponse)
async def get_history(request: Request):
    """Return command history as HTML."""
    try:
        bridge = TmuxBridge()
        commands = bridge.read_command_history()
        commands.reverse()  # 最新順
        return templates.TemplateResponse("partials/history.html", {
            "request": request,
            "commands": commands
        })
    except Exception as e:
        return HTMLResponse(f"<pre>Error: {e}</pre>")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time tmux output updates."""
    handler = WebSocketHandler(websocket)
    await handler.handle()


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
