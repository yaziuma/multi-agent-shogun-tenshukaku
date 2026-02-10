#!/bin/bash

set -e

PROJECT_DIR="/home/quieter/projects/shogun-web-v2"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/shogun-web.log"

# 設定ファイルパス（shogun-webリポジトリ内）
CONFIG_FILE="$PROJECT_DIR/config/settings.yaml"

echo "🚀 shogun-web 起動スクリプト"
echo "================================"

# 設定ファイルから host と port を読み取る
if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ 設定ファイルが見つかりません: $CONFIG_FILE"
    exit 1
fi

echo "設定ファイル読み込み中: $CONFIG_FILE"
HOST=$(grep -A2 '^server:' "$CONFIG_FILE" | grep 'host:' | awk '{print $2}' | tr -d '"')
PORT=$(grep -A2 '^server:' "$CONFIG_FILE" | grep 'port:' | awk '{print $2}')

if [ -z "$HOST" ] || [ -z "$PORT" ]; then
    echo "❌ 設定ファイルから host/port を読み取れませんでした"
    exit 1
fi

echo "設定: HOST=$HOST, PORT=$PORT"

# logsディレクトリ作成
mkdir -p "$LOG_DIR"

# 既存プロセスの停止（ポート+アプリ名の二重確認）
echo "既存プロセスを確認中..."
EXISTING_PID=$(lsof -ti:$PORT 2>/dev/null || true)

if [ -n "$EXISTING_PID" ]; then
    echo "ポート $PORT を使用中のプロセス (PID: $EXISTING_PID) を発見"

    # プロセスのコマンドラインを確認（/proc/$PID/cmdline）
    CMDLINE=$(tr '\0' ' ' < /proc/$EXISTING_PID/cmdline 2>/dev/null || echo "")

    # "uvicorn" AND "main:app" が含まれるか確認
    if echo "$CMDLINE" | grep -q "uvicorn" && echo "$CMDLINE" | grep -q "main:app"; then
        echo "✓ shogun-webプロセスと確認（uvicorn main:app）"
        echo "プロセスを停止します..."
        kill -9 $EXISTING_PID 2>/dev/null || true
        sleep 2
        echo "プロセスを停止しました"
    else
        echo "❌ ポート $PORT は別プロセスが使用中です:"
        echo "   PID: $EXISTING_PID"
        echo "   CMDLINE: $CMDLINE"
        echo "   shogun-webプロセスではないため、停止を中止します"
        exit 1
    fi
else
    echo "既存プロセスはありません"
fi

# ポート解放確認
echo "ポート解放を確認中..."
sleep 1

# shogun-web起動
echo "shogun-webを起動中..."
cd "$PROJECT_DIR"
nohup uv run uvicorn main:app --host $HOST --port $PORT > "$LOG_FILE" 2>&1 &
NEW_PID=$!

echo "起動コマンドを実行しました（PID: $NEW_PID）"
sleep 3

# ヘルスチェック
echo "ヘルスチェック中..."
if curl -s http://localhost:$PORT > /dev/null 2>&1; then
    echo "✅ shogun-webが正常に起動しました！"
    echo "📊 URL: http://$HOST:$PORT"
    echo "📝 ログ: $LOG_FILE"
    echo "🔢 PID: $NEW_PID"
else
    echo "⚠️ ヘルスチェックに失敗しました。ログを確認してください: $LOG_FILE"
    exit 1
fi
