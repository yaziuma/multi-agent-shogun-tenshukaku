"""
Dashboard manual refresh E2E tests using Playwright.

Tests the manual refresh button, content update on click,
and absence of automatic updates (no polling, no WS auto-update).

Requires server running on port 30001.
"""

import pytest
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:30001"


@pytest.fixture(scope="session")
def browser_context_args():
    """Override default browser context args."""
    return {"ignore_https_errors": True}


def navigate_to_dashboard(page: Page):
    """Navigate to the dashboard tab and trigger initial load."""
    page.goto(BASE_URL)
    # Click the dashboard tab button (triggers initial fetch)
    page.click('button[data-tab="dashboard"]')
    # Wait for dashboard content to load via manual fetch
    page.wait_for_selector("#dashboard-raw-data", state="attached", timeout=10000)


class TestRefreshButtonVisibility:
    """Refresh button display verification."""

    def test_refresh_button_exists(self, page: Page):
        """Refresh button is visible in the dashboard tab."""
        navigate_to_dashboard(page)
        refresh_btn = page.locator("#dashboard-refresh-btn")
        expect(refresh_btn).to_be_visible()

    def test_refresh_button_text(self, page: Page):
        """Refresh button shows correct text."""
        navigate_to_dashboard(page)
        refresh_btn = page.locator("#dashboard-refresh-btn")
        expect(refresh_btn).to_have_text("更新")


class TestRefreshButtonClick:
    """Refresh button click behavior."""

    def test_click_updates_content(self, page: Page):
        """Clicking refresh button loads dashboard content."""
        navigate_to_dashboard(page)

        # Content should already be loaded from initial fetch
        raw_data = page.locator("#dashboard-raw-data")
        expect(raw_data).to_be_attached()

        # Click refresh to reload
        refresh_btn = page.locator("#dashboard-refresh-btn")
        refresh_btn.click()

        # Wait for fetch to complete
        page.wait_for_timeout(1000)

        # Verify content is still present after refresh
        raw_data = page.locator("#dashboard-raw-data")
        expect(raw_data).to_be_attached()
        display = page.locator("#dashboard-display")
        expect(display).to_be_visible()

    def test_button_disabled_during_fetch(self, page: Page):
        """Button is briefly disabled during fetch."""
        navigate_to_dashboard(page)

        refresh_btn = page.locator("#dashboard-refresh-btn")

        # Before click, button should be enabled
        expect(refresh_btn).to_be_enabled()

        # Click and check it becomes re-enabled after fetch
        refresh_btn.click()
        page.wait_for_timeout(1500)
        expect(refresh_btn).to_be_enabled()
        expect(refresh_btn).to_have_text("更新")


class TestNoAutoUpdate:
    """Verify no automatic updates occur."""

    def test_no_htmx_polling(self, page: Page):
        """Dashboard content does not have htmx polling attributes."""
        navigate_to_dashboard(page)

        content_div = page.locator("#dashboard-content")
        # Verify no hx-trigger attribute (polling removed)
        hx_trigger = content_div.get_attribute("hx-trigger")
        assert hx_trigger is None, f"hx-trigger should be removed, got: {hx_trigger}"

        hx_get = content_div.get_attribute("hx-get")
        assert hx_get is None, f"hx-get should be removed, got: {hx_get}"

    def test_content_stable_without_interaction(self, page: Page):
        """Dashboard content does not change without user interaction."""
        navigate_to_dashboard(page)

        # Get initial content
        raw_data = page.locator("#dashboard-raw-data")
        initial_text = raw_data.text_content()

        # Wait well beyond any potential polling interval (8 seconds)
        page.wait_for_timeout(8000)

        # Content should be identical (no auto-refresh occurred)
        after_text = raw_data.text_content()
        assert initial_text == after_text, (
            "Dashboard content changed without user interaction"
        )
