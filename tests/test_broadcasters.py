"""Tests for ws/broadcasters.py components."""


from ws.broadcasters import AdaptivePoller


class TestAdaptivePoller:
    """Tests for AdaptivePoller."""

    def test_on_change_resets_interval(self):
        """on_change() should reset interval to base."""
        poller = AdaptivePoller(
            base_interval=1.0, max_interval=5.0, no_change_threshold=2
        )
        # Increase interval artificially
        poller.current_interval = 4.0
        poller.no_change_count = 3

        # Trigger on_change
        poller.on_change()

        assert poller.current_interval == 1.0
        assert poller.no_change_count == 0

    def test_on_no_change_increases_after_threshold(self):
        """on_no_change() should increase interval after threshold."""
        poller = AdaptivePoller(
            base_interval=1.0, max_interval=10.0, no_change_threshold=2
        )

        # First no-change: below threshold
        poller.on_no_change()
        assert poller.current_interval == 1.0
        assert poller.no_change_count == 1

        # Second no-change: reach threshold
        poller.on_no_change()
        assert poller.current_interval == 2.0  # doubled
        assert poller.no_change_count == 2

        # Third no-change: continue doubling
        poller.on_no_change()
        assert poller.current_interval == 4.0
        assert poller.no_change_count == 3

    def test_on_no_change_respects_max_interval(self):
        """on_no_change() should not exceed max_interval."""
        poller = AdaptivePoller(
            base_interval=1.0, max_interval=5.0, no_change_threshold=2
        )

        # Trigger no-change until max is reached
        poller.on_no_change()
        poller.on_no_change()  # 2.0
        assert poller.current_interval == 2.0

        poller.on_no_change()  # 4.0
        assert poller.current_interval == 4.0

        poller.on_no_change()  # would be 8.0, but capped at 5.0
        assert poller.current_interval == 5.0

        poller.on_no_change()  # still 5.0
        assert poller.current_interval == 5.0

    def test_initial_interval_is_base(self):
        """Initial current_interval should equal base_interval."""
        poller = AdaptivePoller(
            base_interval=2.5, max_interval=10.0, no_change_threshold=3
        )
        assert poller.current_interval == 2.5


# Note: Full integration tests for MonitorBroadcaster and ShogunBroadcaster
# would require mocking TmuxBridge and TmuxRuntime, which is beyond
# the scope of this unit test. The above tests cover the critical
# AdaptivePoller logic.
