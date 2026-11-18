#!/bin/bash
# Measure A, B, and C on the three harness subsets.
# A: dense + fastembed, no prefixes, 80 per leg, fusion.k 1
# B: dense + sudachi + char_bigram, same depth and k
# C: dense only
set -euo pipefail
ROOT=/tmp/align-pipeshub
PY=/agent/repos/tmp-cf67989442305416/.venv/bin/python
CACHE=/agent/repos/tmp-cf67989442305416/data/cache
API=http://127.0.0.1:43123
cd "$ROOT"
export PYTHONPATH="$ROOT"

set_legs() {
  LEGS_SPEC="$1" python3 - <<'PY'
import os
from pathlib import Path
spec = os.environ["LEGS_SPEC"]
path = Path("/tmp/align-pipeshub/config.yaml")
lines = []
found = False
for line in path.read_text().splitlines(True):
    if line.startswith("  legs:"):
        lines.append(f"  legs: {spec}\n")
        found = True
    else:
        lines.append(line)
if not found:
    raise SystemExit("search.legs line missing")
path.write_text("".join(lines))
print("legs", spec)
PY
}

wipe() {
  sudo docker exec tmp-cf67989442305416-postgres-1 \
    psql -U kbindex -d kbindex -v ON_ERROR_STOP=1 -c \
    "truncate table bm25_postings, bm25_terms, bm25_stats, chunks, blocks, block_groups, records restart identity cascade;"
  curl -sf -X DELETE http://127.0.0.1:46333/collections/chunks >/dev/null || true
}

ensure_kb() {
  local id="$1"
  curl -sf -X POST "$API/api/v1/kb" -H 'content-type: application/json' \
    -d "{\"id\":\"${id}\",\"name\":\"${id}\"}" >/dev/null || true
}

run_one() {
  local config="$1" subset="$2" slug="$3"
  local out="$ROOT/bench/results/ph-faithful/${config}/${subset}"
  mkdir -p "$out"
  echo "RUN ${config} ${subset} $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  "$PY" -u bench/standalone_bench.py run \
    --subset "$subset" \
    --base-url "$API" \
    --kb "${slug}-ph" \
    --sanity-kb "${slug}-ph-sanity" \
    --cache "$CACHE" \
    --wait-seconds 14400 \
    --out "$out"
}

run_subset() {
  local subset="$1" slug="$2" do_wipe="$3"
  if [[ "$do_wipe" == wipe ]]; then
    wipe
  fi
  ensure_kb "${slug}-ph"
  ensure_kb "${slug}-ph-sanity"
  set_legs "[dense, fastembed]"
  run_one A "$subset" "$slug"
  set_legs "[dense, sudachi, char_bigram]"
  run_one B "$subset" "$slug"
  set_legs "[dense]"
  run_one C "$subset" "$slug"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
mkdir -p "$ROOT/bench/results/ph-faithful"
for pair in "jqara-dev-s40 jqara" "miracl-ja-dev-s30 miracl" "jsquad-valid-s40 jsquad"; do
  subset=${pair%% *}
  slug=${pair##* }
  run_subset "$subset" "$slug" wipe
done
echo "ALL_DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
fi
