"""
Tmux Bridge Module for Shogun Web Interface.

This module provides integration between the web interface and tmux sessions,
allowing remote control and monitoring of the multi-agent system.
"""

import libtmux
from pathlib import Path
import yaml
from datetime import datetime
from typing import Optional


class TmuxBridge:
    """Bridge between web interface and tmux multi-agent sessions."""

    def __init__(self):
        """Initialize the tmux bridge and connect to the multiagent session."""
        self.server = libtmux.Server()
        self.session = self.server.sessions.get(session_name="multiagent", default=None)
        settings_path = Path(__file__).parent.parent / "config" / "settings.yaml"
        with open(settings_path) as f:
            settings = yaml.safe_load(f)
        self.bakuhu_base = Path(settings["bakuhu"]["base_path"])

    def capture_karo_pane(self, lines: int = 50) -> str:
        """
        Capture output from the karo pane (multiagent:0.0).

        Args:
            lines: Number of lines to capture (default: 50)

        Returns:
            Captured pane output as string, or error message if pane not found
        """
        if not self.session:
            return "Error: multiagent session not found"
        pane = self.session.panes.get(pane_index="0", default=None)
        if pane:
            captured = pane.capture_pane()
            # Return last N lines
            return "\n".join(captured[-lines:])
        return "Error: karo pane not found"

    def send_to_karo(self, message: str) -> bool:
        """
        Send a message to the karo pane.

        Args:
            message: Message to send to karo

        Returns:
            True if successful, False otherwise
        """
        if not self.session:
            return False
        pane = self.session.panes.get(pane_index="0", default=None)
        if pane:
            pane.send_keys(message)
            return True
        return False

    def send_to_shogun(self, message: str) -> bool:
        """
        Send a message to the shogun pane (shogun:0.0).

        Args:
            message: Message to send to shogun

        Returns:
            True if successful, False otherwise
        """
        shogun_session = self.server.sessions.get(
            session_name="shogun", default=None
        )
        if not shogun_session:
            return False
        pane = shogun_session.panes.get(pane_index="0", default=None)
        if pane:
            pane.send_keys(message)
            return True
        return False

    def read_dashboard(self) -> str:
        """
        Read the contents of dashboard.md.

        Returns:
            Dashboard contents as string, or error message if not found
        """
        dashboard_path = self.bakuhu_base / "dashboard.md"
        if dashboard_path.exists():
            return dashboard_path.read_text()
        return "Dashboard not found"

    def read_command_history(self) -> list:
        """
        Read command history from queue/shogun_to_karo.yaml.

        Returns:
            List of command dictionaries, or empty list if not found
        """
        yaml_path = self.bakuhu_base / "queue/shogun_to_karo.yaml"
        if yaml_path.exists():
            with open(yaml_path) as f:
                data = yaml.safe_load(f)
            return data.get("commands", []) if data else []
        return []

    def add_command(self, instruction: str) -> str:
        """
        Add a new command to queue/shogun_to_karo.yaml.

        Uses file-append mode to preserve existing YAML formatting.

        Args:
            instruction: Command instruction text

        Returns:
            Generated cmd_id (e.g., "cmd_025")
        """
        yaml_path = self.bakuhu_base / "queue/shogun_to_karo.yaml"

        # 既存データからcmd_idの最大値を取得
        if yaml_path.exists():
            with open(yaml_path) as f:
                data = yaml.safe_load(f) or {"commands": []}
            existing_ids = [c.get("cmd_id", "") for c in data.get("commands", [])]
        else:
            existing_ids = []

        max_num = 0
        for cid in existing_ids:
            if cid.startswith("cmd_"):
                try:
                    num = int(cid.split("_")[1])
                    max_num = max(max_num, num)
                except (IndexError, ValueError):
                    pass
        new_cmd_id = f"cmd_{max_num + 1:03d}"

        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        # ファイルが存在しない場合はヘッダーを書く
        if not yaml_path.exists():
            yaml_path.parent.mkdir(parents=True, exist_ok=True)
            with open(yaml_path, "w") as f:
                f.write("commands:\n")

        # instructionの各行をインデントする（block scalar用）
        lines = instruction.rstrip("\n").split("\n")
        indented_lines = "\n".join("    " + line if line.strip() else "" for line in lines)

        entry = (
            f"- cmd_id: {new_cmd_id}\n"
            f"  priority: normal\n"
            f"  status: pending\n"
            f"  timestamp: '{timestamp}'\n"
            f"  instruction: |\n"
            f"{indented_lines}\n"
        )

        with open(yaml_path, "a") as f:
            f.write(entry)

        return new_cmd_id
