# Pi→ACP bridge — restored build record

The acceptance chain's only missing startup artifact was the Pi→ACP bridge
binary, which HD-002 kept under `/tmp/hd002-bc-go124-pTbe5u/out/acp-adapter`
and which no longer exists. It is rebuilt from the **same approved source pin
and the same toolchain version** (no bridge swap, no version bump) and now
lives inside this repository so launch commands never bind to `/tmp` again.
No protocol problem was found; Pi itself was already present and hash-matched.

## Pins (unchanged, approved)

| Item | Value |
| --- | --- |
| Upstream | `https://github.com/beyond5959/acp-adapter` |
| Tag / commit | `v0.3.8` → peels to `491151b16846682396aca8c31e9285e414e4f3b8` (verified with `git rev-parse v0.3.8^{commit}`) |
| Module / language | `module github.com/beyond5959/acp-adapter`, `go 1.24`, **no third-party require lines** (built with `GOPROXY=off`) |
| Toolchain | Go 1.24.13 linux-amd64, tarball sha256 `1fc94b57134d51669c72173ad5d49fd62afb0f1db9bf3f798fd98ee423f8d730` — computed and matched against `https://go.dev/dl/?mode=json&include=all` |
| Pi bundle (not rebuilt) | `/home/maoqh/.pi/agent/install/releases/0.86.1/…/dist/bundle/cli.js`, sha256 `e79626f2dd6f94aa45d30f3fa63cd84319a6eefcd150b353cfaf274366926774` — matches the HD-002 pin in `scripts/hd002/native_product_two_turn_gate.py:16` |

## Source and toolchain homes (stable, outside the git tree)

```
/home/maoqh/ordessa-builds/acp-adapter        # git checkout of v0.3.8, clean tree
/home/maoqh/ordessa-builds/go1.24.13          # extracted toolchain
/home/maoqh/ordessa-builds/cache/acp-adapter-*  # GOCACHE / GOMODCACHE / GOPATH / TMPDIR
```

## Build

`build-acp-adapter.sh` in this directory is the recorded command; it refuses on
a dirty tree, on a commit/tag mismatch, and on a missing toolchain. Equivalent
one-liner:

```bash
cd /home/maoqh/ordessa-builds/acp-adapter && git checkout v0.3.8
GOFLAGS=-trimpath CGO_ENABLED=0 GOPROXY=off GOTOOLCHAIN=local \
  /home/maoqh/ordessa-builds/go1.24.13/bin/go build \
  -buildvcs=false -trimpath -ldflags "-buildid=" -o <this dir>/acp-adapter ./cmd/acp
```

## Artifact

```
runtime/tools/acp-adapter/acp-adapter   ELF 64-bit x86-64, statically linked
size   7459636 bytes
sha256 7a727bdb5a8d6f569ad3adf22e7b43fbd70bbfa82bc86ee0eb75e0cd1a9fac68
```

This digest differs from the lost HD-002 binary
(`da8deda5f859d8f2b5f30446e27088ecd776e1a94`). The inputs that matter are
identical (same commit, same `go` release); the delta is build-time flags and
paths — HD-002 recorded no `-trimpath`/`-buildid` choice, so byte-equality is
not expected and is **not** evidence of a version change. The identity check
that does pin semantics is the handshake below plus
`agentInfo.name = "acp-adapter"`, and the Pi-side digest match.

## No-model launch / handshake check (this round)

`handshake-check.py` spawns the bridge exactly as the Server's managed channel
does (`--adapter=pi --pi-bin=<pinned cli.js> --pi-session-dir=<fresh dir>`),
replays the real `initialize` frame captured from the production seam
(`{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":1,
"clientCapabilities":{}}}`, from `artifacts/peer-frames/peer.355788.hd004-main`),
and stops — no `session/new`, no `session/prompt`, so no Pi process, no provider
contact, no credential read.

Result (`evidence/hd004b-bridge-handshake.json`):

```
verdict                HANDSHAKE_OK_NO_MODEL_CALL
protocolVersion        1
agentCapabilities      images, loadSession, mcpCapabilities, permissions,
                       promptCapabilities{image,embeddedContext},
                       sessionCapabilities, sessions, slashCommands, toolCalls
authMethods            ["pi"]   (activeAuthMethod: pi)
agentInfo              acp-adapter / version "dev" (not stamped by this build)
piChildrenAtHandshake  []       — proves nothing was spawned
exitCode               0        bridgeStderr empty
```

Re-run at any time (read-only, safe):

```bash
python3 runtime/tools/acp-adapter/handshake-check.py \
  runtime/tools/acp-adapter/acp-adapter \
  /home/maoqh/.pi/agent/install/releases/0.86.1/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js \
  runtime/tools/acp-adapter/evidence/hd004b-bridge-handshake.json
```

## Acceptance launch (user-run)

```bash
scripts/hd004b/start-pi-server.sh 57411      # prefights hashes + PI_* overlays
scripts/hd004b/start-pi-desktop.sh 57411     # real Electron, paired by env only
```

`~/ordessa-acceptance/hd004b/state-logs/pi-acp-frames.jsonl` is the bridge's raw
frame trace; after the **first** send, `grep -c '"session/prompt"' <file>` must
be `1` — see the report's remaining-issues note on the unreproduced duplicate.

## Addendum — Round H artifact (2026-09-25)

`acp-adapter-round-h` (this directory, untracked by the `acp-adapter*`
ignore above) is the CURRENT bridge of the Round H acceptance chain:

- sha256 `5fd6a37b127274eef5c2f27fe731a720e32e9bd64efd6df23e61fe739bbc61ea`
- source: `~/ordessa-builds/acp-adapter` branch `work/round-h`
  (Round H changes over v0.3.8, committed locally; never pushed)
- rebuild: that repo's `scripts/build-round-h.sh` — verified 2026-09-25 to
  reproduce the artifact **byte-for-byte**
  (`CGO_ENABLED=0 go build -trimpath -buildvcs=false -ldflags "-buildid=" ./cmd/acp`)
- launcher: `scripts/hd004b/start-pi-server-round-h.sh` (port 57415,
  ACCEPT_ROOT default `~/ordessa-acceptance/round-h-cp`)

The earlier `acp-adapter` (`7a727bdb…`, hd004b leg) and `acp-adapter-r11`
(`00c48c3a…`) predate the Round H source changes and are kept only as
evidence of those rounds; they are NOT reproducible from work/round-h.
