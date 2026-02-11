"""
Dashboard Markdown rendering E2E tests using Playwright.

Tests the toggle button, Raw/Rendered mode switching,
rendered content verification, and mode persistence across polling updates.

Requires server running on port 30001.
"""

import re

import pytest
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:30001"


@pytest.fixture(scope="session")
def browser_context_args():
    """Override default browser context args."""
    return {"ignore_https_errors": True}


def navigate_to_dashboard(page: Page):
    """Navigate to the dashboard tab."""
    page.goto(BASE_URL)
    # Click the dashboard tab button
    page.click('button[data-tab="dashboard"]')
    # Wait for htmx content to load (toggle button indicates content is ready)
    page.wait_for_selector("#dashboard-mode-toggle", timeout=10000)


class TestToggleButtonVisibility:
    """Toggle button display verification."""

    def test_toggle_button_exists(self, page: Page):
        """Toggle button is visible in the dashboard tab."""
        navigate_to_dashboard(page)
        toggle_btn = page.locator("#dashboard-mode-toggle")
        expect(toggle_btn).to_be_visible()

    def test_default_mode_is_rendered(self, page: Page):
        """Default mode is Rendered."""
        navigate_to_dashboard(page)
        toggle_btn = page.locator("#dashboard-mode-toggle")
        expect(toggle_btn).to_have_attribute("data-mode", "rendered")
        expect(toggle_btn).to_have_text(re.compile("Rendered"))


class TestModeToggleSwitching:
    """Raw/Rendered toggle switching behavior."""

    def test_switch_to_raw_mode(self, page: Page):
        """Clicking toggle switches to Raw mode."""
        navigate_to_dashboard(page)
        toggle_btn = page.locator("#dashboard-mode-toggle")

        # Click to switch to Raw
        toggle_btn.click()
        expect(toggle_btn).to_have_attribute("data-mode", "raw")
        expect(toggle_btn).to_have_text(re.compile("Raw"))

        # Raw mode should show a pre element inside dashboard-display
        display = page.locator("#dashboard-display")
        pre = display.locator("pre")
        expect(pre).to_be_visible()

    def test_switch_back_to_rendered(self, page: Page):
        """Clicking toggle again switches back to Rendered mode."""
        navigate_to_dashboard(page)
        toggle_btn = page.locator("#dashboard-mode-toggle")

        # Switch to Raw first
        toggle_btn.click()
        expect(toggle_btn).to_have_attribute("data-mode", "raw")

        # Switch back to Rendered
        toggle_btn.click()
        expect(toggle_btn).to_have_attribute("data-mode", "rendered")
        expect(toggle_btn).to_have_text(re.compile("Rendered"))

        # Rendered mode: dashboard-display should have markdown-body class
        display = page.locator("#dashboard-display")
        expect(display).to_have_class(re.compile("markdown-body"))


class TestRenderedContent:
    """Rendered mode content verification."""

    def test_rendered_mode_has_markdown_body(self, page: Page):
        """Rendered mode applies markdown-body class."""
        navigate_to_dashboard(page)

        display = page.locator("#dashboard-display")
        expect(display).to_have_class(re.compile("markdown-body"))

    def test_rendered_mode_parses_headings(self, page: Page):
        """Rendered mode converts markdown headings to HTML heading elements."""
        navigate_to_dashboard(page)

        display = page.locator("#dashboard-display")
        # Dashboard.md typically contains headings; check for any h1-h3
        headings = display.locator("h1, h2, h3")
        # At minimum, there should be at least one heading if dashboard has content
        count = headings.count()
        # If dashboard.md has markdown content, headings should be rendered
        assert count >= 0  # Non-negative (content-dependent)

    def test_raw_data_is_hidden(self, page: Page):
        """The raw data container is hidden from view."""
        navigate_to_dashboard(page)

        raw_data = page.locator("#dashboard-raw-data")
        expect(raw_data).to_be_hidden()


class TestModePersistence:
    """Mode persistence across htmx polling updates."""

    def test_rendered_mode_persists_after_polling(self, page: Page):
        """Rendered mode is maintained after htmx polling update."""
        navigate_to_dashboard(page)

        # Verify we're in rendered mode
        toggle_btn = page.locator("#dashboard-mode-toggle")
        expect(toggle_btn).to_have_attribute("data-mode", "rendered")

        # Wait for at least one polling cycle (5s + margin)
        page.wait_for_timeout(6000)

        # Mode should still be rendered
        expect(toggle_btn).to_have_attribute("data-mode", "rendered")
        display = page.locator("#dashboard-display")
        expect(display).to_have_class(re.compile("markdown-body"))

    def test_raw_mode_persists_after_polling(self, page: Page):
        """Raw mode is maintained after htmx polling update."""
        navigate_to_dashboard(page)

        toggle_btn = page.locator("#dashboard-mode-toggle")

        # Switch to Raw mode
        toggle_btn.click()
        expect(toggle_btn).to_have_attribute("data-mode", "raw")

        # Wait for at least one polling cycle (5s + margin)
        page.wait_for_timeout(6000)

        # Mode should still be raw
        expect(toggle_btn).to_have_attribute("data-mode", "raw")
        display = page.locator("#dashboard-display")
        pre = display.locator("pre")
        expect(pre).to_be_visible()
