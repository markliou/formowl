# syntax=docker/dockerfile:1

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/python:/app/python/formowl_project_mcp:/app/python/formowl_wiki_mcp \
    FORMOWL_DATA_DIR=/data

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY README.md SPEC.md pyproject.toml ./
COPY python ./python
COPY crates ./crates

VOLUME ["/data"]

CMD ["python", "-m", "formowl_project_mcp.server"]
