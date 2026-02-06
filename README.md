# multi-agent-shogun-tenshukaku

> This project is a web control panel originally built for [yohey-w/multi-agent-shogun](https://github.com/yohey-w/multi-agent-shogun) and its forks. Compatible with any multi-agent-shogun family system via `config/settings.yaml`.

Web-based control panel for multi-agent-shogun orchestration systems. Named after the castle keep (天守閣) — the commander's vantage point overlooking the entire battlefield.

![Command Tab](assets/screenshots/tab-command.png)

## Overview

Tenshukaku provides a browser-based interface for commanding and monitoring a fleet of AI agents (Claude Code instances) running in tmux. Instead of switching between terminal panes, the human operator ("殿") can issue commands, monitor all agents, review the dashboard, and browse command history — all from a single web page.

## Features

### Command Tab (指揮)

Send messages directly to the Shogun agent's tmux pane. Supports Ctrl+Enter for quick submission and an Escape key button to interrupt Claude Code when needed. Pane output updates every second in real time.

![Command Tab](assets/screenshots/tab-command.png)

### Monitor Tab (監視)

Real-time grid view of all agent panes. Update interval is configurable (default: 5 seconds).

![Monitor Tab](assets/screenshots/tab-monitor.png)

### Dashboard Tab (戦況)

Renders the `dashboard.md` battle report — task progress, blockers, skill candidates, and daily achievements — updated automatically every 5 seconds.

![Dashboard Tab](assets/screenshots/tab-dashboard.png)

### History Tab (履歴)

Browse the command queue (`shogun_to_karo.yaml`) with expandable details for each command. Includes bulk open/close controls.

![History Tab](assets/screenshots/tab-history.png)

## Architecture

```
Browser (HTTP + WebSocket)
    │
    ├── GET  /              → Main SPA (Jinja2 templates + htmx)
    ├── POST /api/command   → tmux send-keys to shogun pane
    ├── POST /api/special-key → Send Escape key (allowlist-based)
    ├── GET  /api/dashboard → Read dashboard.md
    ├── GET  /api/history   → Read shogun_to_karo.yaml
    ├── WS   /ws            → Real-time shogun pane output
    └── WS   /ws/monitor    → Real-time all-pane monitoring
    │
    ▼
FastAPI + Uvicorn
    │
    ▼
TmuxBridge (libtmux)
    │
    ▼
tmux sessions (shogun / multiagent)
```

### Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | FastAPI + Uvicorn |
| Templates | Jinja2 |
| Frontend | htmx 2.x + Vanilla JS |
| WebSocket | FastAPI native WebSocket |
| tmux Integration | libtmux 0.53+ |
| Styling | Custom CSS (Sengoku-era theme) |
| Package Manager | uv |

## Setup

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- tmux with active `shogun` and `multiagent` sessions (from [multi-agent-bakuhu](https://github.com/yaziuma/multi-agent-bakuhu))

### Installation

```bash
git clone https://github.com/yaziuma/multi-agent-shogun-tenshukaku.git
cd multi-agent-shogun-tenshukaku

# Install dependencies
uv sync
```

### Configuration

Edit `config/settings.yaml`:

```yaml
server:
  host: "0.0.0.0"
  port: 30000

bakuhu:
  base_path: "/path/to/multi-agent-bakuhu"

tmux:
  shogun_session: "shogun"          # Shogun tmux session name
  multiagent_session: "multiagent"  # Multi-agent tmux session name
  shogun_pane: "0.0"                # Shogun pane index

monitor:
  update_interval_ms: 5000  # Monitor tab update interval (ms)
```

### Running

```bash
# Using the start script (recommended — handles process management)
./start.sh

# Or manually
uv run uvicorn main:app --host 0.0.0.0 --port 30000
```

Access at `http://<your-host>:30000`

## Project Structure

```
multi-agent-shogun-tenshukaku/
├── main.py                  # FastAPI application & API routes
├── ws/
│   ├── handlers.py          # WebSocket handlers (shogun + monitor)
│   └── tmux_bridge.py       # tmux session interaction layer
├── templates/
│   ├── base.html            # Base template (header, footer, assets)
│   ├── index.html           # Main SPA (4 tabs + JS)
│   └── partials/
│       └── history.html     # Command history partial
├── static/
│   └── style.css            # Sengoku-era themed CSS
├── config/
│   └── settings.yaml        # Server, bakuhu path, tmux & monitor configuration
├── tests/
│   ├── test_api.py          # API endpoint tests
│   ├── test_tmux_bridge.py  # TmuxBridge unit tests
│   └── test_monitor.py      # Monitor WebSocket tests
├── start.sh                 # Safe startup script
├── pyproject.toml           # Project metadata & dependencies
└── assets/
    └── screenshots/         # UI screenshots
```

## Testing

```bash
uv run pytest
```

## Compatibility

Tenshukaku works with any multi-agent-shogun family system. All session names, pane targets, and base paths are configurable via `config/settings.yaml`.

| System | Compatibility |
|--------|--------------|
| [yaziuma/multi-agent-bakuhu](https://github.com/yaziuma/multi-agent-bakuhu) | Developed for this system |
| [yohey-w/multi-agent-shogun](https://github.com/yohey-w/multi-agent-shogun) | Compatible — adjust `bakuhu.base_path` and `tmux` session names in settings |

## Related Projects

- [multi-agent-bakuhu](https://github.com/yaziuma/multi-agent-bakuhu) — The core multi-agent orchestration system that Tenshukaku controls
- [multi-agent-shogun](https://github.com/yohey-w/multi-agent-shogun) — The upstream fork that bakuhu is based on

## License

MIT
