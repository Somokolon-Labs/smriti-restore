#!/usr/bin/env bash
# Run the restoration benchmark and publish the numbers to the live model card.
#
#   bash infra/runpod/evaluate.sh
#   PER_DEGRADATION=6 bash infra/runpod/evaluate.sh
#   PUBLISH=0 bash infra/runpod/evaluate.sh          # keep results local
#
# This is the one outstanding step for the project: every other part is built and
# deployed, but the model card stays empty until this has actually measured
# something.

set -euo pipefail

BLUE='\033[0;34m'; NC='\033[0m'
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

PER_DEGRADATION="${PER_DEGRADATION:-4}"
MAX_SIDE="${MAX_SIDE:-768}"
SCALE="${SCALE:-2}"
PUBLISH="${PUBLISH:-1}"

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

# Larger cards can afford bigger references, which makes the metrics more
# representative of what a real scan looks like.
VRAM_MB=$(python -c "import torch;print(int(torch.cuda.get_device_properties(0).total_memory/1024**2) if torch.cuda.is_available() else 0)")
if [ "$VRAM_MB" -eq 0 ]; then
    echo "no CUDA device; run infra/runpod/bootstrap.sh first" >&2
    exit 1
fi
if [ "$VRAM_MB" -ge 20000 ] && [ -z "${MAX_SIDE_OVERRIDDEN:-}" ]; then
    MAX_SIDE=1024
fi

echo -e "${BLUE}==>${NC} ${VRAM_MB} MB VRAM · ${PER_DEGRADATION} images per degradation · reference side ${MAX_SIDE}px"

ARGS=(--per-degradation "$PER_DEGRADATION" --max-side "$MAX_SIDE" --scale "$SCALE")
if [ "$PUBLISH" = "1" ]; then
    if [ -z "${ADMIN_API_KEY:-}" ] || [ -z "${SMRITI_API_URL:-}" ]; then
        echo "PUBLISH=1 needs SMRITI_API_URL and ADMIN_API_KEY in .env" >&2
        exit 1
    fi
    ARGS+=(--publish)
    echo -e "${BLUE}==>${NC} will publish to ${SMRITI_API_URL}"
fi

python -m ml.evaluate "${ARGS[@]}"

echo
echo "  results      eval/results.json"
echo "  comparisons  eval/samples/   (clean | degraded | restored)"
echo
echo "Pull them down to commit:"
echo "  runpodctl send eval/results.json eval/samples"
