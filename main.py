from fastapi import FastAPI, Request, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import uvicorn
from ws.handlers import WebSocketHandler

app = FastAPI(title="Shogun Web Panel")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render main dashboard page."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/dashboard")
async def get_dashboard():
    """Return dashboard.md content."""
    # TODO: Read and return dashboard.md content
    return {"status": "not_implemented"}


@app.post("/api/command")
async def send_command(command: str):
    """
    Send command to karo via queue/shogun_to_karo.yaml.

    Args:
        command: Command string to send to karo

    Returns:
        Status of command submission
    """
    # TODO: Append to queue/shogun_to_karo.yaml and send tmux send-keys
    return {"status": "not_implemented", "command": command}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time tmux output updates."""
    handler = WebSocketHandler(websocket)
    await handler.handle()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
