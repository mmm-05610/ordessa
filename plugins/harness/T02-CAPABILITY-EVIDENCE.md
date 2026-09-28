# T02 — three-brand capability evidence ledger

Snapshot: 2026-09-28, this C0 worktree. This is an implementation plan and a
source inventory, not G22 acceptance. `docs/design/harness-v2/verification.md`
defines L1 (compiler/fixture), L2 (fixed native adapter and controlled native
endpoint), L3 (Ordessa Server/channel/submit path and controlled endpoint), and
L4 (external model, outside this authorization). The six required cells are
Pi/Codex/Claude × provider+model/Skills. A package name, official feature, or
template file alone does not prove the currently shipped adapter can apply it.

## Fixed identities and runnable seams

| Brand | Repository pin and native path | Actual production adapter entry | Present evidence and limit |
| --- | --- | --- | --- |
| Pi | `packaging/pi/package-lock.json`: `@automatalabs/pi-acp` 0.5.0, bundled `@earendil-works/pi-coding-agent` 0.84.2, ACP SDK override 1.3.0; `src/ordessa_harness/pi/native.py`: `models.json` | `src/ordessa_harness/pi/production.py` launches `/usr/bin/node` with the pinned artifact entry; isolated `.pi/agent` config and session subtree. The separate Go bridge in `adapters/acp-adapter` uses Pi RPC and `--pi-bin`; `packaging/acp-adapter/BUILD-RECORD.md` records a *different* installed Pi 0.86.1 bundle and hash. Do not merge these pins into one evidence claim. | Production template and Go Pi fake RPC/integration tests exist. They do not establish six-cell product control behavior for the npm production path. |
| Codex | `packaging/codex/package-lock.json`: `@agentclientprotocol/codex-acp` 1.1.14, `@openai/codex` 0.147.0, ACP SDK override 1.3.0; `src/ordessa_harness/codex/native.py`: `config.toml` | `src/ordessa_harness/codex/production.py` launches `/usr/bin/node` with pinned artifact entry. Separate Go bridge uses `codex app-server` and has fake app-server fixtures; its results cannot be attributed to the npm adapter. | Production template, vendored adapter protocol test, and Go app-server tests cover portions of startup/protocol. No complete six-cell L3 evidence. |
| Claude Code | `packaging/claude/package-lock.json`: `@agentclientprotocol/claude-agent-acp` 0.81.2, `@anthropic-ai/claude-agent-sdk` 0.3.280, ACP SDK 1.5.0; `src/ordessa_harness/claude/native.py`: `settings.json` | `src/ordessa_harness/claude/production.py` launches `/usr/bin/node` with pinned artifact entry and isolated `CLAUDE_CONFIG_DIR`. Go Claude mode was retired; do not revive or claim its historical tests. | `packaging/claude/PROVIDER-SESSION-PROBE.md` documents fixed-adapter and controlled endpoint routing for A/B/C sessions. It explicitly excludes Ordessa Server/desktop L3. |

The deployment templates provide artifact target, configuration projection and
environment, but are not proof that a changed file reaches an existing native
session or that reset restores a verified baseline. `packaging/*/package-lock.json`
pins package contents; a built artifact digest and the chosen production
deployment must also be captured in each L2/L3 run.

## Six cells: current grade, gap, required controlled experiment

