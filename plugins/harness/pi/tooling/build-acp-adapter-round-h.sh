#!/usr/bin/env bash
# Rebuild the Round-H Pi→ACP bridge from the source vendored in this monorepo.
#
# Source of record: plugins/harness/pi/vendor/acp-adapter (module path
# `github.com/beyond5959/acp-adapter` kept from upstream; commit
# 41d9d94ef6b98547df575240c4366b1e5e8ba39b, branch work/round-h).
# Toolchain pin: Go 1.24.13 linux-amd64 (tarball sha256
#   1fc94b57134d51669c72173ad5d49fd62afb0f1db9bf3f798fd98ee423f8d730).
# Reference artifact (historical, pre-`e30f5ff6df`): sha256
#   5fd6a37b127274eef5c2f27fe731a720e32e9bd64efd6df23e61fe739bbc61ea — reproducible
#   from the then-current vendored copy, verified 2026-09-25, kept as evidence.
# Current-tree artifact: sha256
#   f2878fd2935ec99a853abd97f827eed9f420a1159528ce404094f63ac88ef32f (re-pinned
#   2026-10-02, spec 021 P16). `e30f5ff6df` deleted the duplicate Go Claude adapter
#   from this source, which legitimately changed the digest on 2026-09-27. This
#   script only prints the digest; the enforced pins live in build-deb.mjs's
#   BRIDGE_SHA256_EXPECTED and plugins/harness/pi/vendor/acp-adapter/scripts/build-round-h.sh.
#
# Usage: build-acp-adapter-round-h.sh [output-path]
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SRC=${ORDESSA_PI_ACP_SOURCE:?set ORDESSA_PI_ACP_SOURCE to the reviewed Pi ACP adapter source}
EXPECTED_SRC=$(cd "$HERE/../vendor/acp-adapter" && pwd -P)
SRC=$(cd "$SRC" 2>/dev/null && pwd -P) || { echo "missing ACP source: $ORDESSA_PI_ACP_SOURCE"; exit 1; }
[ "$SRC" = "$EXPECTED_SRC" ] || { echo "unreviewed ACP source: $SRC (expected $EXPECTED_SRC)"; exit 1; }
[ -f "$SRC/go.mod" ] && grep -qx 'module github.com/beyond5959/acp-adapter' "$SRC/go.mod" || { echo "invalid ACP module identity: $SRC/go.mod"; exit 1; }
GOROOT=${GOROOT:?set GOROOT to the pinned Go 1.24.13 toolchain}
OUT=${1:-$HERE/acp-adapter}

GO_BIN=$GOROOT/bin/go
[ -x "$GO_BIN" ] || { echo "missing toolchain: $GO_BIN"; echo "set GOROOT to the pinned Go 1.24.13 linux/amd64 home"; exit 1; }

export GOROOT
export CGO_ENABLED=0
export GOPROXY=off
export GOTOOLCHAIN=local
export GOCACHE=${GOCACHE:-${TMPDIR:-/tmp}/ordessa-acp-gocache}
export GOMODCACHE=${GOMODCACHE:-${TMPDIR:-/tmp}/ordessa-acp-gomodcache}
mkdir -p "$GOCACHE" "$GOMODCACHE"

GO_VERSION=$("$GO_BIN" version)
[ "$GO_VERSION" = "go version go1.24.13 linux/amd64" ] || { echo "unreviewed Go toolchain: $GO_VERSION"; exit 1; }
echo "$GO_VERSION"
cd "$SRC"
"$GO_BIN" build -trimpath -buildvcs=false -ldflags "-buildid=" -o "$OUT" ./cmd/acp

echo "--- artifact ---"
sha256sum "$OUT"
ls -l "$OUT"
