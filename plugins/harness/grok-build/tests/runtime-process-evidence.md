# Runtime process evidence — grok-build package (controlled fake peer, ZERO real grok start)

2026-10-07 · slice `plugins/harness/grok-build/**` (xAI Grok Build Provider
independent package, spec: `docs/implementation/agent-tools/grok-build-registration-draft.md`
§6 + dsh freeze precedent `dsh-package-freeze-v1.md`). Baseline
`c47696b74b11863a9ee2fd1542033e72ce9b513b`. Authority scope: the grok-build
package tree only; no harnesses.toml / launch-descriptors / capability
declarations / profile_extensions / five-lane files / Go bridge / JS bridge /
deploy templates / `test_independent_server_providers.py` were touched (the
grok-build provider is deliberately NOT added to that test's triples —
integration is a later registration action).

## Real grok process: NOT_STARTED (0), by rule

**The real `grok` binary was never executed by this package — 0 real-process
starts.** Rules 6/9: real-model test calls require prior user authorisation;
this slice holds no such authorisation, no registered local grok
installation, and no gate evidence. Every "process" in this package's tests
is a **controlled fake peer**: a generated Python script standing in for
`grok agent stdio`, spawned through the REAL
`GrokBuildAcpChannelFactory` (real `LaunchSpec` isolation, real managed
writer fence, real reap/termination path). The fake performs no model call by
construction (it is a script), and the provider lifecycle tests never write
a `session/prompt` frame (zero-model boundary asserted per test). No `.env`
was read, no credential (`grok` login / `XAI_API_KEY`) was touched, no user
service or user data was operated.

Registered NOT_RUN until the gates open:

- real Grok Build `1.0.46` process behaviour (initialize / `session/new` /
  prompt terminal vocabulary / `authenticate` extension semantics / absent
  method rejections against the real binary); `--version` probe unrun;
- `authenticate` extension实测 (methodId semantics, `_meta.headless`,
  credential flows) — the adapter gate is verified typed-refused at C level;
  the extension itself is NOT implemented;
- production assembly inclusion — the fingerprint gate is NOT backfilled, so
  the grok-build provider must not appear in any production assembly
  (draft §6/§7);
- `harnesses.toml` / launch-descriptors / capability_declarations /
  profile_extensions registration round (static draft text only, untouched);
- deployment templates, settings re-verification, packaging script route
  (no npm/PyPI package exists; install-script/source route uncompiled);
- P-level real-process termination evidence re-proof (the C-level logic is
  exercised against the controlled fake/stub handle).

## Pin facts recorded here (zero forgery)

- CLI pin: Grok Build **`1.0.46`** — x.ai/changelog/build entry v1.0.46
  dated 2026-09-30, verified 2026-10-07 (three-source check per registration
  draft §1; Apache-2.0 double-sourced, copyright "SpaceXAI" quoted as-is).
  No lock file exists (no npm/PyPI package); the pin is a CLI/channel pin,
  never a model-configuration fact.
- channel label: `grok-build-acp/1`; argv plan `grok_acp_argv(executable) ->
  (executable, "agent", "stdio")`; every client frame carries
  `jsonrpc: "2.0"`; isolation root env `GROK_HOME`.
- descriptor digest: required, no default, never generated in-package; test
  fixtures (`sha256:` + `a`*64) are explicitly non-real; production digest
  comes from the deployment fingerprint gate.
- recovery: ACP reopen (`session/load`|`session/resume`) has NO documentary
  evidence → `recover` permanently typed-refused; `describe_definition`
  reports `recovery: "unsupported"`; continuation belongs to
  `agent-box.grok-continuation@1` (target `grok-build-continuation`).
- absent registrations: `kill_task` / `get_task_output` / `session/load` /
  `session/resume` — no client method, no constant, describe `absentMethods`.
- authenticate extension: client-initiated xAI extension
  (`methodId=xai.api_key|cached_token`, `_meta.headless`) — typed-refused
  (`GROKBUILD_AUTHENTICATION_REFUSED`) before any write; the standard ACP
  server→client authenticate chain is never inferred.
- configuration: all four configuration methods absent (no pinned evidence
  port); ACP model adapter kind `grok-build.model` assesses unsupported /
  refuses compile typed / verifies unknown.
- REFUSED codes: `GROKBUILD_PROVIDER_REFUSED` (provider),
  `GROKBUILD_CHANNEL_REFUSED`, `GROKBUILD_LEASE_REFUSED`,
  `GROKBUILD_PROJECTION_REFUSED`, `GROKBUILD_TERMINATION_REFUSED`,
  `GROKBUILD_AUTHENTICATION_REFUSED`.

