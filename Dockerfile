# syntax=docker/dockerfile:1

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/python

WORKDIR /workspace

COPY README.md SPEC.md pyproject.toml ./
COPY python ./python
COPY tests ./tests

CMD ["python", "-m", "unittest", "discover", "-s", "tests"]
