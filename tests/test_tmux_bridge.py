"""
Unit tests for TmuxBridge module.

These tests run in environments without tmux sessions by using mocks and temporary files.
"""

import subprocess
from unittest.mock import Mock, mock_open, patch

import pytest
import yaml

from ws.tmux_bridge import TmuxBridge


@pytest.fixture
def mock_tmux_server():
    """Mock libtmux.Server to return a session-less state."""
    mock_server = Mock()
    mock_server.sessions.get.return_value = None
    return mock_server


@pytest.fixture
def mock_settings(tmp_path):
    """Mock settings.yaml to use tmp_path as bakuhu_base."""
    settings_content = {
        "bakuhu": {"base_path": str(tmp_path)},
        "tmux": {
            "shogun_session": "shogun",
            "multiagent_session": "multiagent",
            "shogun_pane": "0.0",
        },
    }
    return settings_content


@pytest.fixture
def bridge_instance(mock_tmux_server, mock_settings, tmp_path):
    """
    Create a TmuxBridge instance with mocked dependencies.

    This fixture mocks libtmux.Server and settings.yaml loading,
    allowing tests to run without an actual tmux session.
    """
    with patch("libtmux.Server", return_value=mock_tmux_server):
        with patch("builtins.open", mock_open(read_data=yaml.dump(mock_settings))):
            from ws.tmux_bridge import TmuxBridge

            bridge = TmuxBridge()
            # Override bakuhu_base to use tmp_path
            bridge.bakuhu_base = tmp_path
            return bridge


# ========================================
# Test: read_dashboard()
# ========================================


def test_read_dashboard_exists(bridge_instance, tmp_path):
    """Test reading dashboard.md when it exists."""
    dashboard_path = tmp_path / "dashboard.md"
    dashboard_content = "# Dashboard\n\nTest content"
    dashboard_path.write_text(dashboard_content)

    result = bridge_instance.read_dashboard()

    assert result == dashboard_content


def test_read_dashboard_not_found(bridge_instance, tmp_path):
    """Test reading dashboard.md when it does not exist."""
    result = bridge_instance.read_dashboard()

    assert result == "Dashboard not found"


# ========================================
# Test: read_command_history()
# ========================================


def test_read_command_history_exists(bridge_instance, tmp_path):
    """Test reading command history when shogun_to_karo.yaml exists."""
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    yaml_path = queue_dir / "shogun_to_karo.yaml"

    test_commands = {
        "commands": [
            {"cmd_id": "cmd_001", "instruction": "Test command 1"},
            {"cmd_id": "cmd_002", "instruction": "Test command 2"},
        ]
    }
    with open(yaml_path, "w") as f:
        yaml.dump(test_commands, f)

    result = bridge_instance.read_command_history()

    assert len(result) == 2
    assert result[0]["cmd_id"] == "cmd_001"
    assert result[1]["cmd_id"] == "cmd_002"


def test_read_command_history_not_found(bridge_instance, tmp_path):
    """Test reading command history when file does not exist."""
    result = bridge_instance.read_command_history()

    assert result == []


def test_read_command_history_empty_file(bridge_instance, tmp_path):
    """Test reading command history when file is empty."""
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    yaml_path = queue_dir / "shogun_to_karo.yaml"
    yaml_path.write_text("")

    result = bridge_instance.read_command_history()

    assert result == []


# ========================================
# Test: add_command()
# ========================================


def test_add_command_new_file(bridge_instance, tmp_path):
    """Test adding a command when shogun_to_karo.yaml does not exist."""
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()

    cmd_id = bridge_instance.add_command("Test instruction")

    assert cmd_id == "cmd_001"

    # Verify the file was created and contains the command
    yaml_path = queue_dir / "shogun_to_karo.yaml"
    assert yaml_path.exists()

    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    assert len(data["commands"]) == 1
    assert data["commands"][0]["cmd_id"] == "cmd_001"
    assert data["commands"][0]["instruction"].strip() == "Test instruction"
    assert data["commands"][0]["status"] == "pending"


