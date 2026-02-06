"""
Tmux Bridge Module for Shogun Web Interface.

This module provides integration between the web interface and tmux sessions,
allowing remote control and monitoring of the multi-agent system.
"""

import os
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
        self.bakuhu_base = Path(os.environ.get(
            "BAKUHU_BASE",
            "/home/quieter/projects/multi-agent-bakuhu"
        ))

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

        Args:
            instruction: Command instruction text

        Returns:
            Generated cmd_id (e.g., "cmd_025")
        """
        yaml_path = self.bakuhu_base / "queue/shogun_to_karo.yaml"

        # Load existing data
        if yaml_path.exists():
            with open(yaml_path) as f:
                data = yaml.safe_load(f) or {"commands": []}
        else:
            data = {"commands": []}

        # Generate new cmd_id
        existing_ids = [c.get("cmd_id", "") for c in data["commands"]]
        max_num = 0
        for cid in existing_ids:
            if cid.startswith("cmd_"):
                try:
                    num = int(cid.split("_")[1])
                    max_num = max(max_num, num)
                except (IndexError, ValueError):
                    pass
        new_cmd_id = f"cmd_{max_num + 1:03d}"

        # Add new command
        new_command = {
            "cmd_id": new_cmd_id,
            "timestamp": datetime.now().isoformat(),
            "status": "pending",
            "priority": "normal",
            "instruction": instruction
        }
        data["commands"].append(new_command)

        # Save
        with open(yaml_path, "w") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

        return new_cmd_id
