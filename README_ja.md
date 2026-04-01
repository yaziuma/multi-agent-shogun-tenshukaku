# multi-agent-shogun-tenshukaku

> [yohey-w/multi-agent-shogun](https://github.com/yohey-w/multi-agent-shogun) およびそのfork向けに開発されたWeb制御パネル。`config/settings.yaml` の設定変更のみで multi-agent-shogun 系システム全般に対応。

マルチエージェント統制システムのためのWeb制御パネル。天守閣 — 城主が戦場全体を見渡す司令塔にちなんで命名。

![指揮タブ](assets/screenshots/tab-command.png)

## 概要

天守閣は、tmux上で稼働する複数のAIエージェント（Claude Codeインスタンス）を、ブラウザから指揮・監視するためのWebインターフェースである。ターミナルのペインを切り替える代わりに、殿（人間オペレータ）は単一のWebページから指示送信、全エージェント監視、ダッシュボード閲覧、コマンド履歴の確認が可能。

## 機能

### 指揮タブ

将軍エージェントのtmuxペインに直接メッセージを送信する。Ctrl+Enterによるクイック送信と、Claude Codeの割り込みに使うEscapeキー送信ボタンを備える。Top/Bottomスクロールボタンで長い出力のナビゲーションが可能。

**入力テキストエリアは自動リサイズ**される（1行〜設定可能な最大行数、デフォルト8行）。テンプレートフレーズが設定されている場合は、テキストエリア上部に **規定文言** ドロップダウンが表示される。文言を選択するとカーソル位置に挿入されるため、既存のテキストを消さずに繰り返し利用できる。

折りたたみ式の **TUI操作パネル** から、方向キー、Enter、Tab、Space、Backspace、数字キー（0-9）、Yes/No確認ボタンなどのキーボード入力を直接送信可能。ブラウザを離れることなく対話型CLIインターフェースを操作できる。決定系キー（Enter、Escape、Yes、No）は誤操作防止のため1秒長押しで発動する。

**会話ログ** セクションでは、対話形式のビューを表示する。ユーザーの送信メッセージは青色、将軍の応答は金色で表示される。tmuxペインの生出力は会話ログの下の折りたたみセクションで確認可能。

![指揮タブ](assets/screenshots/tab-command.png)

#### ファイル添付（📎）

テキストエリア右側の **📎ファイル添付ボタン** から、ファイルをClaude Codeのtmuxペインへ直接送信できる。

**仕組み:**

1. ブラウザがファイルをBase64エンコードして `/api/file-paste` に送信
2. サーバーがファイルを `/tmp/tenshukaku-images/` にタイムスタンプ付きで保存
3. ファイルパスを `tmux send-keys` 経由で将軍ペインに送信
4. Claude CodeがパスをRead toolで読み取り、画像・PDF・テキスト・コードファイルなどを認識

**対応入力方式:**
- **📎ボタン** — クリックでファイルピッカーを開く（複数ファイル対応）
- **ドラッグ＆ドロップ** — コマンド入力エリアにファイルをドロップ
- **Ctrl+V / ペースト** — クリップボードの画像をテキストエリアに直接貼り付け
- ファイルはテキストエリア下部にチップとしてステージングされ、次のメッセージ送信と同時に送られる

5MB超の画像はアップロード前にブラウザ側でCanvasを使ってJPEG 85%品質にリサイズされる。

**自動クリーンアップ:**
- 起動時: `/tmp/tenshukaku-images/` 内の既存ファイルを全削除
- 5分おき: 30分以上経過したファイルを削除
- 上限管理: ディレクトリが50件を超えると古いものから削除

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

### 幕府タブ（Bakuhu）

Inter-Bakuhu ネットワークに接続中の peer 一覧をテーブル形式で表示する5番目のタブ。テーブルには各 peer の ID・名称・接続状態・Base URL が一覧される。**更新** ボタンで `GET /bakuhu/peers` を呼び出して peer 情報を最新化できる。
Inter-Bakuhu を有効にしている場合、ヘッダーには現在ノードが **主幕府 / 従幕府** のどちらで動いているかを示すロールバッジも表示される。

### 設定ページ（設定） — `GET /settings`

ナビゲーションバーの ⚙️ アイコンからアクセス。`settings.yaml` を直接編集せずにランタイムから設定変更が可能:

- **監視ポーリング間隔** — エージェント監視グリッドのベース・最大間隔（ms）
- **将軍ポーリング間隔** — 将軍ペインWebSocketフィードのベース・最大間隔（ms）
- **テキストエリア最大行数** — テキストエリアがスクロール可能になるまでの最大行高さ（1〜50）
- **規定文言** — 指揮タブのドロップダウンに表示するプリセット文言の追加・編集・削除

設定は `PUT /api/settings` 経由で `config/settings.yaml` に原子書き込みされ、起動中のアプリに即時反映される。

## アーキテクチャ

```
ブラウザ (HTTP + WebSocket)
    │
    ├── GET  /              → メインSPA（Jinja2テンプレート + htmx）
    ├── GET  /settings      → 設定ページ
    ├── POST /api/command   → tmux send-keys で将軍ペインに送信
    ├── POST /api/special-key → 特殊キー送信（許可リスト方式）
    ├── POST /api/monitor/clear → 監視表示クリア（非破壊的）
    ├── GET  /api/dashboard → dashboard.md 読み取り（データコンテナで生markdown返却）
    ├── GET  /api/history   → shogun_to_karo.yaml 読み取り
    ├── GET  /api/ws-config → WebSocket再接続設定
    ├── GET  /api/settings  → ユーザー設定取得（JSON）
    ├── PUT  /api/settings  → 設定を原子書き込みで更新
    ├── POST /api/file-paste → ファイルを /tmp/tenshukaku-images/ に保存してパスをsend-keys
    ├── POST /api/image-paste → /api/file-paste の後方互換エイリアス
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
| 端末レンダリング | xterm.js + image addon |
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
  textarea_max_rows: 8
  template_phrases:
    - label: "状況確認"
      text: "状況確認"
    - label: "家老呼ぶ"
      text: "家老に確認しろ！"
```

`ui.textarea_max_rows` と `ui.template_phrases` は設定ページ（`/settings`）からランタイムで変更することも可能。

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
│   ├── index.html           # メインSPA（5タブ + JS）
│   ├── settings.html        # 設定ページ（ポーリング間隔・規定文言）
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
│   ├── test_bakuhu.py                   # Inter-Bakuhu ルート・挙動テスト
│   ├── test_broadcasters.py             # ブロードキャスターテスト
│   ├── test_dashboard_markdown.py       # ダッシュボードMarkdownレンダリングテスト（Playwright）
│   ├── test_dashboard_refresh.py        # ダッシュボード手動更新テスト（Playwright）
│   ├── test_dashboard_table_dark_theme.py # テーブルダークテーマCSSテスト（Playwright）
│   ├── test_delta.py                    # デルタ差分計算テスト
│   ├── test_logging_config.py           # ログ / 監査ログテスト
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

## 🏯 Inter-Bakuhu ネットワーク

複数の幕府インスタンスを複数マシンにまたがって接続し、プライマリ幕府からセカンダリ幕府へタスクを委任できる。

> **詳細ドキュメント**: [docs/inter-bakuhu/setup.md](docs/inter-bakuhu/setup.md)

| 機能 | 説明 |
|------|------|
| マルチマシン委任 | プライマリからセカンダリ幕府へタスクを送信 |
| WebSocket RPC/PubSub | リアルタイム双方向接続 |
| トークン認証 | peer毎の独立したトークン管理 |
| 役割強制 | 委任操作はprimaryのみ実行可能 |
| ファイル転送 | `/bakuhu/files` で幕府間ファイル送信に対応（multipart、最大200MB） |
| 結果再送 | 委任結果の返却に失敗した場合でもキュー保存して自動再送 |

**クイックセットアップ**: メインマシンの `settings.yaml` に `bakuhu.role: primary`、リモートマシンに `role: secondary` を設定し、Tailscale IPで `peers` を構成する。詳細は [docs/inter-bakuhu/setup.md](docs/inter-bakuhu/setup.md) を参照。

## ログ

- 通常のアプリケーションログは Python `logging` 経由で出力され、プロセスマネージャ側で収集される。
- Inter-Bakuhu 監査イベントは `logs/inter-bakuhu/YYYY-MM-DD.jsonl` に日次JSONLで保存され、peer操作や委任通信の追跡に使える。

## 関連プロジェクト

- [multi-agent-bakuhu](https://github.com/yaziuma/multi-agent-bakuhu) — 天守閣が制御するマルチエージェント統制システム本体
- [multi-agent-shogun](https://github.com/yohey-w/multi-agent-shogun) — bakuhu のfork元

## ライセンス

MIT
