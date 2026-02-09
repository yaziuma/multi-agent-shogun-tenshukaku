"""
Unit tests for sanitize_pane_text function.

Tests that the sanitize function correctly removes ANSI escape sequences,
rule lines (──, ━, etc.), and trailing blank lines.
"""

from ws.tmux_bridge import sanitize_pane_text


class TestSanitizePaneText:
    """Tests for sanitize_pane_text function."""

    def test_ansi_escape_removal(self):
        """ANSI escape sequences should be removed."""
        text = "Hello \x1b[31mred\x1b[0m world"
        result = sanitize_pane_text(text)
        assert result == "Hello red world"

    def test_ansi_escape_complex(self):
        """Complex ANSI sequences should be removed."""
        text = "\x1b[1;32mBold Green\x1b[0m normal \x1b[48;5;214mOrange BG\x1b[0m"
        result = sanitize_pane_text(text)
        assert result == "Bold Green normal Orange BG"

    def test_rule_line_removal_hyphen(self):
        """Rule lines with hyphens (---×20) should be removed."""
        text = "Before\n" + "-" * 20 + "\nAfter"
        result = sanitize_pane_text(text)
        assert result == "Before\nAfter"

    def test_rule_line_removal_box_drawing(self):
        """Rule lines with box drawing chars (─━―) should be removed."""
        text = "Before\n" + "─" * 30 + "\nAfter"
        result = sanitize_pane_text(text)
        assert result == "Before\nAfter"

    def test_rule_line_removal_heavy(self):
        """Rule lines with heavy box drawing (━) should be removed."""
        text = "Before\n" + "━" * 15 + "\nAfter"
        result = sanitize_pane_text(text)
        assert result == "Before\nAfter"

    def test_rule_line_removal_wave_dash(self):
        """Rule lines with wave dash (―) should be removed."""
        text = "Before\n" + "―" * 25 + "\nAfter"
        result = sanitize_pane_text(text)
        assert result == "Before\nAfter"

    def test_consecutive_rule_lines_removed(self):
        """Multiple consecutive rule lines should be removed."""
        text = "Before\n" + "-" * 20 + "\n" + "─" * 20 + "\n" + "━" * 20 + "\nAfter"
        result = sanitize_pane_text(text)
        assert result == "Before\nAfter"

    def test_rule_line_with_whitespace(self):
        """Rule lines with surrounding whitespace should be removed."""
        text = "Before\n  " + "─" * 20 + "  \nAfter"
        result = sanitize_pane_text(text)
        assert result == "Before\nAfter"

    def test_short_hyphen_line_kept(self):
        """Short hyphen lines (<10 chars) should be kept."""
        text = "Before\n-----\nAfter"
        result = sanitize_pane_text(text)
        assert result == "Before\n-----\nAfter"

    def test_mixed_rule_characters(self):
        """Mixed rule characters in same line should be removed."""
        text = "Before\n─━―─━―─━―─\nAfter"
        result = sanitize_pane_text(text)
        assert result == "Before\nAfter"

    def test_normal_text_preserved(self):
        """Normal text should be preserved."""
        text = "Hello world\nThis is a test\nEnd of text"
        result = sanitize_pane_text(text)
        assert result == text

    def test_trailing_blank_lines_removed(self):
        """Trailing blank lines should be removed."""
        text = "Line 1\nLine 2\n\n\n"
        result = sanitize_pane_text(text)
        assert result == "Line 1\nLine 2"

    def test_trailing_whitespace_lines_removed(self):
        """Trailing whitespace-only lines should be removed."""
        text = "Line 1\nLine 2\n   \n\t\n"
        result = sanitize_pane_text(text)
        assert result == "Line 1\nLine 2"

    def test_middle_blank_lines_preserved(self):
        """Blank lines in the middle should be preserved."""
        text = "Line 1\n\nLine 2"
        result = sanitize_pane_text(text)
        assert result == "Line 1\n\nLine 2"

    def test_empty_input(self):
        """Empty string should return empty string."""
        result = sanitize_pane_text("")
        assert result == ""

    def test_only_blank_lines(self):
        """Input with only blank lines should return empty string."""
        text = "\n\n\n"
        result = sanitize_pane_text(text)
        assert result == ""

    def test_only_rule_lines(self):
        """Input with only rule lines should return empty string."""
        text = "-" * 20 + "\n" + "─" * 30
        result = sanitize_pane_text(text)
        assert result == ""

    def test_combined_ansi_and_rules(self):
        """ANSI escapes and rule lines should both be removed."""
        text = "Normal\n" + "\x1b[31mRed text\x1b[0m\n" + "-" * 30 + "\n" + "After rule"
        result = sanitize_pane_text(text)
        assert result == "Normal\nRed text\nAfter rule"

    def test_line_trailing_whitespace_trimmed(self):
        """Trailing whitespace on each line should be trimmed."""
        text = "Line 1   \nLine 2\t\t\nLine 3"
        result = sanitize_pane_text(text)
        assert result == "Line 1\nLine 2\nLine 3"

    def test_realistic_tmux_output(self):
        """Realistic tmux output with ANSI, rules, and trailing blanks."""
        text = (
            "\x1b[1;32m承知つかまつった。\x1b[0m\n"
            + "─" * 40
            + "\n"
            + "Task completed\n"
            + "━" * 40
            + "\n"
            + "Next step\n"
            + "\n"
            + "\n"
        )
        result = sanitize_pane_text(text)
        assert result == "承知つかまつった。\nTask completed\nNext step"

    def test_preserves_content_lines_with_hyphens(self):
        """Lines with hyphens as content (not rules) should be preserved."""
        text = "Command: ls -la\nOption: --verbose\nEnd"
        result = sanitize_pane_text(text)
        assert result == text

    def test_unicode_content_preserved(self):
        """Unicode content should be preserved."""
        text = "承知つかまつった。\n作業を開始する。\n完了いたした。"
        result = sanitize_pane_text(text)
        assert result == text
