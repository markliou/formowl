# syntax=docker/dockerfile:1

FROM python:3.13-slim AS python-runtime
FROM node:22-bookworm-slim AS node-runtime
FROM rust:1-trixie

ARG GITLEAKS_VERSION=8.24.2
ARG TARGETARCH

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

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && case "${TARGETARCH:-amd64}" in \
        amd64) gitleaks_arch="x64" ;; \
        arm64) gitleaks_arch="arm64" ;; \
        *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && curl -fsSL "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_${gitleaks_arch}.tar.gz" -o /tmp/gitleaks.tar.gz \
    && tar -xzf /tmp/gitleaks.tar.gz -C /usr/local/bin gitleaks \
    && chmod +x /usr/local/bin/gitleaks \
    && rm -rf /var/lib/apt/lists/* /tmp/gitleaks.tar.gz

CMD ["bash"]
