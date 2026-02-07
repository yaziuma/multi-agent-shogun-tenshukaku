"""
Unit tests for TmuxBridge module.

These tests run in environments without tmux sessions by using mocks and temporary files.
"""

import subprocess
from unittest.mock import Mock, mock_open, patch

import pytest
import yaml


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


class TestCleanOutput:
    """Tests for _clean_output() prompt line removal."""

    def test_removes_separator_lines(self):
        """区切り線（─の連続）が除去されること"""
        from ws.tmux_bridge import _clean_output

        text = "Line 1\n─────────────────────\nLine 2"
        result = _clean_output(text)
        assert result == "Line 1\nLine 2"

    def test_removes_prompt_lines(self):
        """プロンプト行（❯）が除去されること"""
        from ws.tmux_bridge import _clean_output

        text = "Output line\n❯ prompt here\nMore output"
        result = _clean_output(text)
        assert result == "Output line\nMore output"

    def test_removes_status_lines(self):
        """ステータス行（⏵を含む）が除去されること"""
        from ws.tmux_bridge import _clean_output

        text = "Working...\n  ⏵⏵ bypass permissions on\nDone"
        result = _clean_output(text)
        assert result == "Working...\nDone"

    def test_preserves_normal_output(self):
        """通常の出力（日本語テキスト、コードブロック等）が保持されること"""
        from ws.tmux_bridge import _clean_output

        text = "日本語テキスト\ndef foo():\n    return 42\n結果: 完了"
        result = _clean_output(text)
        assert result == text

    def test_handles_empty_input(self):
        """空の入力でエラーにならないこと"""
        from ws.tmux_bridge import _clean_output

        result = _clean_output("")
        assert result == ""

    def test_trims_trailing_empty_lines(self):
        """末尾の空行がトリムされること"""
        from ws.tmux_bridge import _clean_output

        text = "Line 1\nLine 2\n\n\n"
        result = _clean_output(text)
        assert result == "Line 1\nLine 2"

    def test_complex_prompt_removal(self):
        """複数のプロンプト要素が混在する場合も正しく除去されること"""
        from ws.tmux_bridge import _clean_output

        text = (
            "Output line 1\n"
            "─────────────────────\n"
            "❯ user prompt\n"
            "  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
            "Output line 2\n"
            "─────────────────────\n"
            "\n"
        )
        result = _clean_output(text)
        assert result == "Output line 1\nOutput line 2"
