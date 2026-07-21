# syntax=docker/dockerfile:1

ARG CODEX_VERSION=0.144.6

FROM node:20-bookworm-slim AS codex-runtime

ARG CODEX_VERSION

RUN npm install --global "@openai/codex@${CODEX_VERSION}" \
    && npm cache clean --force \
    && codex --version

FROM python:3.13-slim AS formowl-dev-base

ARG GITLEAKS_VERSION=8.24.2
ARG TARGETARCH

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/python

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
        git \
        poppler-utils \
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

COPY --from=codex-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=codex-runtime /usr/local/lib/node_modules/@openai/codex \
    /usr/local/lib/node_modules/@openai/codex

RUN ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex \
    && codex --version

RUN python -m pip install --no-cache-dir \
    "coverage[toml]>=7.6" \
    "jieba>=0.42.1,<0.43" \
    "pre-commit>=4.0" \
    "ruff==0.8.6" \
    "sentencepiece>=0.2,<0.3"

CMD ["bash"]

FROM formowl-dev-base AS formowl-uat-runtime

RUN groupadd --gid 65532 formowl \
    && useradd \
        --uid 65532 \
        --gid 65532 \
        --create-home \
        --home-dir /home/formowl \
        --shell /usr/sbin/nologin \
        formowl

COPY python /opt/formowl/python
COPY scripts /opt/formowl/scripts

RUN chmod -R a+rX /opt/formowl

ENV PYTHONPATH=/opt/formowl/python

WORKDIR /opt/formowl
USER 65532:65532

CMD ["python", "scripts/mail_human_uat.py", "--help"]

FROM formowl-dev-base AS formowl-dev
