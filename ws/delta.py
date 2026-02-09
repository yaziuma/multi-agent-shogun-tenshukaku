"""Delta calculation module for incremental pane output updates."""

from __future__ import annotations


def compute_delta(
    prev_lines: list[str], curr_lines: list[str]
) -> dict[str, str | list[str]]:
    """
    Compute delta between previous and current pane capture.

    Args:
        prev_lines: Previous capture lines
        curr_lines: Current capture lines

    Returns:
        Dictionary with type and payload:
        - {"type": "reset", "lines": [...]} — Full reset (first capture or screen clear)
        - {"type": "delta", "lines": [...]} — Incremental new lines
        - {"type": "noop"} — No changes
    """
    # Initial capture: send full content (unless both are empty)
    if not prev_lines and not curr_lines:
        return {"type": "noop"}
    if not prev_lines:
        return {"type": "reset", "lines": curr_lines}

    # No changes
    if prev_lines == curr_lines:
        return {"type": "noop"}

    # Check if curr is simply prev + new_lines (typical append case)
    if len(curr_lines) > len(prev_lines):
        # Check if prev matches the beginning of curr
        if curr_lines[: len(prev_lines)] == prev_lines:
            # Perfect append case: return only the new lines
            delta_lines = curr_lines[len(prev_lines) :]
            return {"type": "delta", "lines": delta_lines}

    # Find common suffix length (tail match)
    # This handles cases where scrollback removed old lines
    max_check = min(len(prev_lines), len(curr_lines))
    match_len = 0
    while match_len < max_check:
        if prev_lines[-(match_len + 1)] != curr_lines[-(match_len + 1)]:
            break
        match_len += 1

    # No match at all: screen cleared or major change → full reset
    if match_len == 0:
        return {"type": "reset", "lines": curr_lines}

    # Suffix matches but length shrunk or middle changed: full reset
    # (This handles TUI redraws, screen clears, or scrollback removal)
    return {"type": "reset", "lines": curr_lines}
