---
paths:
  - "app/templates/**/*.html"
  - "static/**/*"
---
# Frontend Layer (htmx + Jinja2)

## ルール
- `base.html` を基点にテンプレート継承。
- htmxの部分更新は `hx-target` / `hx-swap` を明示。
- JSは最小化し、HTML属性で意図を表現する。
- CSSは `static/` にまとめ、テンプレ内の重複を避ける。
