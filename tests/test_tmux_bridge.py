"""
Unit tests for TmuxBridge module.

These tests run in environments without tmux sessions by using mocks and temporary files.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, mock_open
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
        "bakuhu": {
            "base_path": str(tmp_path)
        }
    }
    return settings_content


@pytest.fixture
def bridge_instance(mock_tmux_server, mock_settings, tmp_path):
    """
    Create a TmuxBridge instance with mocked dependencies.

    This fixture mocks libtmux.Server and settings.yaml loading,
    allowing tests to run without an actual tmux session.
    """
    with patch('libtmux.Server', return_value=mock_tmux_server):
        with patch('builtins.open', mock_open(read_data=yaml.dump(mock_settings))):
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
            {"cmd_id": "cmd_002", "instruction": "Test command 2"}
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
        "commands": [
            {"cmd_id": "cmd_001", "instruction": "First command"}
        ]
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
            {"cmd_id": "cmd_005", "instruction": "Fifth"}
        ]
    }
    with open(yaml_path, "w") as f:
        yaml.dump(existing_data, f)

    # Add new command - should be cmd_006 (max+1)
    cmd_id = bridge_instance.add_command("Sixth command")

    assert cmd_id == "cmd_006"


# ========================================
# Test: capture_karo_pane() (without tmux session)
# ========================================

def test_capture_karo_pane_no_session(bridge_instance):
    """Test capture_karo_pane when tmux session is not available."""
    result = bridge_instance.capture_karo_pane()

    assert result == "Error: multiagent session not found"


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
    """Test send_to_shogun when shogun session is not available."""
    result = bridge_instance.send_to_shogun("test message")

    assert result is False
