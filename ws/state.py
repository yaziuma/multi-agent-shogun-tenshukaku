"""
Pane State Module.

Provides hash-based change detection for tmux pane outputs.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass
class PaneState:
    """pane単位の差分検知（sha1ハッシュ比較）"""

    hashes: dict[str, str] = field(default_factory=dict)

    def diff(self, panes: dict[str, str]) -> dict[str, str]:
        """変更があったpaneのみ返す。初回は全paneが返る。"""
        updates: dict[str, str] = {}
        for pane_id, output in panes.items():
            h = hashlib.sha1(output.encode("utf-8")).hexdigest()
            if self.hashes.get(pane_id) != h:
                self.hashes[pane_id] = h
                updates[pane_id] = output
        return updates

    def get_full_state(self) -> dict[str, str]:
        """現在のハッシュキーの一覧を返す（デバッグ用）"""
        return dict(self.hashes)
