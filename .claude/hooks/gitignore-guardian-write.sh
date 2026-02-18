#!/usr/bin/env bash
set -euo pipefail

# Read JSON from stdin
json=$(cat)

# Extract file_path from tool_input
file_path=$(echo "$json" | jq -r '.tool_input.file_path // empty')

# Check if file_path ends with .gitignore or .gitattributes
if [[ "$file_path" == *".gitignore" ]] || [[ "$file_path" == *".gitattributes" ]]; then
  echo "🛡️ .gitignore/.gitattributes の変更は殿の承認が必要です。" >&2
  exit 2
fi

exit 0
