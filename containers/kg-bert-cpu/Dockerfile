# syntax=docker/dockerfile:1

FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/python \
    HF_HOME=/models/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/models/sentence-transformers \
    FORMOWL_BERT_ABLATION_MODEL_PROFILE=legacy_cpu_bert \
    FORMOWL_BERT_ABLATION_MODEL=sentence-transformers/bert-base-nli-mean-tokens

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

COPY containers/kg-bert-cpu/requirements.txt /tmp/formowl-kg-bert-requirements.txt

RUN python -m pip install --no-cache-dir --upgrade "pip<26" \
    && python -m pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==2.5.1+cpu" \
    && python -m pip install --no-cache-dir \
        -r /tmp/formowl-kg-bert-requirements.txt \
    && python - <<'PY'
import sentence_transformers
import torch
import transformers

assert "+cpu" in torch.__version__ or not torch.cuda.is_available()
print("sentence_transformers", sentence_transformers.__version__)
print("torch", torch.__version__)
print("transformers", transformers.__version__)
PY

RUN mkdir -p /models/huggingface /models/sentence-transformers \
    && chmod -R 0777 /models

CMD ["bash"]
