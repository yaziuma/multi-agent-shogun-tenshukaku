# multi-agent-shogun-tenshukaku

> This project is a web control panel originally built for [yohey-w/multi-agent-shogun](https://github.com/yohey-w/multi-agent-shogun) and its forks. Compatible with any multi-agent-shogun family system via `config/settings.yaml`.

Web-based control panel for multi-agent-shogun orchestration systems. Named after the castle keep (天守閣) — the commander's vantage point overlooking the entire battlefield.

![Command Tab](assets/screenshots/tab-command.png)

## Overview

Tenshukaku provides a browser-based interface for commanding and monitoring a fleet of AI agents (Claude Code instances) running in tmux. Instead of switching between terminal panes, the human operator ("殿") can issue commands, monitor all agents, review the dashboard, and browse command history — all from a single web page.

## Features

### Command Tab (指揮)

Send messages directly to the Shogun agent's tmux pane. Supports Ctrl+Enter for quick submission and an Escape key button to interrupt Claude Code when needed. Includes Top/Bottom scroll buttons for navigating long output.

A collapsible **TUI Operation Panel** provides direct keyboard input: arrow keys, Enter, Tab, Space, Backspace, number keys (0-9), and Yes/No confirmation buttons — useful for navigating interactive CLI interfaces without leaving the browser. Critical keys (Enter, Escape, Yes, No) require a 1-second long-press to prevent accidental activation.

The **Chat Log** section displays a conversation-style view of interactions: user messages appear in blue and shogun responses in gold. The raw tmux pane output is available in a collapsible section below the chat log.

![Command Tab](assets/screenshots/tab-command.png)

### Monitor Tab (監視)

Real-time grid view of all agent panes using WebSocket delta updates for efficient bandwidth usage. Update interval is configurable (default: 5 seconds). A **Clear Display** button resets the monitor view without affecting tmux pane history (non-destructive). User input lines are highlighted in light blue for easy identification.

![Monitor Tab](assets/screenshots/tab-monitor.png)

### Dashboard Tab (戦況)

Renders the `dashboard.md` battle report — task progress, blockers, skill candidates, and daily achievements. Content is loaded on demand via a manual **Refresh** button (auto-refresh has been removed to reduce unnecessary API calls).

Supports two display modes via a **Raw/Rendered toggle**:
- **Rendered mode** (default): Parses markdown using [marked.js](https://marked.js.org/) with [github-markdown-css](https://github.com/sindresorhus/github-markdown-css), styled with custom Sengoku-era theme overrides for tables, headings, code blocks, blockquotes, and other elements.
- **Raw mode**: Displays the original markdown source text as-is.

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
    ├── POST /api/special-key → Send special keys (allowlist-based)
    ├── POST /api/monitor/clear → Clear monitor display (non-destructive)
    ├── GET  /api/dashboard → Read dashboard.md (raw markdown in data container)
    ├── GET  /api/history   → Read shogun_to_karo.yaml
    ├── GET  /api/ws-config → WebSocket reconnection configuration
    ├── WS   /ws            → Real-time shogun pane output (delta)
    └── WS   /ws/monitor    → Real-time all-pane monitoring (delta)
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
| WebSocket | FastAPI native WebSocket (delta diff delivery) |
| Markdown Rendering | marked.js + github-markdown-css |
| tmux Integration | libtmux 0.53+ |
| Styling | Custom CSS (Sengoku-era theme) |
| Package Manager | uv |

### WebSocket Reconnection

WebSocket connections use a `ReconnectingWebSocket` class with:
- Automatic reconnection with exponential backoff (1s to 30s)
- Maximum 3 retry attempts before showing a manual **Reconnect** button
- UI display delay to suppress transient disconnection indicators
- All thresholds derived from `settings.yaml` via `/api/ws-config` (no hardcoded values)

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
  port: 30001

bakuhu:
  base_path: "/path/to/multi-agent-bakuhu"

tmux:
  shogun_session: "shogun"
  multiagent_session: "multiagent"
  shogun_pane: "0.0"

runtime:
  thread_pool_workers: 2

monitor:
  base_interval_ms: 5000
  max_interval_ms: 10000
  no_change_threshold: 2

shogun:
  base_interval_ms: 1000
  max_interval_ms: 3000
  no_change_threshold: 2

ui:
  user_input_color: "#4FC3F7"
```

### Running

```bash
# Using the start script (recommended — handles process management)
./start.sh

# Development restart (full cache cleanup + hot reload)
./restart.sh

# Or manually
uv run uvicorn main:app --host 0.0.0.0 --port 30001
```

Access at `http://<your-host>:30001`

## Project Structure

```
multi-agent-shogun-tenshukaku/
├── main.py                  # FastAPI application & API routes
├── ws/
│   ├── broadcasters.py     # Broadcast managers (shogun + monitor)
│   ├── dashboard_cache.py  # mtime-based dashboard file cache
│   ├── delta.py            # Delta diff computation for WebSocket updates
│   ├── handlers.py         # WebSocket handlers (shogun + monitor)
│   ├── runtime.py          # Thread pool executor + async lock
│   ├── state.py            # Pane state diff detection (sha1)
│   └── tmux_bridge.py      # tmux session interaction layer
├── templates/
│   ├── base.html            # Base template (header, footer, CDN assets)
│   ├── index.html           # Main SPA (4 tabs + JS)
│   └── partials/
│       ├── history.html     # Command history partial
│       ├── output.html      # Pane output partial
│       └── status.html      # Status display partial
├── static/
│   └── style.css            # Sengoku-era themed CSS (incl. markdown overrides)
├── config/
│   └── settings.yaml        # Server, bakuhu path, tmux & monitor configuration
├── tests/
│   ├── test_api.py                      # API endpoint tests
│   ├── test_broadcasters.py             # Broadcaster unit tests
│   ├── test_dashboard_markdown.py       # Dashboard markdown rendering tests (Playwright)
│   ├── test_dashboard_refresh.py        # Dashboard manual refresh tests (Playwright)
│   ├── test_dashboard_table_dark_theme.py # Table dark theme CSS tests (Playwright)
│   ├── test_delta.py                    # Delta diff computation tests
│   ├── test_monitor.py                  # Monitor WebSocket tests
│   ├── test_sanitize.py                 # Input sanitization tests
│   ├── test_tmux_bridge.py              # TmuxBridge unit tests
│   ├── test_ws_core.py                  # PaneState & DashboardCache tests
│   └── test_ws_endpoints.py             # WebSocket endpoint tests
├── start.sh                 # Safe startup script
├── restart.sh               # Development restart script
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
