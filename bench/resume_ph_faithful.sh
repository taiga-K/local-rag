#!/bin/bash
# JQaRA is already indexed. Score A, B, and C without wiping it, then wipe
# before MIRACL and JSQuAD.
set -euo pipefail
ROOT=/tmp/align-pipeshub
# shellcheck disable=SC1091
source "$ROOT/bench/run_ph_faithful.sh"
mkdir -p "$ROOT/bench/results/ph-faithful"
run_subset jqara-dev-s40 jqara keep
run_subset miracl-ja-dev-s30 miracl wipe
run_subset jsquad-valid-s40 jsquad wipe
echo "ALL_DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
