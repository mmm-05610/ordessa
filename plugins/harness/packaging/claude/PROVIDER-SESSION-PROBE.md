# Claude ACP per-session provider probe

This branch evaluates `claude-agent-acp` 0.81.2 without changing the product's
provider-switching contract. The pinned 0.77.0 release fingerprints only the
workspace and MCP servers when resuming a loaded Query. In 0.81.2, the
fingerprint also covers session-level SDK `options.env` and `options.settings`.

Run `npm ci` in this directory, then `npm run test:session-provider`. The
controlled test uses no Claude process, credentials, network endpoint, or model
call. It checks that a route change invalidates the target session's fingerprint,
that the adapter's actual `getOrCreateSession` path tears down and recreates only
that session, and that the replacement is resumed under the same session ID.

This is **not** an end-to-end route or transcript-continuity test. Before the
product offers switching, Harness still needs to pass session-scoped routing
values at `session/new` and `session/resume`, verify the effective Claude child
environment with controlled endpoints, and prove that A's native transcript
continues while concurrent B stays on its own route. Do not use the adapter's
`providers/set` for this: that operation updates all loaded sessions. Never put
provider credentials in desktop-visible ACP frames or diagnostic logs.
