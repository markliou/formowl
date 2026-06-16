# syntax=docker/dockerfile:1

FROM python:3.13-slim AS python-runtime
FROM node:22-bookworm-slim AS node-runtime
FROM rust:1-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/usr/local/cargo/bin:/usr/local/bin:/usr/bin:/bin \
    PYTHONPATH=/workspace/python:/workspace/python/formowl_project_mcp:/workspace/python/formowl_wiki_mcp

WORKDIR /workspace

COPY --from=python-runtime /usr/local /usr/local
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/bin/npm /usr/local/bin/npm
COPY --from=node-runtime /usr/local/bin/npx /usr/local/bin/npx
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules

CMD ["bash"]
