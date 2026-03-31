# Alpine.js導入パッチ 修正点まとめ

## 目的
前回PR（`Introduce Alpine.js and x-cloak; migrate tabs and TUI toggle to declarative state`）に対する指摘事項への対応内容を整理する。

## 修正点

### 1. タブ切り替えの宣言化
- `templates/index.html` の `.tab-btn` について、従来のDOM直接操作イベントを廃止。
- `x-data` / `:class` / `x-show` による状態管理へ移行。
- これにより、タブ切替ロジックの責務をマークアップ側に寄せ、命令的JSを削減。

### 2. TUIパネル開閉ロジックの簡素化
- `#tui-panel-toggle` のクリック時に `style.display` を直接操作する処理を廃止。
- `tuiOpen` 状態をAlpineで管理し、`x-show` と `x-text` で表示を制御。
- `Enter` / `Space` キー操作に対応（キーボード操作性を維持）。

### 3. Alpine初期化前のちらつき対策
- `static/style.css` に `[x-cloak]` ルールを追加。
- `x-cloak` 付き要素の初期ちらつき（FOUC）を防止。

### 4. 依存ライブラリの導入方針
- `templates/base.html` に Alpine.js CDN を追加。
- htmxを通信・部分更新の主担当、Alpineを局所UI状態の担当とする役割分離を明確化。

## 影響範囲
- 変更ファイル:
  - `templates/base.html`
  - `templates/index.html`
  - `static/style.css`

## テスト状況
- 実行済み
  - `python -m compileall main.py ws`
- 環境依存で未完了
  - `python -m pytest -q tests/test_api.py`（`httpx` 未導入により収集時エラー）

## 補足
- WebSocket差分処理やxterm連携など、命令型API依存が強い箇所は引き続き素のJSで管理。
- 今後は、フォーム送信や部分更新は `hx-*` に寄せ、UIの局所状態のみをAlpineで扱う方針を継続する。
