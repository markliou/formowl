# syntax=docker/dockerfile:1

ARG FORMOWL_KG_BERT_GPU_BASE=pytorch/pytorch:2.5.1-cuda11.8-cudnn9-runtime

FROM ${FORMOWL_KG_BERT_GPU_BASE}

ARG FORMOWL_KG_BERT_EXPECTED_TORCH_PREFIX=2.5.1
ARG FORMOWL_KG_BERT_EXPECTED_CUDA=11.8

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/python \
    HF_HOME=/models/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/models/sentence-transformers \
    FORMOWL_BERT_ABLATION_MODEL_PROFILE=gpu_bge_large_en_v1_5 \
    FORMOWL_BERT_ABLATION_MODEL=BAAI/bge-large-en-v1.5 \
    FORMOWL_KG_BERT_MIN_GPU_CLASS=gtx_1080_ti_11gb \
    FORMOWL_KG_BERT_EXPECTED_TORCH_PREFIX=${FORMOWL_KG_BERT_EXPECTED_TORCH_PREFIX} \
    FORMOWL_KG_BERT_EXPECTED_CUDA=${FORMOWL_KG_BERT_EXPECTED_CUDA}

WORKDIR /workspace

COPY containers/kg-bert-gpu/requirements.txt /tmp/formowl-kg-bert-gpu-requirements.txt

RUN python -m pip install --break-system-packages --no-cache-dir --upgrade "pip<26" \
    && python -m pip install --break-system-packages --no-cache-dir \
        -r /tmp/formowl-kg-bert-gpu-requirements.txt \
    && python - <<'PY'
import sentence_transformers
import os
import torch
import transformers

expected_torch_prefix = os.environ["FORMOWL_KG_BERT_EXPECTED_TORCH_PREFIX"]
expected_cuda = os.environ["FORMOWL_KG_BERT_EXPECTED_CUDA"]

assert torch.__version__.startswith(expected_torch_prefix)
assert torch.version.cuda == expected_cuda
print("sentence_transformers", sentence_transformers.__version__)
print("torch", torch.__version__)
print("torch_cuda", torch.version.cuda)
print("transformers", transformers.__version__)
PY

RUN mkdir -p /models/huggingface /models/sentence-transformers \
    && chmod -R 0777 /models

CMD ["bash"]
