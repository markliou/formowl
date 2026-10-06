# syntax=docker/dockerfile:1

FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/python \
    HF_HOME=/models/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/models/sentence-transformers \
    FORMOWL_BERT_ABLATION_MODEL_PROFILE=legacy_cpu_bert \
    FORMOWL_BERT_ABLATION_MODEL=sentence-transformers/bert-base-nli-mean-tokens \
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
    && apt-get install -y --no-install-recommends ca-certificates git curl \
    && rm -rf /var/lib/apt/lists/*

COPY containers/kg-bert-requirements.txt /tmp/formowl-kg-bert-requirements.txt

RUN python -m pip install --no-cache-dir --upgrade "pip<26" \
    && python -m pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==2.5.1+cpu" \
    && python -m pip install --no-cache-dir \
        -r /tmp/formowl-kg-bert-requirements.txt \
    && python -m pip check \
    && python - <<'PY'
import importlib
import importlib.metadata

import sentence_transformers
import torch
import transformers

runtime_versions = {
    "Authlib": "1.7.2",
    "cryptography": "46.0.7",
    "httpx": "0.28.1",
    "jieba": "0.42.1",
    "mcp": "1.28.1",
    "psycopg": "3.3.4",
    "psycopg-binary": "3.3.4",
    "sentencepiece": "0.2.2",
    "starlette": "0.52.1",
    "uvicorn": "0.52.1",
}
for package_name, expected_version in runtime_versions.items():
    actual_version = importlib.metadata.version(package_name)
    if actual_version != expected_version:
        raise RuntimeError(f"FormOwl runtime dependency drift: {package_name}")
for module_name in (
    "authlib",
    "cryptography",
    "httpx",
    "mcp",
    "psycopg",
    "starlette",
    "uvicorn",
):
    importlib.import_module(module_name)
assert "+cpu" in torch.__version__ or not torch.cuda.is_available()
print("formowl_runtime_dependencies", "verified")
print("sentence_transformers", sentence_transformers.__version__)
print("torch", torch.__version__)
print("transformers", transformers.__version__)
PY

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

CMD ["bash"]
