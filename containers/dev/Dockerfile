# syntax=docker/dockerfile:1

FROM python:3.13-slim

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
    && apt-get install -y --no-install-recommends ca-certificates curl git pst-utils \
    && case "${TARGETARCH:-amd64}" in \
        amd64) gitleaks_arch="x64" ;; \
        arm64) gitleaks_arch="arm64" ;; \
        *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && curl -fsSL "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_${gitleaks_arch}.tar.gz" -o /tmp/gitleaks.tar.gz \
    && tar -xzf /tmp/gitleaks.tar.gz -C /usr/local/bin gitleaks \
    && chmod +x /usr/local/bin/gitleaks \
    && rm -rf /var/lib/apt/lists/* /tmp/gitleaks.tar.gz

RUN python -m pip install --no-cache-dir \
    "coverage[toml]>=7.6" \
    "jieba>=0.42.1,<0.43" \
    "pre-commit>=4.0" \
    "ruff==0.8.6" \
    "sentencepiece>=0.2,<0.3"

CMD ["bash"]
