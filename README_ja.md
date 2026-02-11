# multi-agent-shogun-tenshukaku

> [yohey-w/multi-agent-shogun](https://github.com/yohey-w/multi-agent-shogun) およびそのfork向けに開発されたWeb制御パネル。`config/settings.yaml` の設定変更のみで multi-agent-shogun 系システム全般に対応。

マルチエージェント統制システムのためのWeb制御パネル。天守閣 — 城主が戦場全体を見渡す司令塔にちなんで命名。

![指揮タブ](assets/screenshots/tab-command.png)

## 概要

天守閣は、tmux上で稼働する複数のAIエージェント（Claude Codeインスタンス）を、ブラウザから指揮・監視するためのWebインターフェースである。ターミナルのペインを切り替える代わりに、殿（人間オペレータ）は単一のWebページから指示送信、全エージェント監視、ダッシュボード閲覧、コマンド履歴の確認が可能。

## 機能

### 指揮タブ

将軍エージェントのtmuxペインに直接メッセージを送信する。Ctrl+Enterによるクイック送信と、Claude Codeの割り込みに使うEscapeキー送信ボタンを備える。Top/Bottomスクロールボタンで長い出力のナビゲーションが可能。

折りたたみ式の **TUI操作パネル** から、方向キー、Enter、Tab、Space、Backspace、数字キー（0-9）、Yes/No確認ボタンなどのキーボード入力を直接送信可能。ブラウザを離れることなく対話型CLIインターフェースを操作できる。決定系キー（Enter、Escape、Yes、No）は誤操作防止のため1秒長押しで発動する。

**会話ログ** セクションでは、対話形式のビューを表示する。ユーザーの送信メッセージは青色、将軍の応答は金色で表示される。tmuxペインの生出力は会話ログの下の折りたたみセクションで確認可能。

![指揮タブ](assets/screenshots/tab-command.png)

### 監視タブ

全エージェントペインをグリッドレイアウトでリアルタイム表示。WebSocketデルタ更新により効率的な帯域使用を実現。更新間隔は設定可能（デフォルト5秒）。**表示クリア** ボタンでtmuxペイン履歴に影響を与えずに表示をリセット可能（非破壊的）。ユーザー入力行はライトブルーでハイライトされ、視認性が高い。

![監視タブ](assets/screenshots/tab-monitor.png)

### 戦況タブ

`dashboard.md` の戦況報告書をレンダリング。タスク進行状況、ブロッカー、スキル候補、本日の戦果を表示。コンテンツは手動 **更新** ボタンによるオンデマンド読み込み（不要なAPIコールを削減するため自動更新は廃止）。

**Raw/Renderedトグル** による2つの表示モードに対応:
- **Renderedモード**（デフォルト）: [marked.js](https://marked.js.org/) と [github-markdown-css](https://github.com/sindresorhus/github-markdown-css) を使用してMarkdownをパース。テーブル、見出し、コードブロック、引用など各要素に戦国テーマのカスタムCSS適用。
- **Rawモード**: 元のMarkdownソーステキストをそのまま表示。

![戦況タブ](assets/screenshots/tab-dashboard.png)

### 履歴タブ

コマンドキュー（`shogun_to_karo.yaml`）を展開可能な詳細付きで一覧表示。一括開閉ボタン付き。

![履歴タブ](assets/screenshots/tab-history.png)

## アーキテクチャ

```
ブラウザ (HTTP + WebSocket)
    │
    ├── GET  /              → メインSPA（Jinja2テンプレート + htmx）
    ├── POST /api/command   → tmux send-keys で将軍ペインに送信
    ├── POST /api/special-key → 特殊キー送信（許可リスト方式）
    ├── POST /api/monitor/clear → 監視表示クリア（非破壊的）
    ├── GET  /api/dashboard → dashboard.md 読み取り（データコンテナで生markdown返却）
    ├── GET  /api/history   → shogun_to_karo.yaml 読み取り
    ├── GET  /api/ws-config → WebSocket再接続設定
    ├── WS   /ws            → 将軍ペインのリアルタイム出力（デルタ配信）
    └── WS   /ws/monitor    → 全ペインリアルタイム監視（デルタ配信）
    │
    ▼
FastAPI + Uvicorn
    │
    ▼
TmuxBridge (libtmux)
    │
    ▼
tmuxセッション (shogun / multiagent)
```

### 技術スタック

| 要素 | 技術 |
|------|------|
| バックエンド | FastAPI + Uvicorn |
| テンプレート | Jinja2 |
| フロントエンド | htmx 2.x + Vanilla JS |
| WebSocket | FastAPI ネイティブ WebSocket（デルタ差分配信） |
| Markdownレンダリング | marked.js + github-markdown-css |
| tmux連携 | libtmux 0.53+ |
| スタイリング | カスタムCSS（戦国テーマ） |
| パッケージ管理 | uv |

### WebSocket再接続

WebSocket接続は `ReconnectingWebSocket` クラスにより以下の機能を提供:
- 指数バックオフによる自動再接続（1秒〜30秒）
- 最大3回のリトライ後に手動 **再接続** ボタンを表示
- 瞬断非表示のためのUI表示遅延
- 全閾値を `settings.yaml` から `/api/ws-config` 経由で取得（ハードコード禁止）

## セットアップ

### 前提条件

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) パッケージマネージャ
- `shogun` および `multiagent` セッションが稼働中のtmux（[multi-agent-bakuhu](https://github.com/yaziuma/multi-agent-bakuhu) から起動）

### インストール

```bash
git clone https://github.com/yaziuma/multi-agent-shogun-tenshukaku.git
cd multi-agent-shogun-tenshukaku

# 依存関係のインストール
uv sync
```

### 設定

`config/settings.yaml` を編集:

```yaml
server:
  host: "0.0.0.0"
  port: 30001

bakuhu:
  base_path: "/path/to/multi-agent-bakuhu"

tmux:
  shogun_session: "shogun"
  multiagent_session: "multiagent"
  shogun_pane: "0.0"

runtime:
  thread_pool_workers: 2

monitor:
  base_interval_ms: 5000
  max_interval_ms: 10000
  no_change_threshold: 2

shogun:
  base_interval_ms: 1000
  max_interval_ms: 3000
  no_change_threshold: 2

ui:
  user_input_color: "#4FC3F7"
```

### 起動

```bash
# 起動スクリプト使用（推奨 — プロセス管理・ヘルスチェック付き）
./start.sh

# 開発用再起動（キャッシュ完全削除 + ホットリロード）
./restart.sh

# 手動起動
uv run uvicorn main:app --host 0.0.0.0 --port 30001
```

`http://<ホスト>:30001` でアクセス。

## プロジェクト構成

```
multi-agent-shogun-tenshukaku/
├── main.py                  # FastAPIアプリケーション & APIルート
├── ws/
│   ├── broadcasters.py     # ブロードキャストマネージャ（将軍 + 監視）
│   ├── dashboard_cache.py  # mtime ベースのダッシュボードキャッシュ
│   ├── delta.py            # WebSocket更新用デルタ差分計算
│   ├── handlers.py         # WebSocketハンドラ（将軍 + 監視）
│   ├── runtime.py          # スレッドプール + 非同期ロック
│   ├── state.py            # ペイン状態の差分検出（sha1）
│   └── tmux_bridge.py      # tmuxセッション操作レイヤー
├── templates/
│   ├── base.html            # ベーステンプレート（ヘッダ、フッタ、CDNアセット）
│   ├── index.html           # メインSPA（4タブ + JS）
│   └── partials/
│       ├── history.html     # コマンド履歴パーシャル
│       ├── output.html      # ペイン出力パーシャル
│       └── status.html      # ステータス表示パーシャル
├── static/
│   └── style.css            # 戦国テーマCSS（Markdownオーバーライド含む）
├── config/
│   └── settings.yaml        # サーバー・bakuhuパス・tmux・監視設定
├── tests/
│   ├── test_api.py                      # APIエンドポイントテスト
│   ├── test_broadcasters.py             # ブロードキャスターテスト
│   ├── test_dashboard_markdown.py       # ダッシュボードMarkdownレンダリングテスト（Playwright）
│   ├── test_dashboard_refresh.py        # ダッシュボード手動更新テスト（Playwright）
│   ├── test_dashboard_table_dark_theme.py # テーブルダークテーマCSSテスト（Playwright）
│   ├── test_delta.py                    # デルタ差分計算テスト
│   ├── test_monitor.py                  # 監視WebSocketテスト
│   ├── test_sanitize.py                 # 入力サニタイズテスト
│   ├── test_tmux_bridge.py              # TmuxBridgeユニットテスト
│   ├── test_ws_core.py                  # PaneState・DashboardCacheテスト
│   └── test_ws_endpoints.py             # WebSocketエンドポイントテスト
├── start.sh                 # 安全起動スクリプト
├── restart.sh               # 開発用再起動スクリプト
├── pyproject.toml           # プロジェクトメタデータ & 依存関係
└── assets/
    └── screenshots/         # UIスクリーンショット
```

## テスト

```bash
uv run pytest
```

## 互換性

天守閣は multi-agent-shogun 系システム全般で利用可能。セッション名、ペイン指定、ベースパスは全て `config/settings.yaml` で設定できる。

| システム | 互換性 |
|---------|--------|
| [yaziuma/multi-agent-bakuhu](https://github.com/yaziuma/multi-agent-bakuhu) | 本システム向けに開発 |
| [yohey-w/multi-agent-shogun](https://github.com/yohey-w/multi-agent-shogun) | 互換あり — settings の `bakuhu.base_path` と `tmux` セッション名を調整すれば利用可能 |

## 関連プロジェクト

- [multi-agent-bakuhu](https://github.com/yaziuma/multi-agent-bakuhu) — 天守閣が制御するマルチエージェント統制システム本体
- [multi-agent-shogun](https://github.com/yohey-w/multi-agent-shogun) — bakuhu のfork元

## ライセンス

MIT
