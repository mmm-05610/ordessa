# ACP adapter (Round-H bridge) — vendored source and rebuild

This directory holds the Go source of the Pi→ACP bridge inside the Harness
plugin (`adapters/acp-adapter/`, one level up), plus the rebuild tooling.

- Upstream module path: `github.com/beyond5959/acp-adapter` (kept from
  upstream; not renamed).
- Source of record: commit `41d9d94ef6b98547df575240c4366b1e5e8ba39b`
  (branch `work/round-h` of `/home/maoqh/ordessa-builds/acp-adapter`),
  vendored here, with `e30f5ff6df` later removing the duplicate Go Claude
  adapter from it.
- Toolchain pin: Go 1.24.13 linux-amd64 (tarball sha256
  `1fc94b57134d51669c72173ad5d49fd62afb0f1db9bf3f798fd98ee423f8d730`).
- Reference artifact (historical, **pre-`e30f5ff6df`**): sha256
  `5fd6a37b127274eef5c2f27fe731a720e32e9bd64efd6df23e61fe739bbc61ea`
  (round-h bridge; byte-for-byte reproducible from the then-current vendored
  copy, re-verified 2026-09-25). Kept as evidence for the 2026-09-25 handshake
  in `evidence/handshake-migrated-20260925.json`; **not** reproducible from
  current source.
- Current-tree reference artifact: sha256
  `714044a5b490a53d5fa89aade993c496e5fa3a5f7c614b4465c4990575185cbd`
  (re-pinned 2026-10-02, spec 021 P16; this is also what the deb stages to
  `/opt/ordessa/bin/acp`).

## Rebuild

```bash
GOROOT=/path/to/go1.24.13 ./build-acp-adapter-round-h.sh [output]
# CGO_ENABLED=0 go build -trimpath -buildvcs=false -ldflags "-buildid=" ./cmd/acp
```

No third-party Go dependencies (built with `GOPROXY=off`).

## No-model handshake check

`handshake-check.py` (carried from the acceptance chain) spawns the bridge
exactly as the Server's managed channel does and replays a captured
`initialize` frame. It stops before any session/prompt: no model process, no
credential read. See `BUILD-RECORD.md` for the historical build and evidence
record (the `v0.3.8` pins there describe the earlier hd004b leg, which is not
migrated).
