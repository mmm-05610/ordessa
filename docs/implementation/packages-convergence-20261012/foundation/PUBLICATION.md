# Safe development-checkpoint publication plan

Status: reviewed procedure only. This document records the intended isolated
publication mechanics; it does not perform a Git operation or authorize any
scope beyond the exact manifest below.

## Confirmed remote facts and history risk

At the read-only remote-ref observation recorded 2026-10-12 18:17 UTC,
`refs/heads/main` was `b4bf7cd90951d0fa9bcf3a3de2e66b7db6a62aa0`, and the proposed
`refs/heads/codex/packages-convergence-publish-20261012` did not exist. The
currently advertised `refs/heads/codex/software-engineering-direction-20261007`
contains three SQLite restore-snapshot blobs. Their paths and object ids are:

| Repository path | Blob object id |
| --- | --- |
| `plugins/tmp-backups/skill-restore-20261007T075823-329854/state/agentbox.sqlite` | `10eb06feef4f429c3115e2d3525f05596759e085` |
| `plugins/tmp-backups/skill-restore-20261007T075856-389637/state/agentbox.sqlite` | `7f39f4b0152c8815078695880b59f1a362aee344` |
| `plugins/tmp-backups/skill-restore-20261007T075920-792003/state/agentbox.sqlite` | `9ccf4fe1445d9b320efe9dadbc69b6bd1f5b9471` |

All three are reachable from that currently advertised branch and absent from
the observed `main` history. The available evidence suggests synthetic restore
fixtures, but the paired manifest digests do not match these database blobs;
provenance and contents therefore remain unverified. No database record values
were read. These binaries violate the repository's no-binaries rule and remain
in the existing remote branch history. This plan does not delete, rewrite,
force-update, or otherwise change that branch or any historical ref.

The positive reachability finding is limited to the currently advertised refs
and locally available objects at the observation time. It does not establish
whether deleted, hidden, or otherwise unavailable refs contain other objects.
The new checkpoint must add no reachability for any of the three blobs.

## Isolated new-ref procedure

Only Foundation Sol performs these Git operations after rechecking the remote
facts and the frozen file hashes. The current work branch/index and other
review trees stay untouched.

1. Confirm `main` still resolves to the exact parent above and the new target ref
   is still absent. Stop if either fact changed; refresh the approved plan and
   manifest before proceeding.
2. Allocate a temporary `GIT_INDEX_FILE` outside the worktree. Initialize it
   with `git read-tree b4bf7cd90951d0fa9bcf3a3de2e66b7db6a62aa0`.
3. Stage only the 56 paths listed below plus this `PUBLICATION.md` path into
   that temporary index. The separate AGENTS authorization appended for this
   new branch changes one file's bytes, so the earlier local manifest hash for
   `AGENTS.md` is superseded. Re-freeze and verify SHA-256 and byte count for all
   57 paths before staging. Do not use `git add -A`, do not copy the whole worktree, and
   do not include root locks, other-owner source, local evidence receipts,
   credentials, personal host metadata, raw logs, or binaries.
4. Write the tree from the temporary index and create a commit whose only parent
   is the exact `main` OID above. Before pushing, verify that every changed path
   is within the 57-path allowlist, the old worktree checkpoint commits
   `b99391d66d8b3a91434bcb419b554bfaad02e02a` and
   `751707e1f1558d6b868a8761aed7c5a8dfbd4ef2` are not ancestors, and none of
   the three SQLite OIDs is reachable from the new commit. Paths already
   byte-identical to `main` need not appear in the diff.
5. Push only that new commit to
   `refs/heads/codex/packages-convergence-publish-20261012`, without force.
   If the ref appeared or the remote rejects a non-fast-forward update, stop;
   do not overwrite it or redirect to another branch.

This plan creates a development checkpoint, not a main merge or release. It
preserves the existing remote branch that already contains the SQLite blobs.
Future owner slices may be appended only through a separately reviewed exact
path manifest after their owners provide contracts and qualification evidence;
there is no directory-wide allowlist.

## Exact first-slice allowlist

The reviewed Foundation path allowlist contains 56 paths. This plan is the only
additional path, for 57 exact paths total. The exact content manifest must be
recomputed after the new AGENTS authorization is appended; do not reuse the
earlier local hash receipt for that file:

