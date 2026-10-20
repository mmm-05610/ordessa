#!/usr/bin/env bash
# Current-source safe verifier candidate; aggregate and full scopes require actual execution.
set -uo pipefail

SOURCE_INPUT=${ORDESSA_SOURCE_ROOT:?set ORDESSA_SOURCE_ROOT to the exact checkout to verify}
SOURCE_ROOT=$(cd -- "$SOURCE_INPUT" && pwd -P) || exit 2
[[ -d "$SOURCE_ROOT/.nightly-cache" && ! -L "$SOURCE_ROOT/.nightly-cache" ]] || { echo "FAIL: source root must have a real .nightly-cache" >&2; exit 2; }
SELF=$(cd -- "$(dirname -- "$0")" && pwd -P)/$(basename -- "$0")
SAFE_PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
VERIFY_PYTHON=${ORDESSA_VERIFY_PYTHON:-"$SOURCE_ROOT/.venv-nightly/bin/python"}
[[ "$VERIFY_PYTHON" == /* && -f "$VERIFY_PYTHON" && -x "$VERIFY_PYTHON" ]] || { echo "FAIL: verifier Python must be an explicit absolute executable" >&2; exit 2; }

# Bootstrap once with a fresh unique run directory directly under the checkout cache.
if [[ "${ORDESSA_VERIFY_CLEAN_SANITIZED:-}" != "1" ]]; then
  RUN_DIR=$(mktemp -d "$SOURCE_ROOT/.nightly-cache/verify-clean.XXXXXXXX") || exit 2
  mkdir -m 700 "$RUN_DIR/home" "$RUN_DIR/tmp" "$RUN_DIR/xdg-config" "$RUN_DIR/xdg-cache" || exit 2
  INPUT_PI_SOURCE=${ORDESSA_PI_ACP_SOURCE:-}
  INPUT_GOROOT=${GOROOT:-}
  exec env -i PATH="$SAFE_PATH" HOME="$RUN_DIR/home" TMPDIR="$RUN_DIR/tmp" \
    XDG_CONFIG_HOME="$RUN_DIR/xdg-config" XDG_CACHE_HOME="$RUN_DIR/xdg-cache" \
    ORDESSA_SOURCE_ROOT="$SOURCE_ROOT" ORDESSA_VERIFY_CLEAN_RUN_DIR="$RUN_DIR" \
    ORDESSA_PI_ACP_SOURCE="$INPUT_PI_SOURCE" GOROOT="$INPUT_GOROOT" \
    ORDESSA_VERIFY_PYTHON="$VERIFY_PYTHON" \
    ORDESSA_VERIFY_CLEAN_SANITIZED=1 bash --noprofile --norc "$SELF"
fi

RUN_DIR=${ORDESSA_VERIFY_CLEAN_RUN_DIR:?internal run directory absent}
[[ -d "$RUN_DIR" && ! -L "$RUN_DIR" ]] || { echo "FAIL: run directory invalid" >&2; exit 2; }
RUN_REAL=$(cd -- "$RUN_DIR" && pwd -P) || exit 2
[[ "$(dirname -- "$RUN_REAL")" == "$SOURCE_ROOT/.nightly-cache" && "$(basename -- "$RUN_REAL")" == verify-clean.* ]] || { echo "FAIL: run directory is not an owned direct cache child" >&2; exit 2; }
SCRATCH="$RUN_DIR/scratch"
mkdir -m 700 "$SCRATCH" || exit 2
ACTIVE_HELPER_PID=
ACTIVE_GATE_NAME=
SERVER_HELPER_PID=
SERVER_NAME=server_owned_temp_smoke
OWNED_CHILDREN_CLEAN=1
OWNED_HELPER="$SOURCE_ROOT/tooling/checks/verify-clean_owned_child.py"
PASS=0; FAIL=0
record() { printf '%s\n' "$*" >>"$RUN_DIR/gates.log"; printf '%s\n' "$*"; }
owned_marker() { printf '%s/%s.children-clean' "$RUN_DIR" "$1"; }

run_owned() {
  local name=$1; shift
  local marker input_fd
  marker=$(owned_marker "$name")
  rm -f -- "$marker"
  # Preserve the caller's stdin (notably a heredoc) on an explicit descriptor;
  # asynchronous Bash jobs otherwise receive /dev/null as stdin.
  exec {input_fd}<&0
  python3 "$OWNED_HELPER" --stdout "$RUN_DIR/$name.stdout" --stderr "$RUN_DIR/$name.stderr" \
    --result "$RUN_DIR/$name.child.json" --clean-marker "$marker" -- "$@" <&"$input_fd" &
  ACTIVE_HELPER_PID=$!
  ACTIVE_GATE_NAME=$name
  wait "$ACTIVE_HELPER_PID"
  local rc=$?
  exec {input_fd}<&-
  ACTIVE_HELPER_PID=
  ACTIVE_GATE_NAME=
  if [[ ! -f "$marker" || -L "$marker" ]]; then
    OWNED_CHILDREN_CLEAN=0
    record "OWNED CHILD CLEANUP UNKNOWN: $name; scratch will be retained"
  fi
  return "$rc"
}

stop_server_helper() {
  [[ -n "$SERVER_HELPER_PID" ]] || return 0
  kill -TERM "$SERVER_HELPER_PID" 2>/dev/null || true
  wait "$SERVER_HELPER_PID"; local rc=$?
  SERVER_HELPER_PID=
  if [[ ! -f "$(owned_marker "$SERVER_NAME")" || -L "$(owned_marker "$SERVER_NAME")" ]]; then
    OWNED_CHILDREN_CLEAN=0
    record "OWNED SERVER CLEANUP UNKNOWN; scratch will be retained"
  fi
  return "$rc"
}

handle_signal() {
  local sig=$1 code=$2
  trap - INT TERM
  if [[ -n "$ACTIVE_HELPER_PID" ]]; then
    local name=$ACTIVE_GATE_NAME
    kill -s "$sig" "$ACTIVE_HELPER_PID" 2>/dev/null || true
    wait "$ACTIVE_HELPER_PID"; local rc=$?
    printf '%s\n' "$rc" >"$RUN_DIR/$name.rc"
    ACTIVE_HELPER_PID=
    ACTIVE_GATE_NAME=
    if [[ ! -f "$(owned_marker "$name")" || -L "$(owned_marker "$name")" ]]; then OWNED_CHILDREN_CLEAN=0; fi
    record "GATE INTERRUPTED: $name signal=$sig helper_rc=$rc"
  fi
  if [[ -n "$SERVER_HELPER_PID" ]]; then
    kill -s "$sig" "$SERVER_HELPER_PID" 2>/dev/null || true
    wait "$SERVER_HELPER_PID"; local rc=$?
    SERVER_HELPER_PID=
    if [[ ! -f "$(owned_marker "$SERVER_NAME")" || -L "$(owned_marker "$SERVER_NAME")" ]]; then OWNED_CHILDREN_CLEAN=0; fi
    record "OWNED SERVER INTERRUPTED signal=$sig helper_rc=$rc"
  fi
  exit "$code"
}

gate() {
  local name=$1; shift
  record "GATE START: $name"
  run_owned "$name" "$@"
  local rc=$?; printf '%s\n' "$rc" >"$RUN_DIR/$name.rc"
  if [[ $rc -eq 0 ]]; then PASS=$((PASS+1)); record "GATE PASS: $name"; else FAIL=$((FAIL+1)); record "GATE FAIL: $name rc=$rc"; fi
  return 0
}
critical() {
  local name=$1; shift
  gate "$name" "$@"
  [[ $(cat "$RUN_DIR/$name.rc") -eq 0 ]]
}
cleanup() {
  local rc=$?
  trap - EXIT INT TERM
  if [[ -n "$ACTIVE_HELPER_PID" ]]; then
    kill -TERM "$ACTIVE_HELPER_PID" 2>/dev/null || true
    wait "$ACTIVE_HELPER_PID" || true
    if [[ ! -f "$(owned_marker "$ACTIVE_GATE_NAME")" || -L "$(owned_marker "$ACTIVE_GATE_NAME")" ]]; then OWNED_CHILDREN_CLEAN=0; fi
  fi
  if [[ -n "$SERVER_HELPER_PID" ]]; then stop_server_helper || true; fi
  if [[ "$SCRATCH" == "$RUN_DIR/scratch" && -d "$SCRATCH" && ! -L "$SCRATCH" ]]; then
    if [[ "$OWNED_CHILDREN_CLEAN" -eq 1 ]]; then rm -rf -- "$SCRATCH"; else record "SCRATCH RETAINED: owned child process-group exit not confirmed"; fi
  fi
  printf '%s\n' "$rc" >"$RUN_DIR/exit-code.txt"
}
trap cleanup EXIT
trap 'handle_signal INT 130' INT
trap 'handle_signal TERM 143' TERM

for needed in tooling/checks/verify-clean_snapshot.py tooling/checks/verify-clean_owned_child.py tooling/checks/verify_clean_python_gates.py tooling/checks/verify_clean_pytest_plugin.py tooling/checks/verify-clean-python-gates.json; do
  [[ -f "$SOURCE_ROOT/$needed" && ! -L "$SOURCE_ROOT/$needed" ]] || { record "GATE FAIL: required verifier input absent: $needed"; exit 2; }
done
critical bootstrap_python "$VERIFY_PYTHON" -I -c 'import sys; print(sys.executable); print(sys.version); assert sys.version_info[:3] == (3, 12, 14), "requires reviewed Python 3.12.14"' || { record "DEPENDENT GATES NOT_RUN: Python runtime refused"; exit 1; }
if ! run_owned source_top_level git -C "$SOURCE_ROOT" rev-parse --show-toplevel; then
  record "GATE FAIL: cannot identify Git top-level"; exit 2
fi
if [[ "$(cat "$RUN_DIR/source_top_level.stdout")" != "$SOURCE_ROOT" ]]; then
  record "GATE FAIL: source root is not Git top-level"; exit 2
fi
if ! run_owned source_head git -C "$SOURCE_ROOT" rev-parse HEAD; then
  record "GATE FAIL: cannot read source HEAD"; exit 2
fi
record "source=$SOURCE_ROOT"; record "head=$(cat "$RUN_DIR/source_head.stdout")"; record "run-dir=$RUN_DIR"
if ! run_owned snapshot python3 "$SOURCE_ROOT/tooling/checks/verify-clean_snapshot.py" "$SOURCE_ROOT" "$SCRATCH/source" "$RUN_DIR/source-manifest.json"; then
  record "GATE FAIL: source snapshot refused/incomplete; all dependent gates NOT_RUN"; FAIL=$((FAIL+1)); exit 1
fi
SNAPSHOT="$SCRATCH/source"
OWNED_HELPER="$SNAPSHOT/tooling/checks/verify-clean_owned_child.py"
cd "$SNAPSHOT" || exit 2
mkdir -m 700 "$SCRATCH/venv-home" "$SCRATCH/venv-tmp" "$SCRATCH/venv-xdg-config" "$SCRATCH/venv-xdg-cache"
export HOME="$SCRATCH/venv-home" TMPDIR="$SCRATCH/venv-tmp" XDG_CONFIG_HOME="$SCRATCH/venv-xdg-config" XDG_CACHE_HOME="$SCRATCH/venv-xdg-cache" PATH="$SAFE_PATH"

# Install gates are critical: no dependent test gate runs after incomplete preparation.
critical python_venv "$VERIFY_PYTHON" -m venv "$SCRATCH/venv" || { record "DEPENDENT GATES NOT_RUN"; exit 1; }
# shellcheck disable=SC1091
. "$SCRATCH/venv/bin/activate"
export PATH="$SCRATCH/venv/bin:$SAFE_PATH"
critical python_locked_requirements pip install --disable-pip-version-check -r tooling/workspace/nightly-python-requirements.txt || { record "DEPENDENT GATES NOT_RUN"; exit 1; }
critical server_runtime_lock pip install --disable-pip-version-check -r apps/server/lockfiles/server-linux-py312.txt || { record "DEPENDENT GATES NOT_RUN"; exit 1; }
if run_owned python_workspace_manifest python - <<'PY'
import json
from pathlib import Path
root=Path.cwd().resolve(); data=json.loads((root/'python-workspace.json').read_text(encoding='utf-8'))
projects=data['projects']; paths=[x['path'] for x in projects]; dists=[x['distribution'].casefold().replace('_','-') for x in projects]
if len(paths)!=len(set(paths)) or len(dists)!=len(set(dists)): raise SystemExit('duplicate project path/distribution')
for rel in paths:
 p=Path(rel)
 if p.is_absolute() or '..' in p.parts or not (root/p/'pyproject.toml').is_file(): raise SystemExit(f'invalid workspace project: {rel}')
print('\n'.join(paths))
PY
then
  mapfile -t projects <"$RUN_DIR/python_workspace_manifest.stdout"; args=(); for project in "${projects[@]}"; do args+=(-e "$project"); done
  critical python_editable_projects pip install --disable-pip-version-check --no-deps --no-build-isolation "${args[@]}" || { record "DEPENDENT GATES NOT_RUN"; exit 1; }
else record "GATE FAIL: Python workspace manifest invalid; dependent gates NOT_RUN"; FAIL=$((FAIL+1)); exit 1; fi
export ORDESSA_TEST_PYTHON="$SCRATCH/venv/bin/python"
critical npm_ci npm ci --no-audit --no-fund || { record "DEPENDENT GATES NOT_RUN"; exit 1; }
critical connector_npm_ci npm --prefix tests/integration/acp-connector ci --no-audit --no-fund || { record "DEPENDENT GATES NOT_RUN"; exit 1; }

gate current_owner_imports python -c 'import server_plugin_api, ordessa_units, ordessa_units.persistence.sqlite, ordessa_environments, ordessa_execution_agents, ordessa_execution_agents.harness.definitions, ordessa_execution_agents.profiles.management, ordessa_interfaces, ordessa_infrastructure, ordessa_server, ordessa_server.bootstrap.storage.product_database, ordessa_server.bootstrap.migrations.legacy_source, ordessa_server_product, ordessa_harness_hermes'
gate starlette_version python -c 'import starlette; assert starlette.__version__ == "1.7.0", starlette.__version__'
gate typecheck npm run typecheck
gate acp_connector_rig env ORDESSA_VITEST_CASE_LEDGER="$RUN_DIR/acp-connector.case.json" npx vitest run --root tests/integration/acp-connector --reporter=default --reporter="$SNAPSHOT/tooling/checks/vitest_case_ledger_reporter.mjs"
if [[ "$(<"$RUN_DIR/acp_connector_rig.rc")" -eq 0 ]]; then
  if run_owned acp_connector_case_ledger node --input-type=module - "$RUN_DIR/acp-connector.case.json" <<'JSLEDGER'
import { readAndValidateReport } from './tooling/checks/case-ledger.mjs'
const cases = await readAndValidateReport({ kind: 'vitest-json', path: process.argv[2], suiteName: 'acp connector rig' })
console.log(`${cases.length} actual cases pass without skip/xfail/XPASS`)
JSLEDGER
  then PASS=$((PASS+1)); record "GATE PASS: ACP connector case ledger"; else FAIL=$((FAIL+1)); record "GATE FAIL: ACP connector case ledger missing/non-clean"; fi
fi
gate product_foundations_build npm run build:foundations
gate desktop_product_build npm run build

# All Python suites are target-scoped. Exact current targets and applied migration paths
# are embedded in verify-clean-python-gates.json. A historical count is never treated as
# today's expected success; each collected ID must execute and pass without skip/error.
mkdir -m 700 "$RUN_DIR/python-ledger"
if run_owned python_owner_gates python tooling/checks/verify_clean_python_gates.py --snapshot "$SNAPSHOT" --run-dir "$RUN_DIR/python-ledger" --manifest tooling/checks/verify-clean-python-gates.json --python "$SCRATCH/venv/bin/python"; then
  PASS=$((PASS+1)); record "GATE PASS: all 8 original Python owner scopes and supplemental owner files have clean per-node ledgers"
else FAIL=$((FAIL+1)); record "GATE FAIL: one or more Python owner scopes failed or were NOT_RUN"; fi
# Supplemental aggregate result is diagnostic; it cannot substitute for the scoped ledgers.
gate js_aggregate_discovery npm test -- --list
gate js_aggregate_cases npm test
if [[ "$(<"$RUN_DIR/js_aggregate_cases.rc")" -eq 0 ]]; then
  if run_owned js_aggregate_case_ledger python - <<'PYLEDGER'
import json
from pathlib import Path
runs=Path('.nightly-cache/js-aggregate-caller/runs')
children=list(runs.glob('run-*'))
if len(children)!=1: raise SystemExit('expected exactly one actual aggregate run in fresh source snapshot')
run=json.loads((children[0]/'run.json').read_text())
s=json.loads((children[0]/'summary.json').read_text())
if run.get('filtered') is not False or run.get('totalInventory')!=53 or len(run.get('selectedSuites',[]))!=53:
 raise SystemExit('partial aggregate run is not a full acceptance gate')
if s.get('status')!='PASS' or s.get('failedSuites')!=[] or s.get('selectedSuiteCount')!=53 or s.get('inventorySuiteCount')!=53:
 raise SystemExit('actual full aggregate did not pass')
if s.get('passedCaseSuites')!=49 or s.get('successfulPrerequisiteGates')!=4:
 raise SystemExit('expected 49 reported case suites and four separate prerequisite gates')
cases=s.get('cases')
if not isinstance(cases,list) or not cases or s.get('validatedCaseCount')!=len(cases):
 raise SystemExit('aggregate case count missing or inconsistent')
if any(c.get('status')!='PASS' or not c.get('id') for c in cases): raise SystemExit('nonpassing or unidentified aggregate case')
print('full 53-suite aggregate has reconciled per-case reports')
PYLEDGER
  then PASS=$((PASS+1)); record "GATE PASS: actual JS aggregate case ledger"; else FAIL=$((FAIL+1)); record "GATE FAIL: aggregate ledger absent/partial/non-clean"; fi
else record "DEPENDENT GATE NOT_RUN: aggregate ledger acceptance after child failure"; fi
FAIL=$((FAIL+1)); record "GATE FAIL: historical per-node ledger equivalence NOT_PROVEN; old script retained summary counts but no node-ID oracle"

# The ACP bridge gate requires explicit original-owner input and pinned GOROOT.
if [[ -z "${ORDESSA_PI_ACP_SOURCE:-}" || -z "${GOROOT:-}" ]]; then
  FAIL=$((FAIL+1)); record "GATE FAIL: bridge requires explicit ORDESSA_PI_ACP_SOURCE and GOROOT; NOT_RUN"
elif [[ ! -d "$ORDESSA_PI_ACP_SOURCE" || "$(cd -- "$ORDESSA_PI_ACP_SOURCE" && pwd -P)" != "$SOURCE_ROOT/plugins/harness/pi/vendor/acp-adapter" || ! -x "$GOROOT/bin/go" ]]; then
  FAIL=$((FAIL+1)); record "GATE FAIL: bridge input/GOROOT is not the reviewed owner and toolchain; NOT_RUN"
else
  if ! run_owned bridge_toolchain_version "$GOROOT/bin/go" version || [[ "$(cat "$RUN_DIR/bridge_toolchain_version.stdout")" != "go version go1.24.13 linux/amd64" ]]; then
    FAIL=$((FAIL+1)); record "GATE FAIL: bridge toolchain is not the reviewed Go 1.24.13 linux/amd64; NOT_RUN"
  else
    ORDESSA_PI_ACP_SOURCE="$SNAPSHOT/plugins/harness/pi/vendor/acp-adapter"; export ORDESSA_PI_ACP_SOURCE GOROOT
    gate bridge_rebuild bash plugins/harness/pi/tooling/build-acp-adapter-round-h.sh "$SCRATCH/acp"
    if [[ -f "$SCRATCH/acp" ]] && run_owned bridge_digest sha256sum "$SCRATCH/acp"; then
      read -r got _ <"$RUN_DIR/bridge_digest.stdout"
      expected=714044a5b490a53d5fa89aade993c496e5fa3a5f7c614b4465c4990575185cbd
      printf '%s\n' "$got" >"$RUN_DIR/bridge.sha256"
      if [[ "$got" == "$expected" ]]; then PASS=$((PASS+1)); record "GATE PASS: bridge_digest"; else FAIL=$((FAIL+1)); record "GATE FAIL: bridge_digest got=$got expected=$expected"; fi
    else FAIL=$((FAIL+1)); record "GATE FAIL: bridge artifact missing or digest command failed"; fi
  fi
fi

# Owned local Server smoke only: fresh data root, OS-assigned loopback port, owned PID.
mkdir -m 700 "$SCRATCH/server-data" || { FAIL=$((FAIL+1)); record "GATE FAIL: temporary Server data root creation"; exit 1; }
python3 "$OWNED_HELPER" --stdout "$RUN_DIR/server.stdout" --stderr "$RUN_DIR/server.stderr" \
  --result "$RUN_DIR/$SERVER_NAME.child.json" --clean-marker "$(owned_marker "$SERVER_NAME")" -- \
  python -m ordessa_server --data-root "$SCRATCH/server-data" --port 0 & SERVER_HELPER_PID=$!
origin=
if run_owned server_origin_extract python -c 'import json,sys,time; from pathlib import Path; p=Path(sys.argv[1]); end=time.monotonic()+10
while time.monotonic()<end:
  try:
    for line in p.read_text(errors="replace").splitlines():
      try:
        e=json.loads(line)
        if e.get("event")=="listening" and isinstance(e.get("origin"),str): print(e["origin"],flush=True); raise SystemExit(0)
      except (ValueError,TypeError): pass
  except FileNotFoundError: pass
  time.sleep(.05)
raise SystemExit(1)' "$RUN_DIR/server.stdout"; then origin=$(<"$RUN_DIR/server_origin_extract.stdout"); fi
if [[ "$origin" =~ ^http://127\.0\.0\.1:[0-9]+$ ]] && run_owned server_owned_live curl --fail --silent --show-error --max-time 3 "$origin/live"; then PASS=$((PASS+1)); record "GATE PASS: server_owned_temp_smoke"; else FAIL=$((FAIL+1)); record "GATE FAIL: server_owned_temp_smoke"; fi
if [[ -n "$SERVER_HELPER_PID" ]]; then stop_server_helper; stop_rc=$?; if [[ -f "$(owned_marker "$SERVER_NAME")" && ( $stop_rc -eq 143 || $stop_rc -eq 0 ) ]]; then PASS=$((PASS+1)); record "GATE PASS: owned_server_stopped"; else FAIL=$((FAIL+1)); record "GATE FAIL: owned_server_stop helper_rc=$stop_rc"; fi; fi
record "RESULT: PASS=$PASS FAIL=$FAIL; evidence=$RUN_DIR"
[[ "$FAIL" -eq 0 ]]
