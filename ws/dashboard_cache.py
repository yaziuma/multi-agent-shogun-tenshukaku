"""
Dashboard Cache Module.

Provides mtime-based caching for dashboard.md file reads.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DashboardCache:
    """dashboard.md の mtime ベースキャッシュ"""

    path: Path
    last_mtime: float = 0.0
    cached_content: str = ""

    def read(self) -> str:
        """mtimeが変わっていなければキャッシュを返す"""
        try:
            stat = os.stat(self.path)
            if stat.st_mtime != self.last_mtime:
                self.cached_content = self.path.read_text(encoding="utf-8")
                self.last_mtime = stat.st_mtime
        except FileNotFoundError:
            self.cached_content = ""
            self.last_mtime = 0.0
        return self.cached_content