def test_add_command_increment_id(bridge_instance, tmp_path):
    """Test that cmd_id increments correctly (cmd_001 -> cmd_002)."""
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    yaml_path = queue_dir / "shogun_to_karo.yaml"

    # Create existing command
    existing_data = {
        "commands": [{"cmd_id": "cmd_001", "instruction": "First command"}]
    }
    with open(yaml_path, "w") as f:
        yaml.dump(existing_data, f)

    # Add new command
    cmd_id = bridge_instance.add_command("Second command")

    assert cmd_id == "cmd_002"

    # Verify both commands are in the file
    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    assert len(data["commands"]) == 2
    assert data["commands"][1]["cmd_id"] == "cmd_002"


def test_add_command_with_gaps(bridge_instance, tmp_path):
    """Test cmd_id increment with non-sequential existing IDs."""
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    yaml_path = queue_dir / "shogun_to_karo.yaml"

    # Create existing commands with gaps (cmd_001, cmd_005)
    existing_data = {
        "commands": [
            {"cmd_id": "cmd_001", "instruction": "First"},
            {"cmd_id": "cmd_005", "instruction": "Fifth"},
        ]
    }
    with open(yaml_path, "w") as f:
        yaml.dump(existing_data, f)

    # Add new command - should be cmd_006 (max+1)
    cmd_id = bridge_instance.add_command("Sixth command")

    assert cmd_id == "cmd_006"


# ========================================
# Test: capture_shogun_pane() (without tmux session)
# ========================================


def test_capture_shogun_pane_no_session(bridge_instance):
    """Test capture_shogun_pane when tmux session is not available."""
    result = bridge_instance.capture_shogun_pane()

    assert result == "Error: shogun session not found"


# ========================================
# Test: send_to_karo() (without tmux session)
# ========================================


def test_send_to_karo_no_session(bridge_instance):
    """Test send_to_karo when tmux session is not available."""
    result = bridge_instance.send_to_karo("test message")

    assert result is False


# ========================================
# Test: send_to_shogun() (without tmux session)
# ========================================


def test_send_to_shogun_no_session(bridge_instance):
    """Test send_to_shogun when tmux command fails."""
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "tmux")):
        result = bridge_instance.send_to_shogun("test message")

    assert result is False


# ========================================
# Test: tmux settings configuration
# ========================================


def test_tmux_settings_from_config(mock_tmux_server, tmp_path):
    """Test that tmux settings are correctly loaded from config."""
    settings_content = {
        "bakuhu": {"base_path": str(tmp_path)},
        "tmux": {
            "shogun_session": "my_shogun",
            "multiagent_session": "my_multiagent",
            "shogun_pane": "1.0",
        },
    }
    with patch("libtmux.Server", return_value=mock_tmux_server):
        with patch("builtins.open", mock_open(read_data=yaml.dump(settings_content))):
            from ws.tmux_bridge import TmuxBridge

            bridge = TmuxBridge()

    assert bridge.shogun_session == "my_shogun"
    assert bridge.multiagent_session == "my_multiagent"
    assert bridge.shogun_pane == "1.0"


def test_tmux_settings_defaults_when_missing(mock_tmux_server, tmp_path):
    """Test that default values are used when tmux section is missing."""
    settings_content = {
        "bakuhu": {"base_path": str(tmp_path)},
    }
    with patch("libtmux.Server", return_value=mock_tmux_server):
        with patch("builtins.open", mock_open(read_data=yaml.dump(settings_content))):
            from ws.tmux_bridge import TmuxBridge

            bridge = TmuxBridge()

    assert bridge.shogun_session == "shogun"
    assert bridge.multiagent_session == "multiagent"
    assert bridge.shogun_pane == "0.0"


# ========================================
# Test: _clean_output()
# ========================================

SEPARATOR = "─" * 40


