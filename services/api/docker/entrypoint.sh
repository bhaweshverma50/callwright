#!/bin/sh
# Container entrypoint: picks the role from the first argument, else $ROLE (default api).
#   api      uvicorn on $PORT behind the Cloud Run proxy (X-Forwarded-Proto/For honoured)
#   worker   arq worker plus a minimal HTTP health server on $PORT
#   migrate  alembic upgrade head, the agent templates sync and the built-in evaluator catalog
#            sync (007); exits
# Any other argument list runs as a plain command, for example
#   docker run --rm callwright-api python -m app.dev.make_admin ops@example.com
set -eu

role="${1:-${ROLE:-api}}"
if [ "$#" -gt 0 ]; then shift; fi

case "$role" in
  api)
    exec uvicorn app.main:app \
      --host 0.0.0.0 \
      --port "${PORT:-8080}" \
      --proxy-headers \
      --forwarded-allow-ips='*' \
      --timeout-graceful-shutdown 8 \
      "$@"
    ;;
  worker)
    exec python -m app.core.worker_main "$@"
    ;;
  migrate)
    alembic upgrade head
    python -m app.templates.jobs sync
    exec python -m app.evaluators.registry sync
    ;;
  *)
    exec "$role" "$@"
    ;;
esac
