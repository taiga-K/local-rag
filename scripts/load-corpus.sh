#!/usr/bin/env bash
# Start the stack if it is not already up, then push a JSONL corpus.
# Usage: scripts/load-corpus.sh samples/corpus.jsonl bench
set -euo pipefail
jsonl=${1:?jsonl path}
kb=${2:?knowledge base id}
api=${KBINDEX_API:-http://127.0.0.1:43123}
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$root"
if [[ "$jsonl" != /* ]]; then
  jsonl="$root/$jsonl"
fi
compose=(docker compose)
if ! docker info >/dev/null 2>&1; then
  compose=(sudo docker compose)
fi
"${compose[@]}" up -d
for _ in $(seq 1 90); do
  if curl -sf -o /dev/null -X POST "$api/api/v1/kb" \
    -H 'content-type: application/json' \
    -d "{\"id\":\"$kb\",\"name\":\"$kb\"}"; then
    break
  fi
  sleep 2
done
python3 - "$api" "$kb" "$jsonl" <<'PY'
import json
import sys
import urllib.request

api, kb, path = sys.argv[1:]
def post(url, body):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.status

post(f"{api}/api/v1/kb", {"id": kb, "name": kb})
with open(path, encoding="utf-8") as handle:
    for line in handle:
        if not line.strip():
            continue
        item = json.loads(line)
        status = post(
            f"{api}/api/v1/kb/{kb}/records",
            {
                "recordName": item.get("recordName") or item["externalRecordId"],
                "mimeType": "application/blocks",
                "externalRecordId": item["externalRecordId"],
                "version": int(item.get("version") or 1),
                "blocksFormat": 1,
                "blocks": {"blocks": [{"index": 0, "type": "text", "format": "txt", "data": item["text"]}]},
            },
        )
        print(f"{status} {item['externalRecordId']}")
PY
echo "ingested $kb from $jsonl"
echo "retrieve: curl -s -X POST $api/api/v1/retrieve -H 'content-type: application/json' -d '{\"query\":\"東京の天気\",\"limit\":10,\"rewriteQuery\":false,\"maxChunksPerRecord\":1,\"filters\":{\"kb\":[\"$kb\"]}}'"
