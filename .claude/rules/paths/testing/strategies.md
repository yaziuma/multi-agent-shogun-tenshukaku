---
paths:
  - "tests/**/*.py"
---
# Testing

## 基本方針
- TDDを前提にする（RED→GREEN→IMPROVE）。
- 目標カバレッジは**80%以上**。

## 実行
- `uv run pytest`
- `uv run pytest --cov=app --cov-report=html`

## ルール
- `test_*.py` に配置。
- 非同期は `pytest-asyncio` + `AsyncClient` を使用。
