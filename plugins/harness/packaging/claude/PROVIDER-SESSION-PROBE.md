# Claude ACP per-session provider probe

This change pins `claude-agent-acp` 0.81.2 and retires the duplicate Go Claude
mode without changing the product's provider-switching contract. The former 0.77.0 release fingerprints only the
workspace and MCP servers when resuming a loaded Query. In 0.81.2, the
fingerprint also covers session-level SDK `options.env` and `options.settings`.

Run `npm ci` in this directory, then both `npm run test:session-provider` and
`npm run test:provider-routing`. The first test mocks Query creation and checks
the adapter's actual `getOrCreateSession` path: a route change invalidates A's
fingerprint, replaces only A, and resumes under the same session ID. The second
test launches the pinned adapter and its Claude child against three loopback
fake Anthropic APIs, with a temporary Claude config directory and fake token.
It sends A and B one turn each, resumes only A with route C, then sends another
turn to each. The observed user-turn requests are A=1, B=2, C=1; C's request
contains A's first turn, while B stays on its original route. Claude's separate
title-generation requests are excluded from user-turn counts. Neither test
contacts a real model or uses a real credential.

This is **not** an Ordessa Server/desktop end-to-end test. Retiring the Go Claude mode does not by itself make provider switching available in the product. Before the product
offers switching, Harness must pass session-scoped routing values at
`session/new` and `session/resume` through its own channel boundary and retain
the selected route per session. Do not use the adapter's `providers/set`: that
operation updates all loaded sessions. Never put provider credentials in
desktop-visible ACP frames or diagnostic logs.

Verification in this worktree: the two Node probes pass (2/2 lifecycle cases;
fake-endpoint turn counts A=1, B=2, C=1), the Claude runtime artifact builds
outside Git at digest `sha256:03324c056754cf7e7a0d117a5abdab02705ef38993d82847b9bb30b2f5d542c5`,
and `test_claude_production_template.py` passes 12/12 under Python 3.12.