## Controlled fake peer behaviour (what the fake asserts)

The generated peer answers the frozen ACP frame set over stdio JSON-RPC 2.0:
`initialize` (agentCapabilities `{}`), `session/new` (with a controlled 50 ms
delay so receipt-loss deadlines are deterministic), `session/prompt` (emits
one `session/update` then terminal `stopReason=end_turn|error`; never answers
`SLOWME`), `session/cancel`; every other method (`kill_task`,
`get_task_output`, `session/load`, `session/resume`, unknowns) → typed
`-32601 "Unknown method"`. No resume/no load/no reopen fallback exists client
side. Every opened channel is closed explicitly through the factory in
teardown; residual private-root process scans assert empty.

## Test accounting (final run, exit 0)

Full package command (exit 0, **233 passed, 0 skipped**):

```
PYTHONPATH=plugins/harness/grok-build/src:plugins/harness/records/src \
<.venv-ordessa-py312 python> -m pytest -c plugins/harness/grok-build/pyproject.toml \
plugins/harness/grok-build/tests -q --tb=short
```

Per file (collected == passed, no skips):

| File | Tests | Level |
| --- | --- | --- |
| `tests/test_server_plugin.py` | 9 | C controlled owner-view wiring |
| `tests/test_provider.py` | 61 | C controlled owner ports, ACP start edges |
| `tests/test_prepared_client.py` | 46 | C one-shot ACP frames, controlled channels/peers |
| `tests/test_runtime_process.py` | 23 | C+ fake-process through the REAL factory/journal |
| `tests/test_termination_records.py` | 19 | C real UnitRecords + stub handle, real port logic |
| `tests/test_acp_model_configuration.py` | 29 | pure adapter, empty family tables |
| `tests/test_acp_model_distribution.py` | 1 | fresh wheel closure + isolated pip check |
| `tests/test_client.py` | 33 | new ACP frames / authenticate gate / absent-method registration / no-retry / receipt≠completion |
| `tests/test_configuration.py` | 12 | new configuration absence + authenticate-extension absence |

Installability gate: the distribution test built all five wheels
(`environment-api`, `pacthold`, `harness-transport`, `harness-api`,
`grok-build`) from their pyprojects (`pip wheel --no-index
--no-build-isolation --no-deps`), installed them into a fresh isolated venv
and ran `pip check` (exit 0). A standalone venv re-run recorded:
`No broken requirements found.` (exit 0) and
`GrokBuildRuntimeProvider` constructs with descriptor
`grok-build / agent-runtime/2` (the isolated program also asserts absence of
`ordessa_harness`/`ordessa_server`/`server_plugin_api`/sibling provider
imports and the four typed-refused surfaces).

Transport acceptance re-run (no breakage): `packages/backend/harness-transport/tests`
— 103 passed, exit 0; `plugins/harness/tests/test_managed_transport_fence.py`
— 31 passed, exit 0; `acceptance_install.py` local wheel closure — passed,
14 records all exit 0, temporary environments removed, evidence JSON kept
outside the tree.

## First failures and fixes (serial run log)

1. First run exit 1: **1 failed, 232 passed**. Failure:
   `test_reply_request_error_round_trip` — `AttributeError: 'ScriptedChannel'
   object has no attribute 'reply_error'` (the controlled double lacked the
   transport's `reply_error` surface, same double-extension class dsh
   logged for `notify`). Fix: extended the test double with
   `reply_error(request_id, *, code, message, data=None)` recording the
   error payload; added an assertion pinning the recorded error reply shape.
   Implementation unchanged.
2. Second run exit 0: **233 passed, 0 skipped**. Per-file re-runs all
   collected == passed (table above); no skips anywhere.

## Unknown discipline observed

Unknown outcomes keep their holds (provider records `unknown`, never
downgrades a concurrently confirmed binding); no retry exists anywhere in
the client (a lost receipt keeps its original id and is recovered read-only);
receipt≠completion is enforced at the prompt fence; the authenticate
extension stays gated typed-refused with zero writes; absent methods
(kill_task/get_task_output/session reopen) surface only as typed unknowns
with no fallback; the controlled fake processes are short-lived, reaped by
identity in teardown, and leave no side-effect processes (private-root scans
assert empty). No user-facing service was touched, no model call was made,
no credentials were read, no real grok process was started.
