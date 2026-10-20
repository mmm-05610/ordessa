# Reference index — history, archives and how to reach them

The Ordessa monorepo keeps **two kinds of history references**:

1. `refs/archive/<repo-key>/…` — the complete locally-available ref set of every
   source repository, imported verbatim (heads, tags, worktree `HEAD`s,
   checkpoints, remote-only refs). Frozen; nothing here is merged into `main`.
2. `refs/reference/*` — three curated snapshots for convenient checkout.

Sources were measured 2026-09-25; the full inventory, dirty-tree snapshots and
restore evidence live outside this repo in
`/home/maoqh/projects/ordessa-preservation/20260925/` (see `REPORT.md`,
`refs-map.tsv`, `bundles/`, `workspace-backups/`, `checkpoints/`).

## Curated reference refs

| Ref | Commit | What it is | Why kept |
| --- | --- | --- | --- |
| `reference/hermes-desktop` | `e08fa034f247` | `agent-box-desktop-next` `main` — the mature state of the desktop lineage imported from upstream `NousResearch/hermes-agent` (first commit `7a0ac573b7 "Import the tree of NousResearch/hermes-agent@cfdbbb6"`, client-only reduction `fb9b4fe998`, FILE_MAP baseline `382915af7b31` is an ancestor) | Reuse source: dependency-direction test suites (`src/api/import-boundary.test.ts`, product-authority boundaries), `apps/shared` JsonRpcGatewayClient SDK + host/plugin context injection, 439 UI components (`components/ui` 297), 1025 test files. Do **not** import its global state, hermes-specific connections or first-run installer chain. Distinct from the backend `hermes` harness driver family. |
| `reference/backend-legacy` | `92a2d2ba66fc` | `agent-box` `integration/linux-native-0` tip — concluded Linux-native backend integration line (LNX-001/002/003 + BE-LOOP-001 amendments) | Latest pre-hd002 backend integration state; source line of the retired trial servers' plugin trees. |
| `reference/studio-legacy` | `8dce2c022925` | `agent-box-studio` `studio-shell` main | Historical Studio vertical; its uncommitted architecture docs (REMOTE_CONNECTION_*) are snapshotted in the preservation batch. |

## Archive refs

| repo-key | Source repository | Imported | Notes |
| --- | --- | --- | --- |
| `agent-box` | `/home/maoqh/projects/agent-box` (origin `github.com/mmm-05610/agent-box`) | 66 heads + 66 tags + 62 worktree HEADs + extra tip `013abb800470` | New `main` descends from this repo's `main` (`6c14ea8d` = remote main). Baseline trio marker: `heads/main-cp-001` = `a0b343e0` (= `work/hd002-bc-native`). Second remote `l1` exists (ssh) — publish-stage question. |
| `agent-box-desktop-next` | `/home/maoqh/projects/agent-box-desktop-next` (origin `mmm-05610/agent-box-desktop-next`, upstream `NousResearch/hermes-agent`) | 80 heads (all), 58/61 tags, remote-only refs | **Shallow clone**: boundary `cfdbbb6e` (hermes import point); parent `425b0017` missing locally → tags `v2026.9.11/14/21` and `upstream/*` not locally recoverable (remote unshallow needed; user decision). `heads/main-cp-001` = `450944bd` (= `work/hd002-fc-functional`, diverged from `main`, not a descendant). |
| `agent-box-studio` | `/home/maoqh/projects/agent-box-studio` | 5 heads + 183 tags + worktree HEADs | Full history. |
| `control` | former `ordessa/control` scheduling+decision repo | `heads/main` @ `e2ab7409` + `checkpoint/2026-09-25` @ `4fc80571` | The checkpoint captures all 2184 uncommitted files (missions/HD-002, product plans, reports). Still-valid decisions were distilled into this repo's docs; the control repo itself is retired as an active authority. |
| `acp-adapter` | `/home/maoqh/ordessa-builds/acp-adapter` (origin `github.com/beyond5959/acp-adapter`) | heads (incl. `work/round-h` = `41d9d94` = `main-cp-001`, upstream `master` = `491151b1`) + 11 tags | Upstream-derived Go ACP bridge; module path kept. Source of `plugins/harness/pi/vendor/acp-adapter`. |
| `harness-profile` | former `ordessa/repos/harness-profile` | `heads/work/initial-plugin` @ `1191a41b` | Independent plugin, clean, protected — continues outside `main`. |
| `harness-provider` | former `ordessa/repos/harness-provider` | `heads/work/initial-plugin` @ `e925f231` + tag `READY_FOR_REVIEW` | Independent plugin, clean, protected. |
| `harness-workboard` | former `ordessa/repos/harness-workboard` | `heads/work/initial-plugin` @ `91683313` | Independent plugin, clean, protected. |

## How to restore anything

**Important clone semantics.** A plain `git clone` of this repository carries
**only `main` + tags** — the `refs/archive/*` and `refs/reference/*` refs are
local to the candidate repository and are NOT auto-cloned (a local-path clone
hardlinks objects, but a `--no-local` or network clone does not even carry the
archive objects). The restore loop below is the supported path; the
preservation bundles are the off-machine durable source.

**Standard restore loop (verified 2026-09-25 from a plain clone):**

```sh
git clone <candidate-or-post-switch-root> work            # main + tags only
cd work
git fetch <candidate-or-post-switch-root> \
    '+refs/archive/*:refs/archive/*' \
    '+refs/reference/*:refs/reference/*'                  # +603 refs → all
git cat-file -e a0b343e0^{commit}                          # any archive SHA reachable
```

- **Any branch of any source repo**: `git checkout refs/archive/<repo-key>/heads/<branch>`,
  or clone the matching bundle from the preservation batch:
  `git clone /home/maoqh/projects/ordessa-preservation/20260925/bundles/<repo-key>.bundle <dir>`
- **Uncommitted work**: `workspace-backups/<label>/files.tar.gz` (+ `MANIFEST.tsv`
  with per-file sha256, `changes.patch`, `status.txt`, `META.txt`).
- **Control's full dirty state**: `git clone
  .../checkpoints/control/control-checkpoint.bundle`, checkout
  `checkpoint/2026-09-25` (`4fc80571`). Restore-loop evidence 2026-09-25: the
  checkpoint restore and the `control__main` tar snapshot agree byte-for-byte
  on README.md, missions/HD-002/BASELINE.md,
  product/ordessa-monorepo-baseline-plan.md (two independent preservation
  artifacts cross-verified); a backend dirty snapshot (`agent-box__hd002-bc`)
  restored byte-identical per its MANIFEST sha256.

## Known history gaps (registered, not hidden)

1. Desktop repo tags `v2026.9.11`, `v2026.9.14`, `v2026.9.21` and `upstream/*` refs cross the shallow boundary and are **not** recoverable locally; neither the 2026-09-20 old bundles nor the 2026-09-25 batch contain `425b0017`. Fixing requires a remote unshallow from origin/upstream — pending user approval.
2. Old trial-server plugin trees (`agent-box-env-provider`, `agent-box-runtime-round1`) live on as archive refs; the servers themselves (ports 18790/18810) are no longer running as of 2026-09-25.
3. `harness-profile`'s `.git` is 57 MB (large objects); a `git gc`/repack review is advisable before any future push — user decision.

- [Engineering platform positioning](engineering-platform-positioning.md) — 定位与目标陈述，含已实现/未验证边界与 Spec Kit (MIT) 复用声明。
