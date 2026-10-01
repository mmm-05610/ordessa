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
step "desktop: unit tests (expect 146 passed / 0 failed)"
npm test 2>&1 | tail -3 | sed 's/^/  /'
n=$(npm test 2>&1 | grep -cE "Tests  146 passed")
[ "$n" -ge 1 ] && ok "desktop unit tests 146/146" || bad "desktop unit tests"
step "desktop: acp-connector rig (expect 79 passed)"
out=$( (cd tests/acp-connector && npm ci --no-audit --no-fund >/dev/null 2>&1 && npx vitest run 2>&1) )
echo "$out" | tail -2 | sed 's/^/  /'
echo "$out" | grep -qE "Tests  79 passed" && ok "acp-connector 79/79" || bad "acp-connector 79/79"
step "desktop: product assembly build"
npm run build:foundations >/dev/null 2>&1 && ok "build:foundations (9 extensions)" || bad "build:foundations"
npm run build >/dev/null 2>&1 && ok "apps/desktop build" || bad "apps/desktop build"

step "backend: venv (python3.12) + verified closure lockfile + editable installs"
python3.12 -m venv "$VENV" || { echo "venv failed"; exit 1; }
# shellcheck disable=SC1091
. "$VENV/bin/activate"
pip install -q --upgrade pip >/dev/null 2>&1
pip install -q -r apps/server/lockfiles/server-linux-py312.txt >/dev/null 2>&1 && ok "closure lockfile (28 pins)" || bad "closure lockfile"
pip install -q -e packages/pacthold -e apps/server -e 'plugins/harness[dev]' -e 'apps/server[dev]' -e 'packages/pacthold[dev]' >/dev/null 2>&1 && ok "editable installs x3 (+dev extras)" || bad "editable installs"
python -c "import pacthold, ordessa_server, ordessa_harness" 2>/dev/null && ok "imports" || bad "imports"
star=$(python -c "import starlette; print(starlette.__version__)")
echo "  starlette resolved: $star"
[ "$star" = "1.7.0" ] && ok "starlette pinned at verified 1.7.0" || bad "starlette drifted to $star"

step "backend suites (strict ledger gates; python -m pytest from repo root)"
# every run_suite call tees full output to $LOGDIR/suite-<label>.log (per-ID evidence)
run_suite "pacthold" packages/pacthold passed=238
run_suite "harness" plugins/harness passed=308 failed=2 skipped=3
run_suite "server" apps/server passed=783 failed=43 skipped=10 errors=25
run_suite "acp_orchestration" tests/acp_orchestration passed=40 failed=18

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
