#!/bin/sh
set -eu
expected_event=${ORDESSA_EXPECTED_NPM_EVENT:-test}
expected_script=${ORDESSA_EXPECTED_NPM_SCRIPT-}
if [ "${npm_lifecycle_event-}" = "$expected_event" ] && [ "${1-}" = '-c' ]; then
  if [ "${2-}" != "$expected_script" ]; then
    echo "npm script changed for $expected_event; refusing uninstrumented execution" >&2
    exit 2
  fi
  shift 2
  if [ "$#" -ne 0 ]; then
    echo 'unexpected forwarded test arguments; refusing an unreviewed filter' >&2
    exit 2
  fi
  case "$expected_script" in
    'vitest run')
      : "${ORDESSA_VITEST_REPORTER:?required Vitest case reporter}"
      exec /bin/sh -c 'exec vitest run --reporter=default --reporter="$ORDESSA_VITEST_REPORTER"' "$@"
      ;;
    'vitest run --maxWorkers=1')
      : "${ORDESSA_VITEST_REPORTER:?required Vitest case reporter}"
      exec /bin/sh -c 'exec vitest run --maxWorkers=1 --reporter=default --reporter="$ORDESSA_VITEST_REPORTER"' "$@"
      ;;
    'node --test tests/test.mjs')
      : "${ORDESSA_NODE_REPORTER:?required Node event reporter}"
      exec /bin/sh -c 'exec node --test --test-reporter="$ORDESSA_NODE_REPORTER" tests/test.mjs' "$@"
      ;;
    *)
      echo "unreviewed npm test script: $expected_script" >&2
      exit 2
      ;;
  esac
fi
# npm pre/post hooks and unrelated scripts follow their original shell path.
exec /bin/sh "$@"
