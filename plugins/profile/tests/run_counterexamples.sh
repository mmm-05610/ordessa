#!/usr/bin/env bash
# Counterexample runner (constitution IV / coordination stop-continue rule):
# every gate must be shown to FAIL under its deliberate behaviour break.
# Aggregate exit 0 == every injection was discriminated by its gate.
set -u
cd "$(dirname "$0")/../../.."   # repo root
GATES_DIR=plugins/profile/tests

# Interpreter choice. A hardcoded .venv/bin/python does not exist in every
# worktree, and silently running against an interpreter that cannot import the
# package turns every gate into an import error -- which the old pass criterion
# counted as "discriminated". $ORDESSA_TEST_PYTHON wins, then the integration
# venv, then the repo .venv. Whichever is chosen must actually import
# ordessa_profile; otherwise this runner refuses rather than reporting green.
PY="${ORDESSA_TEST_PYTHON:-}"
if [ -z "$PY" ]; then
  for candidate in .cleanup-evidence/product-integration-venv/bin/python .venv/bin/python; do
    if [ -x "$candidate" ]; then PY="$candidate"; break; fi
  done
fi
if [ -z "$PY" ] || [ ! -x "$PY" ]; then
  echo "counterexample runner: NO INTERPRETER (set ORDESSA_TEST_PYTHON)" >&2
  exit 1
fi
if ! "$PY" -c 'import ordessa_profile' >/dev/null 2>&1; then
  echo "counterexample runner: REFUSING -- $PY cannot import ordessa_profile." >&2
  echo "  An interpreter that cannot import the package makes every gate die at" >&2
  echo "  import, which is NOT evidence that an injection was discriminated." >&2
  exit 1
fi

# A gate that is not green BEFORE injection cannot discriminate anything: its
# red would be pre-existing, not caused by the break.
baseline_green() {
  local gate="$1"
  "$PY" -m pytest "$GATES_DIR/$gate" -q >"/tmp/ce-baseline-$gate.log" 2>&1
}

run_ce() {
  local id="$1" gate="$2"
  if ! baseline_green "$gate"; then
    echo "NOT-DISCRIMINATED  $id  ($gate): gate is not green without injection, so" \
         "it cannot witness a break ($(tail -1 "/tmp/ce-baseline-$gate.log"))"
    return 1
  fi
  PROFILE_COUNTEREXAMPLE="$id" "$PY" -m pytest "$GATES_DIR/$gate" -q \
    >"/tmp/ce-$id.log" 2>&1
  local code=$?
  local tail
  tail=$(tail -1 "/tmp/ce-$id.log")
  # A collection/import/usability failure means the gate never really ran, so its
  # red says nothing about the injection. pytest uses 4 for usage errors and 5
  # when nothing was collected; an import crash shows up in the output text.
  if [ "$code" -eq 4 ] || [ "$code" -eq 5 ] \
     || grep -qE 'ModuleNotFoundError|ImportError while importing' "/tmp/ce-$id.log"; then
    echo "NOT-DISCRIMINATED  $id  ($gate): gate did not run (exit $code): $tail"
    return 1
  fi
  if [ "$code" -eq 0 ]; then
    echo "NOT-DISCRIMINATED  $id  ($gate): suite stayed green under the break"
    return 1
  fi
  echo "discriminated      $id  ($gate): $tail"
  return 0
}

failures=0
total=0
while IFS='|' read -r id gate; do
  [ -z "$id" ] && continue
  total=$((total + 1))
  run_ce "$id" "$gate" || failures=$((failures + 1))
done <<'INJECTIONS'
version_ignored|test_us1_profiles.py
idempotency_off|test_us1_profiles.py
facet_last_wins|test_us4_facets.py
unload_deletes|test_us4_facets.py
required_defaults|test_us4_facets.py
overlay_masks_facet|test_us3_overlays.py
overlay_writes_profile|test_us3_overlays.py
partial_apply|test_us2_switch.py
assume_switched|test_us2_switch.py
select_any_target|test_us2_switch.py
secrets_allowed|test_us5_projection.py
migration_lossy|test_migration.py
INJECTIONS

if [ "$failures" -ne 0 ]; then
  echo "counterexample runner: FAIL ($failures of $total injections not discriminated)"
  exit 1
fi
echo "counterexample runner: OK ($total/$total injections discriminated by their gates)"
exit 0
