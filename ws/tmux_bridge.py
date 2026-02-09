"""
Tmux Bridge Module for Shogun Web Interface.

This module provides integration between the web interface and tmux sessions,
allowing remote control and monitoring of the multi-agent system.
"""

import re
import subprocess
from datetime import datetime
from pathlib import Path

import libtmux
import yaml

# _clean_output constants
_SEPARATOR_RE = re.compile(r"^─{20,}\s*$")
_STATUS_RE = re.compile(r"^\s*⏵")
_HINT_RE = re.compile(r"^\s*[✢✻✽]")
UNIT_SEPARATOR = "\x1f"

# sanitize_pane_text constants
ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
MIN_RULE_LEN = 10
RULE_RE = re.compile(rf"^\s*[-─━―]{{{MIN_RULE_LEN},}}\s*$")


def sanitize_pane_text(s: str) -> str:
    """tmux pane出力からANSIエスケープと罫線ノイズを除去する

    Args:
        s: 生のtmux pane出力テキスト

    Returns:
        クリーニング済みのテキスト
    """
    # 1) ANSI除去
    s = ANSI_RE.sub("", s)

    # 2) 行単位で罫線除去（連続も潰す）
    out = []
    for line in s.splitlines():
        if RULE_RE.match(line):
            continue
        out.append(line.rstrip())

    # 3) 末尾空行トリム
    while out and not out[-1].strip():
        out.pop()

    return "\n".join(out)


class TmuxBridge:
    """Bridge between web interface and tmux multi-agent sessions."""

    @staticmethod
    def _clean_output(text: str) -> str:
        """Clean tmux pane output: mark user input lines, remove noise.

        Detects user input enclosed in separator line pairs (─×20+),
        adds \\x1f marker to those lines, strips ❯ prefix, and removes
        separator lines, status lines (⏵), and hint lines (✢✻✽).
        """
        lines = text.split("\n")

        # Find separator line indices
        sep_indices = [i for i, line in enumerate(lines) if _SEPARATOR_RE.match(line)]

        # Pair separators: (0,1), (2,3), ...
        user_input_lines: set[int] = set()
        paired_seps: set[int] = set()

        for k in range(0, len(sep_indices) - 1, 2):
            start = sep_indices[k]
            end = sep_indices[k + 1]
            paired_seps.add(start)
            paired_seps.add(end)
            for j in range(start + 1, end):
                user_input_lines.add(j)

        result = []
        for i, line in enumerate(lines):
            if i in paired_seps:
                continue
            if _STATUS_RE.match(line):
                continue
            if _HINT_RE.match(line):
                continue

            if i in user_input_lines:
                clean_line = line
                if clean_line.startswith("❯ "):
                    clean_line = clean_line[2:]
                result.append(UNIT_SEPARATOR + clean_line)
            else:
                result.append(line)

        return "\n".join(result)

    def __init__(self):
        """Initialize the tmux bridge and connect to the multiagent session."""
        self.server = libtmux.Server()
        settings_path = Path(__file__).parent.parent / "config" / "settings.yaml"
        with open(settings_path) as f:
            settings = yaml.safe_load(f)
        self.bakuhu_base = Path(settings["bakuhu"]["base_path"])
        tmux_settings = settings.get("tmux", {})
        self.shogun_session = tmux_settings.get("shogun_session", "shogun")
        self.multiagent_session = tmux_settings.get("multiagent_session", "multiagent")
        self.shogun_pane = tmux_settings.get("shogun_pane", "0.0")
        self.session = self.server.sessions.get(
            session_name=self.multiagent_session, default=None
        )

    def capture_shogun_pane(self, lines: int = 2000) -> str:
        """
        Capture output from the shogun pane (shogun:0.0) with scrollback.

        Args:
            lines: Number of lines to capture from scrollback (default: 2000)

        Returns:
            Captured pane output as string, or error message if pane not found
        """
        shogun_session = self.server.sessions.get(
            session_name=self.shogun_session, default=None
        )
        if not shogun_session:
            return "Error: shogun session not found"
        try:
            pane = shogun_session.panes.get(pane_index="0")
        except Exception:
            pane = None
        if pane:
            # Capture with scrollback: start=-lines to include history
            captured = pane.capture_pane(start=-lines, join_wrapped=True)
            raw = "\n".join(captured)
            cleaned = self._clean_output(raw)
            return sanitize_pane_text(cleaned)
        return "Error: shogun pane not found"

    def capture_all_panes(self, lines: int = 2000) -> list[dict]:
        """
        Capture output from all panes in the multiagent session with scrollback.

        Args:
            lines: Number of lines to capture from scrollback (default: 2000)

        Returns:
            List of dictionaries with agent_id, pane_index, and output
            Example: [{"agent_id": "karo", "pane_index": 0, "output": "..."}]
        """
        if not self.session:
            return []

        result = []
        for pane in self.session.panes:
            # Get pane index
            pane_index = int(pane.pane_index)

            # Try to get @agent_id from tmux user option
            try:
                agent_id = pane.show_option("@agent_id")
            except Exception:
                agent_id = None

            # Fallback to pane_index if @agent_id is not set
            if not agent_id:
                agent_id = f"pane_{pane_index}"

            # Capture pane output with scrollback
            try:
                captured = pane.capture_pane(start=-lines, join_wrapped=True)
                cleaned = self._clean_output("\n".join(captured))
                output = sanitize_pane_text(cleaned)
            except Exception:
                output = "Error: failed to capture pane"

            result.append(
                {"agent_id": agent_id, "pane_index": pane_index, "output": output}
            )

        return result

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
        try:
            pane = self.session.panes.get(pane_index="0")
        except Exception:
            pane = None
        if pane:
            import time

            pane.send_keys(message, enter=False)
            time.sleep(0.1)
            pane.send_keys("", enter=True)
            return True
        return False

    def send_to_shogun(self, message: str) -> bool:
        """Send a message to the shogun pane (shogun:0.0)."""
        target = f"{self.shogun_session}:{self.shogun_pane}"
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", target, message],
                check=True,
            )
            subprocess.run(
                ["tmux", "send-keys", "-t", target, "Enter"],
                check=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def send_special_key(self, key: str) -> bool:
        """
        Send a special key to the shogun pane (shogun:0.0).

        Args:
            key: Special key name (e.g., "Escape")

        Returns:
            True if successful, False otherwise

        Raises:
            ValueError: If the key is not in the allowlist
        """
        # allowlist: 将来拡張可能
        ALLOWED_KEYS = {"Escape"}
        if key not in ALLOWED_KEYS:
            raise ValueError(
                f"Key '{key}' is not allowed. Allowed keys: {ALLOWED_KEYS}"
            )

        target = f"{self.shogun_session}:{self.shogun_pane}"
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", target, key],
                check=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def read_dashboard(self, cache=None) -> str:
        """
        Read the contents of dashboard.md.

        Args:
            cache: Optional DashboardCache instance for mtime-based caching

        Returns:
            Dashboard contents as string, or error message if not found
        """
        dashboard_path = self.bakuhu_base / "dashboard.md"
        if not dashboard_path.exists():
            return "Dashboard not found"

        # Use cache if provided
        if cache is not None:
            return cache.read()

        # Fallback to direct read
        return dashboard_path.read_text()

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
        indented_lines = "\n".join(
            "    " + line if line.strip() else "" for line in lines
        )

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
