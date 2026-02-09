---
paths:
  - "app/services/**/*.py"
---
# Service Layer

## 責務
- 仕様・ビジネスルールの実装。
- トランザクション境界の設計。

## ルール
- FastAPIの `Request/Response` に依存しない。
- DBアクセスはリポジトリ経由。
- 例外は意味のあるドメイン例外に寄せる。
