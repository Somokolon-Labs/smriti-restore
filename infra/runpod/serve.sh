#!/usr/bin/env bash
# Run this pod as a GPU worker for the deployed site.
#
#   SMRITI_API_URL=https://smriti-api.onrender.com \
#   SMRITI_WORKER_KEY=smw_... \
#   bash infra/runpod/serve.sh
#
# Outbound HTTPS only, so RunPod needs no exposed ports.

set -euo pipefail

BLUE='\033[0;34m'; NC='\033[0m'
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

: "${SMRITI_API_URL:?set SMRITI_API_URL to the deployed control plane}"
: "${SMRITI_WORKER_KEY:?set SMRITI_WORKER_KEY to a key from WORKER_API_KEYS}"

export WORKER_NAME="${WORKER_NAME:-runpod-$(hostname | cut -c1-12)}"

# Scale the footprint to the card. Slicing costs speed and only 4GB cards need it.
VRAM_MB=$(python -c "import torch;print(int(torch.cuda.get_device_properties(0).total_memory/1024**2) if torch.cuda.is_available() else 0)")
if [ "$VRAM_MB" -ge 16000 ]; then
    export ATTENTION_SLICING="${ATTENTION_SLICING:-0}"
    export VAE_SLICING="${VAE_SLICING:-0}"
    export UPSCALE_TILE="${UPSCALE_TILE:-640}"
    export WORKER_MAX_PIXELS="${WORKER_MAX_PIXELS:-32000000}"
    export WORKER_TIERS="${WORKER_TIERS:-fast,balanced,max}"
else
    export UPSCALE_TILE="${UPSCALE_TILE:-384}"
fi

echo -e "${BLUE}==>${NC} worker ${WORKER_NAME} (${VRAM_MB} MB) -> ${SMRITI_API_URL}"
echo -e "${BLUE}==>${NC} tile ${UPSCALE_TILE}px · tiers ${WORKER_TIERS:-fast,balanced}"
curl -fsS "${SMRITI_API_URL}/health" && echo

# Restart on crash: a pod that OOMs should rejoin rather than go quiet. The
# control plane requeues whatever was in flight once the lease expires.
until python -m worker.main; do
    echo "worker exited with code $?; restarting in 10s"
    sleep 10
done
