# GPU worker. Needs an NVIDIA runtime:
#   docker build -f worker/Dockerfile -t smriti-worker .
#   docker run --gpus all --env-file .env smriti-worker
FROM pytorch/pytorch:2.5.1-cuda12.1-cudnn9-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/hf_cache

WORKDIR /app

# libGL and libglib are required by opencv even in the headless build.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# torch/torchvision already ship in the base image; drop them from the list so
# pip cannot replace the CUDA build with a CPU wheel.
COPY worker/requirements.txt ./requirements.txt
RUN grep -vE '^(torch|torchvision)==' requirements.txt > requirements.docker.txt \
    && pip install --no-cache-dir -r requirements.docker.txt

COPY worker ./worker

RUN mkdir -p /app/hf_cache /app/outputs

CMD ["python", "-m", "worker.main"]
