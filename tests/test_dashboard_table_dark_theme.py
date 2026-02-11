"""
Dashboard Markdown table dark theme CSS verification test.

Verifies that Markdown tables in Rendered mode are visible with
proper contrast on the sengoku washi theme (not pitch black).

cmd_132: Fix for github-markdown-dark.css causing unreadable tables.
"""

import pytest
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:30001"


@pytest.fixture(scope="session")
def browser_context_args():
    """Override default browser context args."""
    return {"ignore_https_errors": True}


def navigate_to_dashboard_rendered(page: Page):
    """Navigate to dashboard tab and ensure Rendered mode is active."""
    page.goto(BASE_URL)
    # Click dashboard tab
    page.click('button[data-tab="dashboard"]')
    # Wait for initial load
    page.wait_for_selector("#dashboard-raw-data", state="attached", timeout=10000)

    # Ensure Rendered mode is active
    mode_toggle = page.locator("#dashboard-mode-toggle")
    if mode_toggle.get_attribute("data-mode") != "rendered":
        mode_toggle.click()
        page.wait_for_timeout(500)


class TestMarkdownTableVisibility:
    """Verify Markdown tables are visible in dark theme."""

    def test_table_exists_in_rendered_mode(self, page: Page):
        """Rendered mode displays table elements."""
        navigate_to_dashboard_rendered(page)

        # Check if any table exists in markdown-body
        display = page.locator("#dashboard-display")
        expect(display).to_have_class("markdown-body")

        # Wait for table to appear (dashboard.md should contain tables)
        # If no table exists, this test will timeout — expected behavior
        table = display.locator("table").first
        expect(table).to_be_visible(timeout=5000)

    def test_table_background_not_pitch_black(self, page: Page):
        """Table background is not pitch black (css verification)."""
        navigate_to_dashboard_rendered(page)

        table = page.locator("#dashboard-display table").first
        expect(table).to_be_visible()

        # Get computed background color
        bg_color = table.evaluate("el => window.getComputedStyle(el).backgroundColor")

        # Pitch black would be rgb(0, 0, 0) or rgba(0, 0, 0, ...)
        # Our theme uses light backgrounds: rgba(255, 255, 255, 0.7)
        # Assert that it's NOT pure black
        assert bg_color != "rgb(0, 0, 0)", f"Table background is pitch black: {bg_color}"
        assert bg_color != "rgba(0, 0, 0, 1)", f"Table background is pitch black: {bg_color}"

        # Additionally, verify it contains light color values
        # Expected: rgba(255, 255, 255, 0.7) or similar light color
        # Simple heuristic: if RGB components exist, at least one should be > 200
        if bg_color.startswith("rgb"):
            import re
            nums = re.findall(r'\d+', bg_color)
            rgb = [int(n) for n in nums[:3]]  # First 3 are R, G, B
            max_component = max(rgb)
            assert max_component > 200, (
                f"Table background too dark (max RGB component {max_component}): {bg_color}"
            )

    def test_table_text_readable_contrast(self, page: Page):
        """Table text has readable contrast (not dark text on dark bg)."""
        navigate_to_dashboard_rendered(page)

        td = page.locator("#dashboard-display table td").first
        expect(td).to_be_visible()

        # Get computed text color
        text_color = td.evaluate("el => window.getComputedStyle(el).color")

        # Dark text on light background is expected
        # Our theme: color: var(--ink) = #2a1b12 (dark brown)
        # Text should NOT be light (e.g., rgb(255, 255, 255))
        # Simple check: RGB components should be relatively low (< 100)
        if text_color.startswith("rgb"):
            import re
            nums = re.findall(r'\d+', text_color)
            rgb = [int(n) for n in nums[:3]]
            max_component = max(rgb)
            # Dark text means low RGB values
            assert max_component < 150, (
                f"Table text too light (max RGB component {max_component}): {text_color}"
            )

    def test_screenshot_rendered_mode(self, page: Page):
        """Capture screenshot of Rendered mode for manual verification."""
        navigate_to_dashboard_rendered(page)

        # Wait a bit for full render
        page.wait_for_timeout(1000)

        # Take full page screenshot
        screenshot_path = "tests/screenshots/cmd_132_rendered.png"
        page.screenshot(path=screenshot_path, full_page=True)

        # Verify screenshot file exists
        import os
        assert os.path.exists(screenshot_path), f"Screenshot not saved: {screenshot_path}"
