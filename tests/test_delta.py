"""Tests for ws/delta.py delta computation."""

from ws.delta import compute_delta


class TestComputeDelta:
    """Tests for compute_delta function."""

    def test_initial_capture_returns_reset(self):
        """First capture (prev empty) should return reset."""
        prev = []
        curr = ["line1", "line2", "line3"]
        result = compute_delta(prev, curr)
        assert result["type"] == "reset"
        assert result["lines"] == curr

    def test_no_change_returns_noop(self):
        """Identical prev and curr should return noop."""
        prev = ["line1", "line2", "line3"]
        curr = ["line1", "line2", "line3"]
        result = compute_delta(prev, curr)
        assert result["type"] == "noop"

    def test_append_lines_returns_delta(self):
        """Appending new lines to the end should return delta."""
        prev = ["line1", "line2", "line3"]
        curr = ["line1", "line2", "line3", "line4", "line5"]
        result = compute_delta(prev, curr)
        assert result["type"] == "delta"
        assert result["lines"] == ["line4", "line5"]

    def test_single_line_append_returns_delta(self):
        """Appending a single line should return delta."""
        prev = ["line1", "line2"]
        curr = ["line1", "line2", "line3"]
        result = compute_delta(prev, curr)
        assert result["type"] == "delta"
        assert result["lines"] == ["line3"]

    def test_no_common_suffix_returns_reset(self):
        """No common suffix (screen clear) should return reset."""
        prev = ["line1", "line2", "line3"]
        curr = ["different1", "different2"]
        result = compute_delta(prev, curr)
        assert result["type"] == "reset"
        assert result["lines"] == curr

    def test_lines_shrunk_returns_reset(self):
        """Fewer lines (e.g., screen scroll) should return reset."""
        prev = ["line1", "line2", "line3", "line4"]
        curr = ["line3", "line4"]
        result = compute_delta(prev, curr)
        assert result["type"] == "reset"
        assert result["lines"] == curr

    def test_middle_changed_returns_reset(self):
        """Change in the middle (TUI redraw) should return reset."""
        prev = ["line1", "line2", "line3"]
        curr = ["line1", "CHANGED", "line3"]
        result = compute_delta(prev, curr)
        assert result["type"] == "reset"
        assert result["lines"] == curr

    def test_large_append(self):
        """Appending many lines should return delta."""
        prev = ["base"] * 100
        new_lines = [f"new{i}" for i in range(500)]
        curr = prev + new_lines
        result = compute_delta(prev, curr)
        assert result["type"] == "delta"
        assert result["lines"] == new_lines

    def test_empty_to_empty_returns_noop(self):
        """Empty prev and curr should return noop."""
        prev = []
        curr = []
        result = compute_delta(prev, curr)
        assert result["type"] == "noop"

    def test_empty_curr_after_non_empty_prev_returns_reset(self):
        """Clearing screen (empty curr) should return reset."""
        prev = ["line1", "line2"]
        curr = []
        result = compute_delta(prev, curr)
        assert result["type"] == "reset"
        assert result["lines"] == []
