#!/usr/bin/env bash
# Clean-checkout verification of the Ordessa monorepo candidate. v2 — strict.
#
# Every step is gated: exit codes and parsed pytest summaries are compared
# against the expected ledger; collection interruptions are FAIL by
# definition. Known reds are asserted at their exact counts — a *new* red,
# a missing inherited red, or an unrunnable suite all fail this script.
set -u
CAND=${ORDESSA_CANDIDATE:-/home/maoqh/projects/ordessa}
CLEAN=/home/maoqh/projects/ordessa-verify-clean
VENV=/tmp/ordessa-verify-venv
BRIDGE_OUT=/tmp/ordessa-verify-bridge
# Current-tree bridge digest. Was 5fd6a37b..., which is the pre-retirement
# source `e30f5ff6df^`; e30f5ff6df removed the duplicate Go Claude adapter and
# the digest legitimately changed. Re-pinned 2026-10-02 (spec 021 P16).
WANT_SHA=714044a5b490a53d5fa89aade993c496e5fa3a5f7c614b4465c4990575185cbd
PASS=0; FAIL=0
step() { echo; echo "=== $1"; }
ok()   { echo "PASS: $1"; PASS=$((PASS+1)); }
bad()  { echo "FAIL: $1"; FAIL=$((FAIL+1)); }

# run_suite <label> <pytest target> [expected k=v ...]
# expected keys: passed failed skipped errors (missing key defaults to 0)
LOGDIR=${ORDESSA_VERIFY_LOGDIR:-$(dirname "$CLEAN")/verify-logs}  # outside the repo on purpose
run_suite() {
  local label="$1" target="$2"; shift 2
  local out rc
  out=$(cd "$CLEAN" && python3 -m pytest -q "$target" 2>&1); rc=$?
  mkdir -p "$LOGDIR"; printf '%s' "$out" > "$LOGDIR/suite-$label.log"
  echo "$out" | tail -2 | sed 's/^/  /'
  if echo "$out" | grep -qE "Interrupted|error during collection|no tests ran"; then
    bad "$label: did not run cleanly (collection interruption)"; return
  fi
  local sline; sline=$(echo "$out" | grep -E "in [0-9]+[0-9.]*s( \([0-9:]+\))?$" | tail -1)
  [ -z "$sline" ] && { bad "$label: no pytest summary line (rc=$rc)"; return; }
  echo "  summary: $sline"
  local got; got=$(echo "$sline" | tr ',' '\n' | grep -E "[0-9]+ (passed|failed|skipped|errors?)" | awk '{print $2"="$1}' | sed 's/error=/errors=/' | tr '\n' ' ')
  local exp="passed=0 failed=0 skipped=0 errors=0 " k v g badcnt=0 kv
  for kv in "$@"; do
    case "$kv" in passed=*|failed=*|skipped=*|errors=*)
      k="${kv%%=*}"
      exp=$(echo "$exp" | tr ' ' '\n' | grep -v "^$k=" | tr '\n' ' ')
      exp="$exp$kv " ;;
    esac
  done
  for kv in $exp; do
    k="${kv%%=*}"; v="${kv#*=}"
    g=$(echo "$got" | tr ' ' '\n' | grep -E "^$k=" | cut -d= -f2); g=${g:-0}
    if [ "$g" != "$v" ]; then bad "$label: $k=$g expected $v"; badcnt=$((badcnt+1)); fi
  done
  [ $badcnt -eq 0 ] && ok "$label: ledger matches ($exp)"
}

rm -rf "$CLEAN" "$VENV" "$BRIDGE_OUT"
step "clone candidate"
git clone -q "$CAND" "$CLEAN" || { echo "clone failed"; exit 1; }
cd "$CLEAN"
echo "HEAD: $(git log --oneline -1)"
echo "files: $(git ls-files | wc -l)"

step "desktop: npm ci"
npm ci --no-audit --no-fund >/dev/null 2>&1 && ok "npm ci" || bad "npm ci"
step "desktop: typecheck"
npm run typecheck >/dev/null 2>&1 && ok "typecheck" || bad "typecheck"
step "desktop: unit tests (npm test aggregate; every suite must pass)"
# `npm test` is the root aggregate (tooling/test-all.mjs): it runs many suites and
# prints one "Tests  N passed" line PER SUITE, never a single total. The old gate
# grepped for a literal "Tests  146 passed", which no aggregate output has ever
# contained, so it could only ever report bad. Assert the real contract instead:
# the aggregate exits 0 and no suite reports a failure.
agg=$(npm test 2>&1); agg_rc=$?
printf '%s\n' "$agg" | tail -3 | sed 's/^/  /'
if [ "$agg_rc" -eq 0 ] && ! printf '%s\n' "$agg" | grep -qE "^ +Tests +[0-9]+ failed"; then
  ok "desktop unit tests (aggregate green)"
else
  bad "desktop unit tests (aggregate rc=$agg_rc)"
  printf '%s\n' "$agg" | grep -E "^ +Tests +[0-9]+ failed" | sed 's/^/    /'
fi
step "desktop: acp-connector rig (expect 81 passed)"
# The rig moved to tests/integration/acp-connector and is invoked with an explicit
# --root (tooling/test-all.mjs:61); the old path and a bare `npx vitest` found
# nothing. It resolves vitest from the root workspace, so run it from the root.
out=$( (cd tests/integration/acp-connector && npm ci --no-audit --no-fund >/dev/null 2>&1) \
       && npx vitest run --root tests/integration/acp-connector 2>&1)
echo "$out" | tail -2 | sed 's/^/  /'
echo "$out" | grep -qE "Tests  81 passed" && ok "acp-connector 81/81" || bad "acp-connector 81/81"
step "desktop: product assembly build"
npm run build:foundations >/dev/null 2>&1 && ok "build:foundations" || bad "build:foundations"
npm run build >/dev/null 2>&1 && ok "apps/desktop build" || bad "apps/desktop build"

