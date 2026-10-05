# Ordessa Decision

Optional read-only decision library. The original `pydantic-graph` executes
host-defined trusted graphs; the official Jev SDK answers finite questions.
Decision outputs are proposals. Agent/Profile ownership and actual effects remain
with the existing core and owners. No apply, resume, dispatcher or effect lease exists.

Base installation requires Python >=3.10 (verified on 3.12.14). Extras: `jev` for
SDK, `ordessa` for public core adapter, `dev` for tests. Importing contracts uses
only the standard library; public import never imports the optional SDK or core.

Reference graph assembly is in `flows/agent_assignment/build.py`, configured by
external versioned `task_gate_policy.json` and `selection_policy.json`. The caller
may substitute trusted Python graphs and registered proposal template handlers.
Default limit values are configurable; effective business bounds intersect run
limits. Trust is a host code review boundary, not a Python sandbox.

## Existing isolated environment

From this worktree:

```bash
.venv-decision/bin/python packages/backend/decision/examples/offline_assignment.py
.venv-decision/bin/python packages/backend/decision/examples/alternate_flow.py
.venv-decision/bin/python packages/backend/decision/checks/offline_acceptance.py
```

Offline fixtures are explicitly labelled controlled; they demonstrate protocol,
flow and read boundaries, not Chinese model quality or native unit readiness.
Acceptance uses the official SDK with fake HTTP transports, real graph runtime,
local POSIX files, real subprocess kills and a temporary core with fake owner.

## Read and effect handoff

Only `DecisionServices` read/candidate/composer/validator ports enter nodes; raw SDK
is held by the gateway. Owner validation binds both native input and decision
proposal digests. Consumers must recheck every MUST precondition using recognised
checker/version identities; `CheckBatch.require` fails on omitted, unknown or
changed versions. There is no decision-side apply operation.

File evidence requires a host-chosen local POSIX directory mode 0700 and read
capability. SDK errors and event summaries exclude raw bodies, task text and keys.
Async cancellation propagates; timeout is cooperative and cannot hard-kill
blocking or cancellation-suppressing trusted code. Host closes shared clients and
sinks. Evidence uncertainty carries a safe run ID for authorised read/query only.

Real Jev synthetic evaluation through the separately authorized OpenCode Zen free
route is PARTIAL; model label failures and the live capacity protocol failure remain recorded. Host settings bind
requested model and a finite response-model allowlist in the provider digest. The
evaluation profile and explicit opt-in runner live in evaluation/, with no default
live execution. Real Harness operation and real family effects are unverified. See
the spec status and per-scenario evidence ledger for tested scope.

The implementation and required evaluation reports are delivered; product readiness
remains PARTIAL. The spec completion-audit.md maps the original JD items and
requirements to scoped evidence. Existing family opt-out and unmet live labels are
reported exactly as the task contract requires, without advertising native effects.
