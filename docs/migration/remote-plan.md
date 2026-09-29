# Remote plan — reusing the agent-box repository identity

Status: **prepared, not executed.** No push, no rename, no remote mutation has
happened. Every action below needs explicit user authorisation.

## Identity decision (user-confirmed direction)

The monorepo keeps the identity of the original `agent-box` repository (`https://github.com/mmm-05610/agent-box.git`), **renamed to `https://github.com/mmm-05610/ordessa.git` on 2026-09-29** (GitHub redirects the old URL).
The GitHub repository may later be renamed `ordessa` (GitHub redirects refs
after a rename); this round only prepares.

## Measured facts (2026-09-25)

- Remote `main` = `6c14ea8db8130f1e219328835840b4159fe8c9e7`, identical to the
  local `agent-box` repo's `main` (checked out by the preserved
  `agent-box-studio-backend-core` worktree). New `main` here is its descendant:
  migration commit replaced the tree, history kept (no orphan, no force).
- The desktop repo has its own origin (`mmm-05610/agent-box-desktop-next`,
  local `main` ahead of origin by 497 commits) and an upstream
  (`NousResearch/hermes-agent`); `agent-box` additionally has a second remote
  `l1` (ssh). Those remotes are untouched; how to treat them at publish time
  is an open question for the user.
- The ACP bridge is derived from `beyond5959/acp-adapter` (its origin);
  attribution and module path preserved.

## Proposed publish contents (for user approval, when requested)

| Target ref on origin | Source | Notes |
| --- | --- | --- |
| `main` | local `main` (candidate SHA reported at switch time) | descendant of `6c14ea8d`; old files removed in the migration commit, history intact |
| `archive/*`, `reference/*` | the archive refs imported during migration | **opt-in**: pushing ~400 MB of history refs is a separate decision; can publish main only |

Rules that will apply: re-check `ls-remote` immediately before any push and
re-integrate if the remote moved; no `--force`, no `--mirror`, no deletion of
existing remote refs; old remote `main` needs no preservation ref (it remains
an ancestor of the new `main`). Publishing desktop/studio/control archives to
this remote is possible later via their archive refs if wanted.

## Rename to `ordessa` — executed 2026-09-29

The GitHub repository was renamed `agent-box` → `ordessa` (redirects kept). Local
`origin` updated with `git remote set-url` to
`https://github.com/mmm-05610/ordessa.git`; `ls-remote` verified at the new URL.
The CI added the same day (`.github/workflows/ci.yml`, PR #68) now provides the
`backend`/`frontend` contexts the `main` ruleset requires, so routine changes go
through a PR merge instead of a temporary ruleset relaxation.
