# syntax=docker/dockerfile:1

FROM python:3.12.11-slim-trixie

ARG GITLEAKS_VERSION=8.24.2
ARG TARGETARCH

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/python \
    HF_HOME=/models/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/models/sentence-transformers \
    FORMOWL_ISSUE56_DENSE_MODEL_ID=intfloat/multilingual-e5-small \
    FORMOWL_ISSUE56_DENSE_MODEL_REVISION=fd1525a9fd15316a2d503bf26ab031a61d056e98 \
    FORMOWL_ISSUE56_DENSE_MODEL_FILE_SHA256=sha256:1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477 \
    FORMOWL_ISSUE56_DENSE_PROFILE_FINGERPRINT=sha256:39185d72bbf32944bd5498e7ac105311db90ca724f790d0bb123499691ae2b54

WORKDIR /workspace

RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources; \
    fi \
    && if [ -f /etc/apt/sources.list ]; then \
        sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        docker-buildx \
        docker-cli \
        docker-compose \
        git \
        pst-utils \
    && case "${TARGETARCH:-amd64}" in \
        amd64) gitleaks_arch="x64" ;; \
        arm64) gitleaks_arch="arm64" ;; \
        *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && curl -fsSL "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_${gitleaks_arch}.tar.gz" -o /tmp/gitleaks.tar.gz \
    && tar -xzf /tmp/gitleaks.tar.gz -C /usr/local/bin gitleaks \
    && chmod +x /usr/local/bin/gitleaks \
    && rm -rf /var/lib/apt/lists/* /tmp/gitleaks.tar.gz

COPY pyproject.toml README.md ./
COPY python ./python

RUN python -m pip install --no-cache-dir "setuptools>=68" wheel \
    && python -m pip install --no-cache-dir --no-build-isolation ".[dev]" \
    && python -m pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==2.5.1+cpu" \
    && python -m pip install --no-cache-dir \
        "huggingface-hub==0.26.5" \
        "numpy==1.26.4" \
        "safetensors==0.4.5" \
        "sentence-transformers==3.3.1" \
        "tokenizers==0.20.3" \
        "transformers==4.46.3" \
    && python -m pip check

RUN mkdir -p /models/huggingface /models/sentence-transformers \
    && chmod -R 0777 /models

RUN python - <<'PY'
import hashlib
import os
from pathlib import Path

from huggingface_hub import snapshot_download

model_id = os.environ["FORMOWL_ISSUE56_DENSE_MODEL_ID"]
revision = os.environ["FORMOWL_ISSUE56_DENSE_MODEL_REVISION"]
snapshot = Path(
    snapshot_download(
        repo_id=model_id,
        revision=revision,
        cache_dir=str(Path(os.environ["HF_HOME"]) / "hub"),
        ignore_patterns=["onnx/**", "pytorch_model.bin"],
    )
)
if snapshot.name != revision:
    raise RuntimeError("Issue #56 dense model revision drift")
weights = snapshot / "model.safetensors"
if weights.stat().st_size != 470641600:
    raise RuntimeError("Issue #56 dense model artifact size drift")
hasher = hashlib.sha256()
with weights.open("rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        hasher.update(chunk)
digest = "sha256:" + hasher.hexdigest()
expected = os.environ["FORMOWL_ISSUE56_DENSE_MODEL_FILE_SHA256"]
if digest != expected:
    raise RuntimeError("Issue #56 dense model artifact drift")
print("issue56_dense_model_verified", model_id, revision, digest)
PY

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs chromium \
    && node --version \
    && chromium --version \
    && rm -rf /var/lib/apt/lists/*

CMD ["bash"]
