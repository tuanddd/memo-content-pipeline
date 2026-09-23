#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: correct-transcript.sh <session-folder>" >&2
  exit 2
fi

session=$(cd "$1" && pwd)
repo=$(cd "$(dirname "$0")/.." && pwd)
model=${SESSION_KIT_MODEL:-sonnet}
work="$session/02-transcript/correction"
log="$session/run.log"
kit=(uv run --project "$repo" session-kit)

"${kit[@]}" _correct-prepare "$session"

shopt -s nullglob
chunks=("$work"/in-*.json)
total=${#chunks[@]}
n=0
failed=0
for input in "${chunks[@]}"; do
  n=$((n + 1))
  name=$(basename "$input")
  output="$work/out-${name#in-}"
  if [[ -s "$output" ]]; then
    echo "  correct    chunk $n/$total cached"
    continue
  fi
  for attempt in 1 2; do
    if "$repo/scripts/claude-json.sh" "$repo/schemas/correction.schema.json" "$repo/prompts/correct-transcript.md" "$model" \
        < "$input" > "$output.tmp" 2>>"$log"; then
      mv "$output.tmp" "$output"
      echo "  correct    chunk $n/$total done"
      break
    fi
    rm -f "$output.tmp"
    echo "  correct    chunk $n/$total failed (attempt $attempt)" | tee -a "$log"
    if [[ $attempt -eq 2 ]]; then
      failed=$((failed + 1))
    fi
  done
done

if [[ $total -gt 0 && $failed -eq $total ]]; then
  echo "every correction chunk failed; see $log" >&2
  exit 1
fi

"${kit[@]}" _correct-apply "$session"
