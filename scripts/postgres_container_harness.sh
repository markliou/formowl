#!/usr/bin/env bash

formowl_postgres_require_env() {
  local variable_name
  for variable_name in "$@"; do
    if [[ -z "${!variable_name:-}" ]]; then
      printf '%s is required\n' "$variable_name" >&2
      return 1
    fi
  done
}

formowl_postgres_validate_pgdata() {
  local pgdata="$1"
  if [[ ! "$pgdata" =~ ^/tmp/formowl-[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
    printf 'PGDATA must be a single safe /tmp/formowl-* directory\n' >&2
    return 1
  fi
}

formowl_postgres_initialize() {
  local pgdata="$1"
  local log_path="$2"

  formowl_postgres_validate_pgdata "$pgdata"

  export PGUSER="${PGUSER:-postgres}"
  export POSTGRES_DB="${POSTGRES_DB:-postgres}"
  export POSTGRES_HOST_AUTH_METHOD="${POSTGRES_HOST_AUTH_METHOD:-trust}"
  export PGDATA="$pgdata"

  rm -rf "$PGDATA"
  mkdir -p "$PGDATA"
  docker-entrypoint.sh postgres -c listen_addresses='' >"$log_path" 2>&1 &
  FORMOWL_POSTGRES_PID="$!"
  trap formowl_postgres_cleanup EXIT

  local attempt
  for ((attempt = 0; attempt < 60; attempt += 1)); do
    if pg_isready -U "$PGUSER" -d "$POSTGRES_DB" >/dev/null 2>&1 \
      && psql -v ON_ERROR_STOP=1 -U "$PGUSER" -d "$POSTGRES_DB" \
        -c 'SELECT 1' >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done

  pg_isready -U "$PGUSER" -d "$POSTGRES_DB" >/dev/null
  psql -v ON_ERROR_STOP=1 -U "$PGUSER" -d "$POSTGRES_DB" \
    -c 'SELECT 1' >/dev/null
}

formowl_postgres_cleanup() {
  if [[ -n "${FORMOWL_POSTGRES_PID:-}" ]] \
    && kill -0 "$FORMOWL_POSTGRES_PID" >/dev/null 2>&1; then
    pg_ctl -D "$PGDATA" -m fast -w stop >/dev/null 2>&1 || true
  fi
}

formowl_postgres_apply_migration() {
  local migration_path
  for migration_path in "$@"; do
    psql -v ON_ERROR_STOP=1 -U "$PGUSER" -d "$POSTGRES_DB" -f "$migration_path"
  done
}
