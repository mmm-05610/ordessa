#!/usr/bin/env bash
# Counterexample runner (constitution IV / coordination stop-continue rule):
# every gate must be shown to FAIL under its deliberate behaviour break.
# Aggregate exit 0 == every injection was discriminated by its gate.
set -u
cd "$(dirname "$0")/../../.."   # repo root
PY=.venv/bin/python
GATES_DIR=plugins/profile/tests

run_ce() {
  local id="$1" gate="$2"
  PROFILE_COUNTEREXAMPLE="$id" "$PY" -m pytest "$GATES_DIR/$gate" -q \
    >"/tmp/ce-$id.log" 2>&1
  local code=$?
  local tail
  tail=$(tail -1 "/tmp/ce-$id.log")
  if [ "$code" -eq 0 ]; then
    echo "NOT-DISCRIMINATED  $id  ($gate): suite stayed green under the break"
    return 1
  fi
  echo "discriminated      $id  ($gate): $tail"
  return 0
}

failures=0
while IFS='|' read -r id gate; do
  [ -z "$id" ] && continue
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
  echo "counterexample runner: FAIL ($failures injections not discriminated)"
  exit 1
fi
echo "counterexample runner: OK (12/12 injections discriminated by their gates)"
exit 0
