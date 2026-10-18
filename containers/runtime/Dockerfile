# syntax=docker/dockerfile:1

FROM python:3.13-slim AS build

WORKDIR /build

COPY pyproject.toml README.md ./
COPY python ./python

RUN python -m pip install --no-cache-dir "setuptools>=68" wheel \
    && python -m pip wheel --no-cache-dir --no-build-isolation --wheel-dir /wheels .

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FORMOWL_AUTH_MODE=oauth_google \
    FORMOWL_DATA_DIR=/data \
    FORMOWL_CONNECTED_HOST=0.0.0.0 \
    FORMOWL_CONNECTED_PORT=8000

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin formowl \
    && install -d -o formowl -g formowl /data

COPY --from=build /wheels /wheels

RUN python -m pip install --no-cache-dir /wheels/*.whl \
    && rm -rf /wheels

USER root
WORKDIR /home/formowl

VOLUME ["/data"]
EXPOSE 8000

ENTRYPOINT ["formowl-container-entrypoint"]
CMD ["serve"]
