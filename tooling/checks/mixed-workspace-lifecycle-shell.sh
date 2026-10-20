#!/bin/sh
set -eu
if [ "${npm_lifecycle_event-}" = "test" ] && [ "${1-}" = "-c" ] && [ "${2-}" = "${ORDESSA_MIXED_SCRIPT-}" ] && [ "${2-}" = 'vitest run --maxWorkers=1 && node --test tests/' ]; then
  shift 2
  "${ORDESSA_VITEST_BIN:?}" run --maxWorkers=1 --reporter="${ORDESSA_VITEST_REPORTER:?}" "$@"
  "${ORDESSA_NODE_BIN:?}" --test --test-reporter="${ORDESSA_NODE_REPORTER:?}" tests/
  exit $?
fi
exec /bin/sh "$@"
