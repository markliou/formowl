# syntax=docker/dockerfile:1

FROM pytorch/pytorch:2.5.1-cuda11.8-cudnn9-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/python \
    HF_HOME=/models/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/models/sentence-transformers \
    FORMOWL_BERT_ABLATION_MODEL=sentence-transformers/bert-base-nli-mean-tokens

WORKDIR /workspace

COPY containers/kg-bert-gpu/requirements.txt /tmp/formowl-kg-bert-gpu-requirements.txt

RUN python -m pip install --no-cache-dir --upgrade "pip<26" \
    && python -m pip install --no-cache-dir \
        -r /tmp/formowl-kg-bert-gpu-requirements.txt \
    && python - <<'PY'
import sentence_transformers
import torch
import transformers

assert torch.__version__.startswith("2.5.1")
assert torch.version.cuda == "11.8"
print("sentence_transformers", sentence_transformers.__version__)
print("torch", torch.__version__)
print("torch_cuda", torch.version.cuda)
print("transformers", transformers.__version__)
PY

RUN mkdir -p /models/huggingface /models/sentence-transformers \
    && chmod -R 0777 /models

CMD ["bash"]