- `AGENTS.md`
- `docs/implementation/packages-convergence-20261012/foundation/README.md`
- `docs/standards/engineering-standard.md`
- `docs/implementation/packages-convergence-20261012/foundation/consumer-batch-81/README.md`
- `tooling/checks/package-boundaries.json`
- `packages/infrastructure/README.md`
- `packages/infrastructure/pyproject.toml`
- `packages/infrastructure/src/ordessa_infrastructure/__init__.py`
- `packages/infrastructure/src/ordessa_infrastructure/database/README.md`
- `packages/infrastructure/src/ordessa_infrastructure/database/__init__.py`
- `packages/infrastructure/src/ordessa_infrastructure/database/migrations.py`
- `packages/infrastructure/src/ordessa_infrastructure/database/options.py`
- `packages/infrastructure/src/ordessa_infrastructure/database/records.py`
- `packages/infrastructure/src/ordessa_infrastructure/database/sqlite.py`
- `packages/infrastructure/src/ordessa_infrastructure/discovery.py`
- `packages/infrastructure/src/ordessa_infrastructure/encoding/README.md`
- `packages/infrastructure/src/ordessa_infrastructure/encoding/__init__.py`
- `packages/infrastructure/src/ordessa_infrastructure/encoding/canonical_json.mjs`
- `packages/infrastructure/src/ordessa_infrastructure/encoding/canonical_json.py`
- `packages/infrastructure/src/ordessa_infrastructure/encoding/digests.py`
- `packages/infrastructure/src/ordessa_infrastructure/filesystem/README.md`
- `packages/infrastructure/src/ordessa_infrastructure/filesystem/__init__.py`
- `packages/infrastructure/src/ordessa_infrastructure/filesystem/blobs.py`
- `packages/infrastructure/src/ordessa_infrastructure/filesystem/directories.py`
- `packages/infrastructure/src/ordessa_infrastructure/filesystem/errors.py`
- `packages/infrastructure/src/ordessa_infrastructure/filesystem/files.py`
- `packages/infrastructure/src/ordessa_infrastructure/filesystem/publication.py`
- `packages/infrastructure/src/ordessa_infrastructure/identifiers.py`
- `packages/infrastructure/src/ordessa_infrastructure/process/README.md`
- `packages/infrastructure/src/ordessa_infrastructure/process/__init__.py`
- `packages/infrastructure/src/ordessa_infrastructure/process/framing.py`
- `packages/infrastructure/src/ordessa_infrastructure/process/spawn.py`
- `packages/infrastructure/src/ordessa_infrastructure/security/__init__.py`
- `packages/infrastructure/src/ordessa_infrastructure/security/secrets.py`
- `packages/infrastructure/src/ordessa_infrastructure/security/windows_dpapi.py`
- `packages/infrastructure/tests/database/test_migrations.py`
- `packages/infrastructure/tests/database/test_records_contract.py`
- `packages/infrastructure/tests/database/test_sqlite_options.py`
- `packages/infrastructure/tests/encoding/test_canonical.py`
- `packages/infrastructure/tests/filesystem/test_blobs.py`
- `packages/infrastructure/tests/filesystem/test_directories_files.py`
- `packages/infrastructure/tests/filesystem/test_publication.py`
- `packages/infrastructure/tests/process/test_framing.py`
- `packages/infrastructure/tests/process/test_spawn.py`
- `packages/infrastructure/tests/security/test_secrets.py`
- `packages/infrastructure/tests/security/test_windows_dpapi.py`
- `packages/infrastructure/tests/test_discovery.py`
- `packages/infrastructure/tests/test_identifiers.py`
- `packages/infrastructure/tests/test_import_boundaries.py`
- `packages/infrastructure/tests/test_kernel_retirement_boundaries.py`
- `packages/infrastructure/tests/test_request_key.py`
- `tooling/checks/dependency_boundaries.py`
- `tooling/checks/dependency-boundaries.mjs`
- `tooling/tests/dependency-boundaries.test.mjs`
- `tests/architecture/test_dependency_boundaries.py`
- `docs/implementation/packages-convergence-20261012/foundation/consumer-batch-81/CROSS-OWNER-REQUESTS.md`
- `docs/implementation/packages-convergence-20261012/foundation/PUBLICATION.md`

## What this checkpoint establishes

The slice publishes the approved Engineering Standard, package-boundary rules,
Foundation's technical facilities, and the sanitized 81-file consumer
checkpoint summary. It records a bounded development-state handoff; it does not
complete all C1 retirement, product wiring, product dependency closure, or
whole-product acceptance. The 81/141 Harness import slice remains distinct
from full integration qualification. Memory's separately reported latest
132-passed/1-skipped scope is not included in this manifest and is not evidence
that its source is present in this checkpoint.

Current bounded evidence: Infrastructure source and installed-wheel scopes
reported 206 passed and 0 skipped each; these scopes overlap and are not added
together. Boundary fixtures reported 33 Python passes and 24 JavaScript passes.
The latest Memory full-package source and installed runs in the current worktree
each reported 132 passed and 1 historical skip; the
[sanitized consumer checkpoint](consumer-batch-81/README.md) records the scope.
Memory source is not part of this first-slice manifest, so these results do not
mean that Memory code is published or that another branch's contents are
complete. The full repository boundary gate remains red, and product dependency
closure and isolated product installation remain unqualified. No
product-completion claim follows from this slice.
