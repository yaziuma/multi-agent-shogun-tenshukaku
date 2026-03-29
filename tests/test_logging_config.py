"""tests/test_logging_config.py - DailyJsonlHandler / setup_logging テスト（古典学派）"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from app.logging_config import DailyJsonlHandler, setup_logging

# ------------------------------------------------------------------ #
# TC-LOG-01: DailyJsonlHandler の emit がファイルに書き込む
# ------------------------------------------------------------------ #


class TestDailyJsonlHandlerEmit:
    def test_emit_writes_jsonl_file(self, tmp_path: Path) -> None:
        """emit() が今日の日付.jsonl ファイルを作成し、内容を書き込む"""
        handler = DailyJsonlHandler(log_dir=tmp_path)
        handler.setFormatter(logging.Formatter("%(message)s"))

        record = logging.LogRecord(
            name="bakuhu.audit",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=json.dumps({"action": "test_event", "peer_id": "peer-a"}),
            args=(),
            exc_info=None,
        )
        handler.emit(record)

        # ファイルが作成されているか
        jsonl_files = list(tmp_path.glob("*.jsonl"))
        assert len(jsonl_files) == 1, "JSONL ファイルが1つ作成されるべき"

        # 内容が正しいか（改行区切り）
        content = jsonl_files[0].read_text()
        lines = [line for line in content.splitlines() if line.strip()]
        assert len(lines) == 1

        parsed = json.loads(lines[0])
        assert parsed["action"] == "test_event"
        assert parsed["peer_id"] == "peer-a"

    def test_emit_appends_multiple_records(self, tmp_path: Path) -> None:
        """複数回 emit すると行が追記される"""
        handler = DailyJsonlHandler(log_dir=tmp_path)
        handler.setFormatter(logging.Formatter("%(message)s"))

        for i in range(3):
            record = logging.LogRecord(
                name="bakuhu.audit",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg=json.dumps({"seq": i}),
                args=(),
                exc_info=None,
            )
            handler.emit(record)

        jsonl_files = list(tmp_path.glob("*.jsonl"))
        assert len(jsonl_files) == 1

        lines = [
            line for line in jsonl_files[0].read_text().splitlines() if line.strip()
        ]
        assert len(lines) == 3
        seqs = [json.loads(line)["seq"] for line in lines]
        assert seqs == [0, 1, 2]

    def test_log_dir_created_automatically(self, tmp_path: Path) -> None:
        """存在しないディレクトリでも自動作成される"""
        nested = tmp_path / "a" / "b" / "c"
        assert not nested.exists()

        handler = DailyJsonlHandler(log_dir=nested)
        assert nested.exists(), "ディレクトリが自動作成されるべき"

        # emit が成功する
        handler.setFormatter(logging.Formatter("%(message)s"))
        record = logging.LogRecord(
            name="bakuhu.audit",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
        handler.emit(record)
        assert len(list(nested.glob("*.jsonl"))) == 1


# ------------------------------------------------------------------ #
# TC-LOG-02: setup_logging() で bakuhu.audit が DailyJsonlHandler を持つ
# ------------------------------------------------------------------ #


class TestSetupLoggingAuditLogger:
    def test_audit_logger_has_daily_jsonl_handler(self, tmp_path: Path) -> None:
        """setup_logging() 後に bakuhu.audit に DailyJsonlHandler が追加されている"""
        # テスト間干渉を避けるため既存ハンドラをリセット
        audit = logging.getLogger("bakuhu.audit")
        audit.handlers.clear()

        setup_logging(log_dir=tmp_path)

        handler_types = [type(h) for h in audit.handlers]
        assert DailyJsonlHandler in handler_types, (
            "bakuhu.audit に DailyJsonlHandler が設定されるべき"
        )

    def test_audit_propagate_is_false(self, tmp_path: Path) -> None:
        """setup_logging() 後に bakuhu.audit の propagate が False"""
        audit = logging.getLogger("bakuhu.audit")
        audit.handlers.clear()
        audit.propagate = True  # 意図的に True にしてから確認

        setup_logging(log_dir=tmp_path)

        assert audit.propagate is False, (
            "bakuhu.audit.propagate は False でなければならない"
        )

    def test_audit_log_not_written_to_stdout(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """propagate=False により audit ログが root logger (stdout) に流れない"""
        audit = logging.getLogger("bakuhu.audit")
        audit.handlers.clear()

        setup_logging(log_dir=tmp_path)

        audit.info(json.dumps({"action": "propagate_test"}))

        captured = capsys.readouterr()
        assert "propagate_test" not in captured.out, (
            "audit ログが stdout に混入してはならない"
        )

    def test_setup_logging_idempotent(self, tmp_path: Path) -> None:
        """setup_logging() を複数回呼んでも DailyJsonlHandler が重複追加されない"""
        audit = logging.getLogger("bakuhu.audit")
        audit.handlers.clear()

        setup_logging(log_dir=tmp_path)
        setup_logging(log_dir=tmp_path)

        daily_handlers = [h for h in audit.handlers if isinstance(h, DailyJsonlHandler)]
        assert len(daily_handlers) == 1, "DailyJsonlHandler は重複追加されてはならない"

    def test_root_logger_still_has_stream_handler(self, tmp_path: Path) -> None:
        """setup_logging() 後も root logger の StreamHandler が維持されている"""
        root = logging.getLogger()
        root.handlers.clear()

        setup_logging(log_dir=tmp_path)

        stream_handlers = [
            h
            for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, DailyJsonlHandler)
        ]
        assert len(stream_handlers) >= 1, (
            "root logger の StreamHandler が維持されるべき"
        )

    def test_default_log_dir_resolves(self) -> None:
        """log_dir=None のとき、デフォルトパスが project_root/logs/inter-bakuhu に解決される"""
        audit = logging.getLogger("bakuhu.audit")
        audit.handlers.clear()

        setup_logging()  # log_dir 省略（デフォルト）

        daily_handlers = [h for h in audit.handlers if isinstance(h, DailyJsonlHandler)]
        assert len(daily_handlers) == 1

        # デフォルトパスが project root / logs / inter-bakuhu であること
        handler_dir = daily_handlers[0].log_dir
        assert handler_dir.name == "inter-bakuhu"
        assert handler_dir.parent.name == "logs"