| Cell | Current grade | Scope, application, reset and resume evidence still needed | L2 then L3 experiment |
| --- | --- | --- | --- |
| Pi provider+model | L1 template; alternate Go Pi RPC tests are separate evidence | Verify pinned 0.84.2 npm adapter consumes `models.json` and selects the requested model per session; determine whether change needs reload/restart, explicit reset of prior provider/model, and native session identity after resume. `0.86.1` Go bridge behavior cannot fill this cell. | L2: two sessions A/B on distinct controlled model endpoints; change A, observe A's next native request and B unchanged; reset A and resume same native session. L3: repeat through Server ACP channel and submit gate, with frame correlation and generation assertions. |
| Pi Skills | L1 path/CLI projection only | Verify the fixed native loader actually discovers and uses approved Skill content, per-session versus shared home scope, unload/reset behavior, and same-session resume. File presence or `--skill-dir` alone is insufficient. | L2: fixed loader reports a unique Skill marker for A, not B; remove/reset A and verify absence on a subsequent turn and after resume. L3: repeat via Server and assert failed/unknown application does not bind Profile or advertise the Skill. |
| Codex provider+model | L1 template and separate Go app-server behavior | Verify pinned `codex-acp` accepts the intended `config.toml` provider/model operation through its ACP path, session isolation, old-value reset, and exact `thread/resume` identity after restart. Official Codex config keys alone are not adapter capability. | L2: fixed npm adapter plus controlled Responses endpoint, two thread IDs, A switch/reset/resume and B unchanged. L3: same route through Ordessa channel/submit and execution association. |
| Codex Skills | L1 config/content candidates only | Verify pinned native Codex loader discovers approved Skill, its home/project scope, removal/reset, and resumed-thread behavior. Adapter protocol tests do not demonstrate native Skill loading. | L2: native loader discovery and turn evidence for A, absence for B, remove/reset and resume. L3: Server path, authorization and configuration confirmation with distinct frame IDs. |
| Claude provider+model | L2 partial: `packaging/claude/PROVIDER-SESSION-PROBE.md` | Existing controlled probe covers session-scoped env/settings route change and B isolation; still prove product control entry, credentials confined to backend, explicit baseline reset, native session identity and generation across restart. Never use global `providers/set`. | Extend fixed 0.81.2 probe with reset and restart-resume; L3 route A/B changes through Ordessa ACP channel and submit, verify endpoint turns and identity. |
| Claude Skills | L1 materialization candidate only | Verify fixed Claude native loader discovers `.claude/skills` content under `CLAUDE_CONFIG_DIR`/workspace scope; distinguish loaded instruction from an already remembered turn. Prove removal/reset and same native session resume. | L2: fixed adapter plus controlled endpoint, loader/discovery evidence and unique marker for A only, reset and resume. L3: same via Server with authorization, frame and execution correlation. |

Every L2/L3 run should capture source SHA, lock and artifact digest, controlled
endpoint counts, native session IDs before/after, generation, A/B isolation,
explicit reset baseline, and a negative: unsupported or missing adapter must
refuse before side effects. A failed stop or uncertain resume stays `unknown`;
`session/new` must never masquerade as resume. No L4 call is planned.

## Other brands: preserve the existing startup baseline

`packaging/` and `src/ordessa_harness/*/production.py` retain OpenCode,
Hermes, dsh, Kilo and Qwen packaging/deployment paths; `tests/test_*production_template.py`
contain baseline template checks. The current `entrypoints.py` directly lists
OpenCode and Hermes; other brand registration must be checked in product
composition. During integration, compare exact existing startup test IDs and
results against the pre-change baseline, then run controlled startup for each
available artifact. This inventory does not grant new configuration capability
to any of them, nor does a template test prove live startup. Missing artifacts
remain an explicit test gap rather than a simulated green result.

## Checks in this worktree

* Lock/source inspection used `python3` JSON parsing and `rg`; pins above come
  from committed lockfiles and paths named above.
* `python3 -m pytest -q plugins/harness/tests/test_pi_production_template.py plugins/harness/tests/test_codex_production_template.py plugins/harness/tests/test_claude_production_template.py`
  exited **1** immediately: `/usr/bin/python3: No module named pytest`.
* C0 then installed the repository's pinned Python lock into its own `.venv` and reran those three template files with `PYTHONPATH=plugins/harness/src .venv/bin/python -m pytest -q ...`: **39 passed, exit 0**. This proves template assertions only; it does not promote any of the six cells to L2/L3.
* The three packaging roots have no `node_modules` in this worktree. Claude's
  `npm run test:session-provider` and `test:provider-routing` therefore were
  not run here. No agent, model, service, or user configuration was touched.

**Status:** all six cells remain below full L3 acceptance; five have no L2
proof for the fixed production adapter, and Claude provider+model has only
partial L2. Application/reset/resume, isolation and product integration remain
unknown wherever the experiments above have not been run.
