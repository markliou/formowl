#!/bin/sh

set -eu

umask 077

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

SCRIPT_PATH=$(/usr/bin/readlink -f "$0")
SCRIPT_DIR=${SCRIPT_PATH%/*}
ROOT=${SCRIPT_DIR%/tests}
DOCKER_SOCKET=/var/run/docker.sock

if [ ! -S "$DOCKER_SOCKET" ]; then
    printf '%s\n' '{"error":"capability_live_docker_socket_unavailable","status":"error"}'
    exit 1
fi
SOCKET_GID=$(/usr/bin/stat -c '%g' "$DOCKER_SOCKET")

exec /usr/bin/docker run --rm \
    --user "$(/usr/bin/id -u):$(/usr/bin/id -g)" \
    --group-add "$SOCKET_GID" \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --tmpfs /tmp:size=256m,mode=1777 \
    --volume "$ROOT:$ROOT:ro" \
    --volume "$DOCKER_SOCKET:$DOCKER_SOCKET" \
    --workdir "$ROOT" \
    --env DOCKER_HOST=unix:///var/run/docker.sock \
    --env FORMOWL_RUN_CAPABILITY_BOUNDING_SET_LIVE=1 \
    --env PYTHONDONTWRITEBYTECODE=1 \
    --env "PYTHONPATH=$ROOT:$ROOT/tests:$ROOT/python" \
    formowl-dev:local \
    python -m unittest \
    test_connected_runtime_container.ConnectedRuntimeContainerTests.test_capability_bounding_set_container_ab_regression