class TestCleanOutput:
    """Tests for TmuxBridge._clean_output static method."""

    def test_single_line_user_input_marked(self):
        """Separator pair with single line user input gets \\x1f marker."""
        text = "\n".join(
            [
                "Claude output line",
                SEPARATOR,
                "❯ hello world",
                SEPARATOR,
                "More Claude output",
            ]
        )
        result = TmuxBridge._clean_output(text)
        lines = result.split("\n")
        assert lines[0] == "Claude output line"
        assert lines[1] == "\x1fhello world"
        assert lines[2] == "More Claude output"

    def test_multiline_user_input_marked(self):
        """Multi-line user input: ❯ on first line, continuation lines also marked."""
        text = "\n".join(
            [
                SEPARATOR,
                "❯ first line",
                "second line",
                "third line",
                SEPARATOR,
            ]
        )
        result = TmuxBridge._clean_output(text)
        lines = result.split("\n")
        assert lines[0] == "\x1ffirst line"
        assert lines[1] == "\x1fsecond line"
        assert lines[2] == "\x1fthird line"
        assert len(lines) == 3

    def test_separator_lines_removed(self):
        """Paired separator lines are removed from output."""
        text = "\n".join(
            [
                "before",
                SEPARATOR,
                "❯ input",
                SEPARATOR,
                "after",
            ]
        )
        result = TmuxBridge._clean_output(text)
        assert SEPARATOR not in result

    def test_claude_output_not_marked(self):
        """Text outside separator pairs has no marker."""
        text = "\n".join(
            [
                "Claude says hello",
                "Another line",
            ]
        )
        result = TmuxBridge._clean_output(text)
        for line in result.split("\n"):
            assert not line.startswith("\x1f")

    def test_status_lines_removed(self):
        """Status lines starting with ⏵ are removed."""
        text = "\n".join(
            [
                "normal line",
                "⏵ status info",
                "another line",
            ]
        )
        result = TmuxBridge._clean_output(text)
        lines = result.split("\n")
        assert len(lines) == 2
        assert lines[0] == "normal line"
        assert lines[1] == "another line"

    def test_hint_lines_removed(self):
        """Hint lines starting with ✢, ✻, or ✽ are removed."""
        text = "\n".join(
            [
                "normal",
                "✢ hint1",
                "✻ hint2",
                "✽ hint3",
                "end",
            ]
        )
        result = TmuxBridge._clean_output(text)
        lines = result.split("\n")
        assert lines == ["normal", "end"]

    def test_unpaired_separator_kept(self):
        """Single separator (no pair) is kept in output as a regular line."""
        text = "\n".join(
            [
                "before",
                SEPARATOR,
                "after",
            ]
        )
        result = TmuxBridge._clean_output(text)
        lines = result.split("\n")
        assert len(lines) == 3
        assert lines[1] == SEPARATOR

    def test_multiple_pairs(self):
        """Multiple separator pairs each mark their own user input."""
        text = "\n".join(
            [
                "Claude output 1",
                SEPARATOR,
                "❯ input 1",
                SEPARATOR,
                "Claude output 2",
                SEPARATOR,
                "❯ input 2",
                SEPARATOR,
            ]
        )
        result = TmuxBridge._clean_output(text)
        lines = result.split("\n")
        assert lines[0] == "Claude output 1"
        assert lines[1] == "\x1finput 1"
        assert lines[2] == "Claude output 2"
        assert lines[3] == "\x1finput 2"

    def test_empty_input(self):
        """Empty string returns empty string."""
        assert TmuxBridge._clean_output("") == ""

    def test_no_separators_passthrough(self):
        """Text without separators passes through (minus noise)."""
        text = "line1\nline2\nline3"
        result = TmuxBridge._clean_output(text)
        assert result == text

    def test_prompt_prefix_stripped(self):
        """❯ prefix is stripped only from user input lines."""
        text = "\n".join(
            [
                SEPARATOR,
                "❯ user typed this",
                SEPARATOR,
            ]
        )
        result = TmuxBridge._clean_output(text)
        assert result == "\x1fuser typed this"

    def test_user_input_without_prompt_prefix(self):
        """Continuation lines without ❯ still get marker."""
        text = "\n".join(
            [
                SEPARATOR,
                "❯ line one",
                "line two no prompt",
                SEPARATOR,
            ]
        )
        result = TmuxBridge._clean_output(text)
        lines = result.split("\n")
        assert lines[0] == "\x1fline one"
        assert lines[1] == "\x1fline two no prompt"

    def test_odd_separators_last_unpaired(self):
        """Odd number of separators: last one unpaired, kept as-is."""
        text = "\n".join(
            [
                SEPARATOR,
                "❯ input",
                SEPARATOR,
                "Claude output",
                SEPARATOR,
            ]
        )
        result = TmuxBridge._clean_output(text)
        lines = result.split("\n")
        assert lines[0] == "\x1finput"
        assert lines[1] == "Claude output"
        assert lines[2] == SEPARATOR


