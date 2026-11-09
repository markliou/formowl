#!/usr/bin/env bash
# Run the suite against a disposable pgvector database on isolated loopback.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
dev_image="${FORMOWL_DEV_IMAGE:-formowl-dev:local}"
pg_image="${FORMOWL_PGVECTOR_IMAGE:-pgvector/pgvector@sha256:131dcf7ff6a900545df8e7e092c270aa8c6db2f2c818e408cb45ec21316b74e6}"
mount_mode=ro
command=(python -B scripts/regression_unittest.py)
case "${1:-}" in
    '') ;;
    --records-only) command+=(--records-only) ;;
    --coverage)
        mount_mode=rw
        command=(sh -ec 'coverage run scripts/regression_unittest.py && coverage report')
        ;;
    *) echo 'Usage: run_regression.sh [--records-only|--coverage]' >&2; exit 2 ;;
esac
if (( $# > 1 )); then echo 'Expected at most one option' >&2; exit 2; fi

pg_id="$(docker run --rm -d --network none --tmpfs /var/lib/postgresql/data \
    -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=records_test \
    "$pg_image" postgres -c listen_addresses=127.0.0.1)"
runner="formowl-regression-${pg_id:0:12}"
cleanup() {
    docker rm -f "$runner" >/dev/null 2>&1 || true
    docker rm -f "$pg_id" >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# The temporary initdb server uses a Unix socket. TCP readiness selects the
# final server. Both containers share only this private network namespace.
for ((attempt=0; attempt<60; attempt++)); do
    if docker exec "$pg_id" pg_isready -q -h 127.0.0.1 -U postgres -d records_test; then break; fi
    sleep 1
done
docker exec "$pg_id" psql -X -v ON_ERROR_STOP=1 -h 127.0.0.1 -U postgres -d records_test \
    -c 'CREATE EXTENSION vector'
docker run --rm --name "$runner" --network "container:$pg_id" \
    --tmpfs /tmp:rw,exec,nosuid,nodev,size=4g -v "$root:/workspace:$mount_mode" -w /workspace \
    -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/workspace:/workspace/python:/workspace/tests \
    -e FORMOWL_RECORDS_TEST_DSN=postgresql://postgres@127.0.0.1:5432/records_test \
    "$dev_image" "${command[@]}"
