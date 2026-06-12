#!/bin/sh
set -e

echo "[entrypoint] Running database migrations..."
alembic upgrade head

if [ "${RUN_SEED:-false}" = "true" ]; then
  echo "[entrypoint] Seeding database..."
  python -m app.scripts.seed
fi

echo "[entrypoint] Starting API server..."
exec "$@"
