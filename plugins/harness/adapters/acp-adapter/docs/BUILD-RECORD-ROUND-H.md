# Round H artifact build record

The Round H acceptance chain runs the binary `acp-adapter-round-h` (repo root).
This record pins how it is reproduced byte-for-byte from this tree.

> **Superseded 2026-10-02.** The Round H digest below is **not reproducible from
> current source, by design**. Commit `e30f5ff6df` ("Retire duplicate Go Claude
> adapter in favor of pinned official ACP runtime", 2026-09-27) deleted
> `internal/claude/*` and `pkg/claudeacp/*`; today's `./cmd/acp` accepts
> `--adapter codex|pi` where the Round H tree accepted `codex|claude|pi`.
> Building current source yields sha256 `714044a5…` (7 477 986 → 7 371 366 B,
> the size delta consistent with that deletion), so `scripts/build-round-h.sh`
> now pins `714044a5…`; the flag rationale below still holds for it, all four
> flags remaining load-bearing. The Round H artifact is preserved verbatim as
> history and is cited by the pre-retirement evidence files
> (`packaging/acp-adapter/evidence/handshake-migrated-20260925.json`,
> `packaging/acp-adapter/README.md`); those records state what was observed on
> 2026-09-25 and were deliberately **not** rewritten. This record previously
> claimed reproducibility "from this tree", which stopped being true on
> 2026-09-27 and went unflagged until spec 021 P16.

## Artifact (pre-retirement source `e30f5ff6df^`)

| Item | Value |
| --- | --- |
| File | `acp-adapter-round-h` (repo root) |
| sha256 | `5fd6a37b127274eef5c2f27fe731a720e32e9bd64efd6df23e61fe739bbc61ea` |
| Built | 2026-09-25 15:50 (+0800), first verified reproducible same day |
| Source | branch `work/round-h` (this tree; Round H changes over upstream `v0.3.8` == `491151b16846682396aca8c31e9285e414e4f3b8`) |
| Toolchain | `/home/maoqh/ordessa-builds/go1.24.13` (go1.24.13 linux/amd64) |

## Command (recorded in `scripts/build-round-h.sh`)

```
CGO_ENABLED=0 /home/maoqh/ordessa-builds/go1.24.13/bin/go build \
  -trimpath -buildvcs=false -ldflags "-buildid=" \
  -o acp-adapter-round-h ./cmd/acp
```

Flag rationale — each one is load-bearing for byte-identity:

- `-trimpath`: strips machine-local paths so the build is root-independent;
- `-buildvcs=false`: no `vcs.revision`/`vcs.modified` stamp (stamping would
  make every dirty-state change produce a different binary);
- `-ldflags "-buildid="`: suppresses the `.note.go.buildid`/`.note.gnu.buildid`
  sections (their absence is visible in `readelf -S` of the pinned artifact);
- `CGO_ENABLED=0`: static, no toolchain libc variance.

## Verification history

- 2026-09-25 (this session): rebuilt from the then-uncommitted Round H tree —
  `cmp` byte-identical, sha256 equal. Two earlier probe builds
  (without `-buildvcs=false`, then without `-ldflags "-buildid="`) differed
  only in vcs/buildid notes, which is how the flag set was derived.
- Module has zero third-party requires (`go.sum` empty); the build does not
  depend on any network proxy.

## Related artifacts (NOT reproducible from this branch — kept only as evidence)

- `bc-native runtime/tools/acp-adapter/acp-adapter` (`7a727bdb…`): v0.3.8
  clean-tree build, used by the hd004b leg (port 57411).
- `bc-native runtime/tools/acp-adapter/acp-adapter-r11` (`00c48c3a…`): r11
  round build.
Both predate the Round H source changes; see bc-native
`runtime/tools/acp-adapter/BUILD-RECORD.md` for the v0.3.8 build.
