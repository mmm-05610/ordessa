#!/bin/sh
set -eu

expected='mkdir -p .nightly-cache/harness-test-tmp && TMPDIR="${TMPDIR:-$PWD/.nightly-cache/harness-test-tmp}" node --test --test-concurrency=1 "plugins/harness/*/tests/packaging/**/*.test.mjs"'
if [ "${npm_lifecycle_event-}" = 'test:harness-packaging' ] && [ "${1-}" = '-c' ]; then
  if [ "${2-}" != "$expected" ]; then
    echo 'test:harness-packaging script changed; refusing uninstrumented execution' >&2
    exit 2
  fi
  : "${ORDESSA_NODE_REPORTER:?required Node event reporter path}"
  shift 2
  instrumented='mkdir -p .nightly-cache/harness-test-tmp && TMPDIR="${TMPDIR:-$PWD/.nightly-cache/harness-test-tmp}" node --test --test-concurrency=1 --test-reporter="$ORDESSA_NODE_REPORTER" "plugins/harness/*/tests/packaging/**/*.test.mjs"'
  exec /bin/sh -c "$instrumented" "$@"
fi

# Keep npm lifecycle hooks and every unreviewed script on their normal shell path.
exec /bin/sh "$@"
