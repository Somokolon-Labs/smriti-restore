#!/usr/bin/env bash
# Prepare a fresh RunPod (or any Ubuntu + CUDA) box for Smriti.
#
#   git clone https://github.com/Somokolon-Labs/smriti-restore.git
#   cd smriti-restore && bash infra/runpod/bootstrap.sh
#
# Assumes a PyTorch template. Installs the cu121 wheels itself if torch is absent.

set -euo pipefail

BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'
step() { echo -e "\n${BLUE}==>${NC} $*"; }
warn() { echo -e "${YELLOW}  !${NC} $*"; }

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
step "project root: $(pwd)"

step "GPU"
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
else
    warn "nvidia-smi not found — this box may not have a GPU"
fi

step "system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# libgl and libglib are needed by opencv even in the headless build.
apt-get install -y -qq --no-install-recommends git curl unzip libgl1 libglib2.0-0 >/dev/null

step "python dependencies"
python -m pip install --upgrade pip -q
if python -c "import torch" 2>/dev/null; then
    echo "  torch $(python -c 'import torch; print(torch.__version__)') already present"
else
    warn "torch missing, installing cu121 wheels"
    pip install -q torch==2.5.1 torchvision==0.20.1 \
        --index-url https://download.pytorch.org/whl/cu121
fi

# Never let a requirements file replace the template's CUDA torch build.
grep -vE '^(torch|torchvision)==' worker/requirements.txt > /tmp/worker-req.txt
pip install -q -r /tmp/worker-req.txt
grep -vE '^(torch|torchvision)==' ml/requirements.txt > /tmp/ml-req.txt
pip install -q -r /tmp/ml-req.txt
pip install -q -r api/requirements.txt

step "environment"
if [ ! -f .env ]; then
    cp .env.example .env
    warn ".env created — fill these in before running anything:"
    warn "   PEXELS_ACCESS_KEY                    (ground-truth photos for evaluation)"
    warn "   SMRITI_API_URL, SMRITI_WORKER_KEY    (serving the live site)"
    warn "   ADMIN_API_KEY                        (publishing eval results)"
fi

# Keep the HF cache on the persistent volume so SD downloads once, not per boot.
if [ -d /workspace ]; then
    export HF_HOME=/workspace/hf_cache
    mkdir -p "$HF_HOME"
    grep -q '^HF_HOME=' .env \
        && sed -i "s|^HF_HOME=.*|HF_HOME=$HF_HOME|" .env \
        || echo "HF_HOME=$HF_HOME" >> .env
    echo "  HF cache -> $HF_HOME (survives pod restarts)"
fi

mkdir -p data outputs eval

step "verifying the classical layer (no GPU needed, seconds)"
python scripts/check_imaging.py

step "verifying CUDA is genuinely usable"
python - <<'PY'
import torch
assert torch.cuda.is_available(), "no CUDA device visible to torch"
a = torch.randn(2048, 2048, device="cuda", dtype=torch.float16)
torch.cuda.synchronize()
assert torch.isfinite(a @ a).all().item()
props = torch.cuda.get_device_properties(0)
print(f"  {props.name}, {props.total_memory / 1024**3:.1f} GB, fp16 matmul OK")
PY

cat <<'EOF'

Ready. Two things you can do from here:

  Measure restoration quality and publish it to the live model card:
    bash infra/runpod/evaluate.sh

  Serve the live site from this pod:
    bash infra/runpod/serve.sh

EOF