# ========================================
# Test: send_special_key() - New Keys
# ========================================


class TestSendSpecialKeyNewKeys:
    """Tests for send_special_key() with newly added keys."""

    def test_send_special_key_enter(self, bridge_instance):
        """Test sending Enter key."""
        with patch("subprocess.run") as mock_run:
            result = bridge_instance.send_special_key("Enter")
            assert result is True
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "Enter" in args

    def test_send_special_key_tab(self, bridge_instance):
        """Test sending Tab key."""
        with patch("subprocess.run") as mock_run:
            result = bridge_instance.send_special_key("Tab")
            assert result is True
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "Tab" in args

    def test_send_special_key_btab(self, bridge_instance):
        """Test sending BTab (Shift+Tab) key."""
        with patch("subprocess.run") as mock_run:
            result = bridge_instance.send_special_key("BTab")
            assert result is True
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "BTab" in args

    def test_send_special_key_arrow_keys(self, bridge_instance):
        """Test sending arrow keys (Up, Down, Left, Right)."""
        for key in ["Up", "Down", "Left", "Right"]:
            with patch("subprocess.run") as mock_run:
                result = bridge_instance.send_special_key(key)
                assert result is True
                mock_run.assert_called_once()
                args = mock_run.call_args[0][0]
                assert key in args

    def test_send_special_key_numbers(self, bridge_instance):
        """Test sending number keys (0-9)."""
        for num in range(10):
            key = str(num)
            with patch("subprocess.run") as mock_run:
                result = bridge_instance.send_special_key(key)
                assert result is True
                mock_run.assert_called_once()
                args = mock_run.call_args[0][0]
                assert key in args

    def test_send_special_key_yes_no(self, bridge_instance):
        """Test sending y/n keys."""
        for key in ["y", "n"]:
            with patch("subprocess.run") as mock_run:
                result = bridge_instance.send_special_key(key)
                assert result is True
                mock_run.assert_called_once()
                args = mock_run.call_args[0][0]
                assert key in args

    def test_send_special_key_space(self, bridge_instance):
        """Test sending Space key."""
        with patch("subprocess.run") as mock_run:
            result = bridge_instance.send_special_key("Space")
            assert result is True
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "Space" in args

    def test_send_special_key_bspace(self, bridge_instance):
        """Test sending BSpace (Backspace) key."""
        with patch("subprocess.run") as mock_run:
            result = bridge_instance.send_special_key("BSpace")
            assert result is True
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "BSpace" in args

    def test_send_special_key_disallowed_key(self, bridge_instance):
        """Test that disallowed keys raise ValueError."""
        with pytest.raises(ValueError, match="not allowed"):
            bridge_instance.send_special_key("Delete")

    def test_send_special_key_disallowed_key_f1(self, bridge_instance):
        """Test that function keys are not allowed."""
        with pytest.raises(ValueError, match="not allowed"):
            bridge_instance.send_special_key("F1")
