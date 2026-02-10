#!/bin/bash

# ============================================================
# restart.sh - shogun-web 開発用再起動スクリプト
# ============================================================
# キャッシュ完全削除 + プロセス停止 + クリーン起動を一発で行う
# 開発時のホットリロード（--reload）有効

PROJECT_DIR="/home/quieter/projects/shogun-web-v2"
CONFIG_FILE="$PROJECT_DIR/config/settings.yaml"

# 色定義
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
NC='\033[0m' # No Color

echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}🔄 shogun-web 再起動スクリプト${NC}"
echo -e "${GREEN}======================================${NC}"
echo ""

# ============================================================
# 0. 設定ファイルからポート番号・ホストを取得
# ============================================================
echo -e "${YELLOW}[0/3] 設定ファイル読み込み中...${NC}"

# デフォルト値
HOST="0.0.0.0"
PORT=30000

if [ -f "$CONFIG_FILE" ]; then
    echo "  → 設定ファイル: $CONFIG_FILE"

    # config/settings.yaml から host と port を読み取る（start.sh と同じ方式）
    READ_HOST=$(grep -A2 '^server:' "$CONFIG_FILE" | grep 'host:' | awk '{print $2}' | tr -d '"')
    READ_PORT=$(grep -A2 '^server:' "$CONFIG_FILE" | grep 'port:' | awk '{print $2}')

    if [ -n "$READ_HOST" ]; then
        HOST="$READ_HOST"
    fi

    if [ -n "$READ_PORT" ]; then
        PORT="$READ_PORT"
    fi

    echo "  ✓ 設定: HOST=$HOST, PORT=$PORT"
else
    echo "  ⚠️  設定ファイルが見つかりません。デフォルト値を使用: HOST=$HOST, PORT=$PORT"
fi

echo ""

# ============================================================
# 1. 既存プロセスの停止
# ============================================================
echo -e "${YELLOW}[1/3] 既存プロセスを停止中...${NC}"

# uvicornプロセスの検索と停止（shogun-web関連のみ）
UVICORN_PIDS=$(ps aux | grep "[u]vicorn main:app" | grep "shogun-web-v2" | awk '{print $2}')
if [ -n "$UVICORN_PIDS" ]; then
    echo "  → uvicornプロセスを発見: $UVICORN_PIDS"
    for pid in $UVICORN_PIDS; do
        kill $pid 2>/dev/null || true
    done
    sleep 2
    echo "  ✓ uvicornプロセスを停止しました"
else
    echo "  → uvicornプロセスは見つかりませんでした"
fi

# ポート30000を使用中のプロセスを停止
PORT_PID=$(lsof -ti:$PORT 2>/dev/null || true)
if [ -n "$PORT_PID" ]; then
    echo "  → ポート$PORT を使用中のプロセスを発見: PID $PORT_PID"
    kill $PORT_PID 2>/dev/null || true
    sleep 2

    # まだ残っていれば kill -9
    if kill -0 $PORT_PID 2>/dev/null; then
        echo "  → 強制停止します (kill -9)"
        kill -9 $PORT_PID 2>/dev/null || true
        sleep 1
    fi
    echo "  ✓ ポート使用プロセスを停止しました"
else
    echo "  → ポート$PORT は使用されていません"
fi

echo ""

# ============================================================
# 2. キャッシュの完全削除
# ============================================================
echo -e "${YELLOW}[2/3] キャッシュを完全削除中...${NC}"

cd "$PROJECT_DIR"

# __pycache__/ ディレクトリを再帰的に削除
PYCACHE_COUNT=$(find . -type d -name "__pycache__" | wc -l)
if [ "$PYCACHE_COUNT" -gt 0 ]; then
    echo "  → __pycache__/ を削除中 (${PYCACHE_COUNT}個)"
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
fi

# *.pyc ファイルを再帰的に削除
PYC_COUNT=$(find . -type f -name "*.pyc" | wc -l)
if [ "$PYC_COUNT" -gt 0 ]; then
    echo "  → *.pyc を削除中 (${PYC_COUNT}個)"
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
fi

# その他のキャッシュディレクトリを削除
for cache_dir in .pytest_cache .ruff_cache .mypy_cache; do
    if [ -d "$cache_dir" ]; then
        echo "  → $cache_dir/ を削除中"
        rm -rf "$cache_dir"
    fi
done

# *.egg-info/ を削除
EGG_COUNT=$(find . -type d -name "*.egg-info" | wc -l)
if [ "$EGG_COUNT" -gt 0 ]; then
    echo "  → *.egg-info/ を削除中 (${EGG_COUNT}個)"
    find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
fi

echo "  ✓ キャッシュ削除完了"
echo ""

# ============================================================
# 3. サーバー起動
# ============================================================
echo -e "${YELLOW}[3/3] サーバーを起動中...${NC}"

cd "$PROJECT_DIR"
echo "  → uvicorn main:app --host $HOST --port $PORT --reload"
echo ""

# 起動コマンドを実行（--reload でホットリロード有効）
uv run uvicorn main:app --host $HOST --port $PORT --reload &
SERVER_PID=$!

# 起動確認（最大10秒待機）
echo -e "${YELLOW}起動確認中...${NC}"
for i in {1..10}; do
    sleep 1
    if lsof -i:$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo ""
        echo -e "${GREEN}======================================${NC}"
        echo -e "${GREEN}✅ shogun-web が起動しました！${NC}"
        echo -e "${GREEN}======================================${NC}"
        echo -e "📊 URL: ${GREEN}http://localhost:$PORT${NC}"
        echo -e "🔢 PID: ${GREEN}$SERVER_PID${NC}"
        echo -e "🔄 ホットリロード: ${GREEN}有効${NC}"
        echo ""
        echo "Ctrl+C で停止します"
        echo ""

        # フォアグラウンドで待機
        wait $SERVER_PID
        exit 0
    fi
done

# 起動失敗
echo ""
echo -e "${RED}======================================${NC}"
echo -e "${RED}❌ 起動に失敗しました${NC}"
echo -e "${RED}======================================${NC}"
echo "ポート$PORT がlistenされませんでした（10秒タイムアウト）"
echo "プロセスを確認してください: ps aux | grep uvicorn"
exit 1
