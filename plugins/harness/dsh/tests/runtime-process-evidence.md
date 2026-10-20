# Runtime process evidence — dsh package (controlled fake peer, ZERO real dsh start)

2026-10-07 · slice `plugins/harness/dsh/**` (DeepSeek Harness Provider
independent package, freeze `dsh-package-freeze-v1.md`). Baseline
`c47696b74b11863a9ee2fd1542033e72ce9b513b`. Authority scope: the dsh package
tree only; no harnesses.toml / five-lane files / Go bridge / JS bridge /
deploy templates / `test_independent_server_providers.py` were touched.

## Real dsh process: NOT_STARTED (0), by rule

**The real `dsh` binary was never executed by this package — 0 real-process
starts.** Rules 6/9 and freeze §4: real-model test calls require prior user
authorisation; this slice holds no such authorisation, no registered local
dsh installation, and no gate evidence. Every "process" in this package's
tests is a **controlled fake peer**: a generated Python script standing in
for `dsh --profile acp`, spawned through the REAL
`DshAcpChannelFactory` (real `LaunchSpec` isolation, real managed writer
fence, real reap/termination path). The fake performs no model call by
construction (it is a script), and the provider lifecycle tests never write
a `session/prompt` frame (zero-model boundary asserted per test).

Registered NOT_RUN until the gates open:

- real dsh `0.1.5-rc.1` process behaviour (initialize / `session/new` /
  `session/load` rejection / resume-no-replay against the real binary);
- production assembly inclusion — the fingerprint gate is NOT backfilled, so
  the dsh provider must not appear in any production assembly (freeze §3/§5);
- `harnesses.toml` registration round (static candidate only, untouched);
- deployment/dsh templates, settings re-verification, capability_declarations
  sync; SDK extra (`deepseek-harness-sdk==0.1.5rc1` stays an independent,
  absent track);
- P-level real-process termination evidence re-proof (the C-level logic is
  exercised against the controlled fake/stub handle).

## Pin facts recorded here (zero forgery)

- npm pin: `@deepseek-ai/dsh` **`0.1.5-rc.1`** —
  `tooling/npm/package-lock.json` resolved
  `https://registry.npmmirror.com/@deepseek-ai/dsh/-/dsh-0.1.5-rc.1.tgz`,
  integrity
  `sha512-rmNmzQCg3oIc1z8xH7izRSOuy1TNzq+/NILyfM+7e8DKOyV+yBtg47WEsqR2SiIe1ATec3L/rUa1YhIcfQ2XEg==`.
  npm latest `0.2.0-rc.2` deliberately NOT chased (zero in-repo ACP evidence).
- channel label: `dsh-acp/1`; argv plan `dsh_acp_argv(executable) ->
  (executable, "--profile", "acp")`; every client frame carries
  `jsonrpc: "2.0"`.
- descriptor digest: required, no default, never generated in-package; test
  fixtures (`sha256:` + `a`*64) are explicitly non-real; production digest
  comes from the deployment fingerprint gate.
- recovery: `session/load` rejected by dsh → `recover` permanently absent;
  `session/resume` is a client frame only, continuation belongs to
  `agent-box.dsh-continuation@1`.
- configuration: all four configuration methods absent (no pinned evidence
  port); ACP model adapter kind `dsh.model` assesses unsupported / refuses
  compile typed / verifies unknown.

## Controlled fake peer behaviour (what the fake asserts)

The generated peer answers the frozen ACP frame set over stdio JSON-RPC 2.0:
`initialize` (agentCapabilities.loadSession=false), `session/new` (with a
controlled 50 ms delay so receipt-loss deadlines are deterministic),
`session/prompt` (emits one `session/update` then terminal
`stopReason=end_turn|error`; never answers `SLOWME`),
`session/cancel|close|set_config_option`, `session/resume` (returns
`configOptions` with NO replay state — resume never replays history),
`session/load` → typed `-32601 "session/load is not supported"`, unknown
methods → typed `-32601`. Every opened channel is closed explicitly through
the factory in teardown; residual private-root process scans assert empty.

