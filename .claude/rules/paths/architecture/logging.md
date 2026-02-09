---
paths:
  - "*.py"
---
## パフォーマンス配慮したログ

### logging標準の遅延フォーマットを使用する。

- 誤：`logger.debug(f"unify: {a} {b}")`
- 正：`logger.debug("unify: %r %r", a, b)`
- reprが発生せずパフォーマンスが良い