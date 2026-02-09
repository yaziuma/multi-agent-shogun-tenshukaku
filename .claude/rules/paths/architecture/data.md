---
paths:
  - "app/models/**/*.py"
  - "app/repositories/**/*.py"
  - "app/core/db.py"
---
# Data Layer (SQLAlchemy)

## 責務
- モデル定義とデータアクセス。

## ルール
- SQLAlchemy 2.0記法を優先。
- 生SQLは必要最小限、必ずパラメータ化。
- N+1回避のためEager Loadingを検討。
- ここにビジネスルールを置かない。
