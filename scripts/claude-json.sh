#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: claude-json.sh <schema.json> <system-prompt.md> [model] < input > output" >&2
  exit 2
fi

schema_file=$1
prompt_file=$2
model=${3:-sonnet}

claude_bin=${CLAUDE_BIN:-$(command -v claude || true)}
if [[ -z "$claude_bin" && -x "$HOME/.claude/local/claude" ]]; then
  claude_bin="$HOME/.claude/local/claude"
fi
if [[ -z "$claude_bin" ]]; then
  echo "claude CLI not found. Install Claude Code or set CLAUDE_BIN to its path." >&2
  exit 127
fi

raw=$("$claude_bin" -p \
  --output-format json \
  --model "$model" \
  --tools "" \
  --no-session-persistence \
  --setting-sources "" \
  --system-prompt-file "$prompt_file" \
  --json-schema "$(cat "$schema_file")" \
  "Process the JSON input below and answer only through the schema.")

if [[ "$(jq -r '.is_error' <<<"$raw")" != "false" ]]; then
  jq -r '.result // "claude returned an error"' <<<"$raw" >&2
  exit 1
fi

jq -e '.structured_output' <<<"$raw"
