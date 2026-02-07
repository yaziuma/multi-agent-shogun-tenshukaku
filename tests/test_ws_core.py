"""
Unit tests for WebSocket core modules (PaneState and DashboardCache).
"""

import time

from ws.dashboard_cache import DashboardCache
from ws.state import PaneState


class TestPaneState:
    """Tests for PaneState.diff() hash-based change detection."""

    def test_diff_initial_returns_all_panes(self):
        """初回は全paneを返却する"""
        state = PaneState()
        panes = {"karo": "output1", "ashigaru1": "output2"}

        result = state.diff(panes)

        assert result == panes
        assert len(state.hashes) == 2

    def test_diff_no_change_returns_empty(self):
        """変更なしは空dictを返却する"""
        state = PaneState()
        panes = {"karo": "output1", "ashigaru1": "output2"}

        # 初回
        state.diff(panes)

        # 2回目（変更なし）
        result = state.diff(panes)

        assert result == {}

    def test_diff_one_pane_changed_returns_only_changed(self):
        """1pane変更時はそのpaneのみ返却する"""
        state = PaneState()
        panes = {"karo": "output1", "ashigaru1": "output2"}

        # 初回
        state.diff(panes)

        # karo のみ変更
        panes["karo"] = "output1_updated"
        result = state.diff(panes)

        assert result == {"karo": "output1_updated"}
        assert "ashigaru1" not in result

    def test_diff_pane_added_returns_new_pane_only(self):
        """pane追加時は新paneのみ返却する"""
        state = PaneState()
        panes = {"karo": "output1"}

        # 初回
        state.diff(panes)

        # ashigaru1 追加
        panes["ashigaru1"] = "output2"
        result = state.diff(panes)

        assert result == {"ashigaru1": "output2"}
        assert "karo" not in result

    def test_get_full_state_returns_current_hashes(self):
        """get_full_state() は現在のハッシュキー一覧を返す"""
        state = PaneState()
        panes = {"karo": "output1", "ashigaru1": "output2"}

        state.diff(panes)
        full_state = state.get_full_state()

        assert "karo" in full_state
        assert "ashigaru1" in full_state
        assert len(full_state) == 2


class TestDashboardCache:
    """Tests for DashboardCache mtime-based caching."""

    def test_read_initial_load(self, tmp_path):
        """ファイル初回読み込み時に内容を返す"""
        dashboard_file = tmp_path / "dashboard.md"
        dashboard_file.write_text("# Test Dashboard\n\nContent")

        cache = DashboardCache(path=dashboard_file)
        result = cache.read()

        assert result == "# Test Dashboard\n\nContent"
        assert cache.last_mtime > 0

    def test_read_no_change_returns_cache(self, tmp_path):
        """mtimeが同一ならキャッシュを返す（再読み込みしない）"""
        dashboard_file = tmp_path / "dashboard.md"
        dashboard_file.write_text("# Test Dashboard\n\nContent")

        cache = DashboardCache(path=dashboard_file)

        # 初回読み込み
        first_result = cache.read()
        first_mtime = cache.last_mtime

        # ファイルを変更せず再度読み込み
        second_result = cache.read()
        second_mtime = cache.last_mtime

        assert first_result == second_result
        assert first_mtime == second_mtime
        assert second_result == "# Test Dashboard\n\nContent"

    def test_read_file_changed_reloads_content(self, tmp_path):
        """ファイル変更時に再読み込みする"""
        dashboard_file = tmp_path / "dashboard.md"
        dashboard_file.write_text("# Test Dashboard\n\nContent")

        cache = DashboardCache(path=dashboard_file)

        # 初回読み込み
        first_result = cache.read()
        first_mtime = cache.last_mtime

        # ファイルを変更（mtimeを確実に変えるため0.1秒待機）
        time.sleep(0.1)
        dashboard_file.write_text("# Updated Dashboard\n\nNew Content")

        # 再度読み込み
        second_result = cache.read()
        second_mtime = cache.last_mtime

        assert first_result != second_result
        assert first_mtime != second_mtime
        assert second_result == "# Updated Dashboard\n\nNew Content"

    def test_read_file_not_found_returns_empty(self, tmp_path):
        """ファイル不在時は空文字列を返す"""
        non_existent_file = tmp_path / "non_existent.md"

        cache = DashboardCache(path=non_existent_file)
        result = cache.read()

        assert result == ""
        assert cache.last_mtime == 0.0
        assert cache.cached_content == ""

    def test_read_file_disappears_returns_empty(self, tmp_path):
        """ファイルが途中で消えた場合も空文字列を返す"""
        dashboard_file = tmp_path / "dashboard.md"
        dashboard_file.write_text("# Test Dashboard\n\nContent")

        cache = DashboardCache(path=dashboard_file)

        # 初回読み込み
        first_result = cache.read()
        assert first_result == "# Test Dashboard\n\nContent"

        # ファイル削除
        dashboard_file.unlink()

        # 再度読み込み
        second_result = cache.read()
        assert second_result == ""
        assert cache.last_mtime == 0.0