## Test accounting (final run, exit 0)

Full package command (exit 0, **231 passed, 0 skipped**):

```
PYTHONPATH=plugins/harness/dsh/src:plugins/harness/records/src \
<.venv-ordessa-py312 python> -m pytest -c plugins/harness/dsh/pyproject.toml \
plugins/harness/dsh/tests -q --tb=short
```

Per file (collected == passed, no skips):

| File | Tests | Level |
| --- | --- | --- |
| `tests/test_server_plugin.py` | 9 | C controlled owner-view wiring |
| `tests/test_provider.py` | 61 | C controlled owner ports, ACP start edges |
| `tests/test_prepared_client.py` | 49 | C one-shot ACP frames, controlled channels/peers |
| `tests/test_runtime_process.py` | 23 | C+ fake-process through the REAL factory/journal |
| `tests/test_termination_records.py` | 19 | C real UnitRecords + stub handle, real port logic |
| `tests/test_acp_model_configuration.py` | 30 | pure adapter, empty family tables |
| `tests/test_acp_model_distribution.py` | 1 | fresh wheel closure + isolated pip check |
| `tests/test_client.py` | 29 | new ACP frames / no-load / no-retry / receipt≠completion |
| `tests/test_configuration.py` | 10 | new configuration-absence + adapter absence |

Installability gate (freeze §5.1): the distribution test built all five
wheels (`environment-api`, `pacthold`, `harness-transport`, `harness-api`,
`dsh`) from their pyprojects (`pip wheel --no-index --no-build-isolation
--no-deps`), installed them into a fresh isolated venv and ran `pip check`
(exit 0). A standalone re-run of the same closure recorded:
`No broken requirements found.` (exit 0) and
`DshRuntimeProvider` constructs with descriptor `dsh / agent-runtime/2`.

Transport acceptance re-run (no breakage): `packages/backend/harness-transport/tests`
— 103 passed, exit 0; `plugins/harness/tests/test_managed_transport_fence.py`
— 31 passed, exit 0; `acceptance_install.py` local wheel closure — passed,
14 records all exit 0, temporary environments removed.

## First failures and fixes (serial run log)

1. First run exit 1: **11 failed, 220 passed**. Failures and fixes:
   - rc-version expectations (`0.1.5-rc.1`/`0.2.0-rc.2`): `parse_version`
     returns `None` for prerelease pins → honest `unknown` (range is empty);
     tests updated, implementation unchanged.
   - `TargetHandle("dsh","project",…)` compile: dsh pins NO scope claim in
     this tree — an out-of-instance scope cannot invent a target-conflict;
     it hits the honest absence refusal (`capability-unsupported`); tests
     updated, implementation unchanged.
   - `_payload` method name contained the substring `load`, tripping the
     no-load-constant assertion → renamed `_request_frame`.
   - ScriptedChannel lacked `notify` (the real transport adds
     `jsonrpc:"2.0"` + `params`) → test double extended.
   - Timeout-semantics mismatch in one scripted test (`ChannelClosed` vs
     `RequestTimeout`) → dedicated `TimeoutChannel` double.
   - regex `match="configuration"` did not cover `query_change` → matched the
     full typed-refusal prefix instead.
   - configuration-call arity in one test (3 args into a 1-arg method) →
     per-method call tuples.
   - initialize-stub bug in one test (stub replaced the recording method) →
     recording stub.
2. Second run exit 1: **1 failed, 230 passed** (ScriptedChannel `notify`
   missing) → double extended.
3. Final run exit 0: **231 passed, 0 skipped**.

## Unknown discipline observed

Unknown outcomes keep their holds (provider records `unknown`, never
downgrades a concurrently confirmed binding); no retry exists anywhere in the
client (a lost receipt keeps its original id and is recovered read-only);
receipt≠completion is enforced at the prompt fence; the controlled fake
processes are short-lived, reaped by identity in teardown, and leave no
side-effect processes (private-root scans assert empty). No user-facing
service was touched, no model call was made, no credentials were read.
