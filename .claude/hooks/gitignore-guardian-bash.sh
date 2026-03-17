#!/usr/bin/env bash
set -euo pipefail

# Read JSON from stdin
json=$(cat)

# Extract command from tool_input
command=$(echo "$json" | jq -r '.tool_input.command // empty')

# Check if command contains "git add -f" or "git add --force"
if [[ "$command" == *"git add -f"* ]] || [[ "$command" == *"git add --force"* ]]; then
  echo "🛡️ git add -f は禁止です。.gitignoreで除外されたファイルの強制追加はできません。" >&2
  exit 2
fi

exit 0