step "backend: venv (python3.12) + verified closure lockfile + editable installs"
python3.12 -m venv "$VENV" || { echo "venv failed"; exit 1; }
# shellcheck disable=SC1091
. "$VENV/bin/activate"
pip install -q --upgrade pip >/dev/null 2>&1
pins=$(grep -cE '^[A-Za-z0-9_.-]+==' apps/server/lockfiles/server-linux-py312.txt)
echo "  closure lockfile: $pins pinned distributions"
pip install -q -r apps/server/lockfiles/server-linux-py312.txt >/dev/null 2>&1 && ok "closure lockfile ($pins pins)" || bad "closure lockfile"
# Every installable package in the tree. All but pacthold are local-only (no index
# release) and are depended on by name, so dropping any one of them fails the whole
# editable step with "No matching distribution found" and every suite gate below
# then reports from a venv that cannot import the tree at all. That is exactly what
# this script did: it carried a 5-package list from before the post-010 package
# split, so `ordessa_harness` failed to import on `pacthold_runtime_compat` and the
# gate never reached its own suite steps. The API packages must be installed before
# the backends that depend on them. Verified end-to-end in a clean clone.
pip install -q \
  -e 'packages/backend/pacthold[dev]' \
  -e packages/backend/server-plugin-api \
  -e packages/backend/environment-api \
  -e packages/backend/persistence-sqlite \
  -e packages/backend/platform-services \
  -e plugins/harness/api \
  -e plugins/permissions/api \
  -e plugins/permissions/backend \
  -e plugins/permissions/adapters \
  -e plugins/assets/sandbox/api \
  -e plugins/assets/sandbox/adapters \
  -e plugins/assets/sandbox/backend \
  -e plugins/assets/model-provider/profile-contribution \
  -e plugins/assets/model-provider/server \
  -e plugins/assets/skills \
  -e plugins/profile \
  -e plugins/runtime-compat \
  -e plugins/server-compat \
  -e plugins/workspace \
  -e 'apps/server[dev]' \
  -e 'plugins/harness[dev]' \
  -e products/server \
  >/dev/null 2>&1 && ok "editable installs (all 21 in-tree packages)" || bad "editable installs"
python -c "import pacthold, server_plugin_api, ordessa_environment_api, ordessa_persistence_sqlite, ordessa_platform_services, ordessa_harness_api, ordessa_server, ordessa_harness, ordessa_server_product" 2>/dev/null && ok "imports" || bad "imports"
star=$(python -c "import starlette; print(starlette.__version__)")
echo "  starlette resolved: $star"
[ "$star" = "1.7.0" ] && ok "starlette pinned at verified 1.7.0" || bad "starlette drifted to $star"

step "backend suites (strict ledger gates; python -m pytest from repo root)"
# every run_suite call tees full output to $LOGDIR/suite-<label>.log (per-ID evidence)
# Re-measured 2026-10-02 in a clean clone of this tree with the install set above,
# each suite run twice for stability. The previous numbers were the 2026-09-26
# switch baseline and had drifted, and the acp_orchestration path
# (`tests/acp_orchestration`) no longer exists, so that suite collected nothing at
# all. These pins fail on ANY deviation — a new red, a fixed red, or a count change.
# Treat a change as a real event to attribute, not a number to refresh: see
# docs/known-issues.md for what each red means today.
# NOTE: `plugins/harness` is pinned at 792/3/3/**3 errors** — not at its 795-passed
# result — because this script always runs with the venv activated, and under an
# activated venv three tests that `pip install` a fixture adapter error instead of
# passing (795 without activation, 792 + 3 errors with it, both reproduced on
# 2026-10-02). The pin states what this gate actually observes; the underlying
# sensitivity is registered in docs/known-issues.md.
run_suite "pacthold" packages/backend/pacthold passed=212
run_suite "harness" plugins/harness passed=792 failed=3 skipped=3 errors=3
run_suite "server" apps/server passed=1187 failed=64 skipped=9 errors=2
run_suite "acp_orchestration" tests/integration/acp_orchestration passed=31 failed=28
# New backend packages from the 026 migration (005 codeReady). Counts measured
# 2026-10-03 in this tree; all three suites are green.
run_suite "environment-api" packages/backend/environment-api passed=33
run_suite "persistence-sqlite" packages/backend/persistence-sqlite passed=20
run_suite "platform-services" packages/backend/platform-services passed=7

step "bridge: byte-identical rebuild from clean clone"
bash plugins/harness/packaging/acp-adapter/build-acp-adapter-round-h.sh "$BRIDGE_OUT" >/dev/null 2>&1
GOT=$(sha256sum "$BRIDGE_OUT" 2>/dev/null | cut -d' ' -f1)
echo "  got  $GOT"; echo "  want $WANT_SHA"
[ "$GOT" = "$WANT_SHA" ] && ok "bridge sha256 byte-identical" || bad "bridge sha256"

step "server smoke on 127.0.0.1:8941"
bash scripts/start-server.sh 8941 >/tmp/ordessa-verify-server.log 2>&1 &
SH_PID=$!
sleep 6
BODY=$(curl -s --max-time 5 http://127.0.0.1:8941/live || echo CURL_FAILED)
echo "  /live -> $BODY"
case "$BODY" in *alive*) ok "server /live alive";; *) bad "server /live ($BODY)";; esac
kill $SH_PID 2>/dev/null; wait $SH_PID 2>/dev/null
sleep 1
if ss -tln 2>/dev/null | grep -q ':8941 '; then bad "port 8941 still open"; else ok "server exited, port closed"; fi

echo
echo "RESULT: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
