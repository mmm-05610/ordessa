#!/usr/bin/env bash
# Reproducible build of the bridge artifact from this tree.
#
# Produces a byte-identical copy of the current-tree bridge and refuses to
# exit 0 on any digest mismatch. See docs/BUILD-RECORD-ROUND-H.md for the flag
# rationale and the verification history.
#
# The pinned digest is what this tree builds TODAY. The Round H digest
# (5fd6a37b...) applied to the pre-retirement source `e30f5ff6df^`, which still
# contained the duplicate Go Claude adapter; `e30f5ff6df` ("Retire duplicate Go
# Claude adapter in favor of pinned official ACP runtime") deleted it, so no
# build from current source can reproduce the Round H digest again. That
# artifact stays recorded in docs/BUILD-RECORD-ROUND-H.md as history — it is
# unreproducible from this branch by design, not by drift.
set -euo pipefail

GO=${GO:-/home/maoqh/ordessa-builds/go1.24.13/bin/go}
OUT=${1:-acp-adapter-round-h}
# The later legal Pi error-response slice is qualified in Execution's
# pi-failure-protocol/receipt.json and pi-native-model-preservation handoff.
SHA_EXPECTED=5a2f8f008fdf6fdf274d99f358c37477d8bcf8c4bfacf8cefef2630ef12d1c84

cd "$(dirname "$0")/.."
CGO_ENABLED=0 "$GO" build -trimpath -buildvcs=false -ldflags "-buildid=" -o "$OUT" ./cmd/acp

GOT=$(sha256sum "$OUT" | cut -d' ' -f1)
echo "built  : $OUT"
echo "sha256 : $GOT"
if [ "$GOT" != "$SHA_EXPECTED" ]; then
  echo "REFUSE: digest mismatch vs pinned current-tree artifact $SHA_EXPECTED" >&2
  exit 1
fi
echo "MATCH: pinned current-tree artifact reproduced byte-for-byte"
