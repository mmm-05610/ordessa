Current source after the Pi failure-protocol repair builds sha256 `5a2f8f008fdf6fdf274d99f358c37477d8bcf8c4bfacf8cefef2630ef12d1c84` using the unchanged pinned Go 1.24.13 toolchain and reproducible flags. This digest was already qualified in `docs/implementation/execution-unit-environment-20261011/evidence/codex-takeover/pi-failure-protocol/receipt.json` and `pi-native-model-preservation/CONSUMER-CONTRACT.md`. On 2026-10-12 two offline temporary builds reproduced that same digest; the build-script pin was corrected to that qualified source. No Go source, `.toolchains` artifact or user service was changed. This reproduction does not claim a fresh execution of the earlier full Go test scope.

The ADR-0060 intermediate artifact `f2878fd2935ec99a853abd97f827eed9f420a1159528ce404094f63ac88ef32f` and ADR-0059 artifact below remain historical. Actual SDK Unit joint verification is recorded in Execution takeover evidence.

# Standard notification repair artifact (2026-10-11)

Current source with ADR-0059 builds sha256 `59441be7736fde2726c7a1c9537d679607d15c5934cd48f8f10a2d91f66bf33f` using Go 1.24.13, CGO_ENABLED=0, -trimpath -buildvcs=false -ldflags=-buildid=. Plugin build script pin is updated. Desktop packaging and root verification pins require coordinated integration. Prior artifact `714044a5b490a53d5fa89aade993c496e5fa3a5f7c614b4465c4990575185cbd` is retained as historical evidence, not overwritten.

# Round H artifact build record

The Round H acceptance chain runs the binary `acp-adapter-round-h` (repo root).
This record pins how it is reproduced byte-for-byte from this tree.

> **Superseded 2026-10-02.** The Round H digest below is **not reproducible from
> current source, by design**. Commit `e30f5ff6df` ("Retire duplicate Go Claude
> adapter in favor of pinned official ACP runtime", 2026-09-27) deleted
> `internal/claude/*` and `pkg/claudeacp/*`; today's `./cmd/acp` accepts
> `--adapter codex|pi` where the Round H tree accepted `codex|claude|pi`.
> Building the 2026-10-02 source yielded sha256 `714044a5…` (7 477 986 → 7 371 366 B,
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
