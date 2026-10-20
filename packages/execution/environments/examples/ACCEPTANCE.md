# `envctl` acceptance standard (v1)

Reference acceptance for the standalone `envctl` driver of `ordessa_environments`.
It is a **reference consumer** check, not a product-release gate. Every command
below runs a real subprocess, a real SQLite registry and real local files; there
are no mocks, no service starts, no model calls and no network calls.

## 0. Fixed environment

Run every check from the fix worktree with the runbook interpreter:

```sh
export FIX=/home/maoqh/projects/ordessa/worktree/execution-sdk-fix-20261018
export PY=/home/maoqh/projects/ordessa/worktree/nightly-restructure-20261009/.venv-nightly/bin/python
export PP="$FIX/packages/execution/units/src:$FIX/packages/execution/agents/src:$FIX/packages/execution/environments/src:$FIX/packages/execution/decision/src:$FIX/packages/infrastructure/src:$FIX/packages/backend/pacthold/src:$FIX/plugins/environments/local/src"
export STATE="$(mktemp -d /tmp/envctl-acceptance-XXXXXX)"
envctl() {
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PP" "$PY" \
    "$FIX/packages/execution/environments/examples/envctl.py" "$@"
}
```

State is CLI-owned: `environments.sqlite` (the `SQLiteEnvironmentStore`),
`aliases.json` (alias map, never secrets) and `work/` (default local root). The
state directory comes from `--state DIR` or `ENVCTL_STATE` and is required.

## 1. Envelope and exit codes (applies to every check)

`--json` prints **one** JSON object to stdout and nothing else:

```json
{"apiVersion":"agent-tools/1","requestId":"...","command":"...",
 "status":"confirmed|refused|unknown","data":...,"error":null}
```

`error` is `{"code":...,"message":...,"retryable":bool}`; `retryable` is always
`false` in v1 (nothing retries an unknown outcome). Exit codes: `0` ok, `2`
invalid/refused before any effect, `3` authorization, `4` unsupported/unavailable,
`5` conflict, `6` unknown (never retried), `7` local observation timeout.
`use` propagates the child's real exit code.

## C1 — providers (local probe, openshell reported unavailable)

```sh
envctl --state "$STATE" providers --json; echo "exit=$?"
envctl --state "$STATE" providers;          echo "exit=$?"
```

- stdout fragment: `"id": "local"`, `"available": true`, `"isolation": "none"`,
  capabilities include `process`, `files`, `byte-channel`, `stderr`.
- stdout fragment: `"id": "openshell"`, `"available": false`,
  `"status": "UNAVAILABLE"` with a non-empty `reason`.
- human mode contains `local available isolation=none` and `openshell UNAVAILABLE`.
- expected exit: `0`.

## C2 — list (resource-only, no Profile/Harness)

```sh
envctl --state "$STATE" list --json; echo "exit=$?"
```

- stdout fragment: `"resources": [` and `"orphanAliases": []`.
- expected exit: `0`.
- Note: `envctl` imports only `ordessa_environments` and
  `ordessa_environments_local`; no unit, agent, Profile or Harness is assembled
  or started (A18/A24 resource-only path).

## C3 — create local

```sh
envctl --state "$STATE" create local --root "$STATE/root" --alias demo; echo "exit=$?"
envctl --state "$STATE" create local --root "$STATE/root2" --alias other --json; echo "exit=$?"
test -d "$STATE/root" && echo "root-created"
```

- stdout fragment: `created environment/` and `alias=demo`.
- `--json` fragment: `"apiVersion":"agent-tools/1"`, `"status":"confirmed"`,
  `"data"` contains `"identity":"environment/..."`, `"alias":"other"`.
- expected exit: `0`; `root-created`.

## C4 — use echo

```sh
envctl --state "$STATE" use demo -- /bin/echo hi; echo "exit=$?"
```

- stdout fragment: `hi`.
- expected exit: `0` (the child's exit code).

## C5 — use shell (both streams)

```sh
envctl --state "$STATE" use demo -- /bin/sh -c 'echo shell-ok; echo err-line >&2'; echo "exit=$?"
```

- stdout fragment: `shell-ok`; stderr fragment: `err-line`.
- expected exit: `0`.

## C6 — exit-code propagation

```sh
envctl --state "$STATE" use demo -- /bin/false; echo "exit=$?"
envctl --state "$STATE" use demo -- /bin/sh -c 'exit 42'; echo "exit=$?"
envctl --state "$STATE" use demo --json -- /bin/false; echo "exit=$?"
```

- expected exit: `1` and `42` respectively; no stdout.
- the `--json` run exits `1` too and its envelope carries
  `"status":"confirmed"`, `"error":null`, `"data":{"exitCode":1,...}` — the
  envelope never hides the propagated command result.
- Note: a child exit code in 2..7 is indistinguishable from an `envctl` code in
  the exit status alone; `--json` disambiguates it in `data.exitCode`.

## C7 — stdin piping

```sh
printf 'x\n'      | envctl --state "$STATE" use demo -- /bin/cat; echo "exit=$?"
printf 'a\nb\n'   | envctl --state "$STATE" use demo -- /bin/cat; echo "exit=$?"
```

- stdout fragment: `x` (first), `a` and `b` (second).
- expected exit: `0` both.
- A TTY stdin is closed immediately (v1 has no interactive terminal); a regular
  file or pipe is streamed and closed.

## C8 — persistence across processes

```sh
envctl --state "$STATE" create local --root "$STATE/persist" --alias keep; echo "exit=$?"
envctl --state "$STATE" list --json; echo "exit=$?"          # a new process
```

- second process stdout fragment: `"aliases": ["keep"]` and
  `"backendId": ".../persist"`.
- expected exit: `0` both.
- The registry is reopened from `environments.sqlite`; no in-memory state is
  carried between processes.

## C9 — inspect JSON (isolation / assurance / capabilities)

```sh
envctl --state "$STATE" inspect demo --json; echo "exit=$?"
envctl --state "$STATE" capabilities demo --json; echo "exit=$?"
```

- one JSON object; `apiVersion == "agent-tools/1"`, `status == "confirmed"`.
- `data.capabilities.isolation == "none"`.
- `data.capabilities.assurance` is an object with
  `isolationIsSecurityBoundary == false` and a non-empty `statement`.
- `data.capabilities.provides` is a non-empty list; `data.capabilities.values`
  is the provider's own detail (e.g. `{"resourceKind":"directory"}`).
- `data.activeUses` is an integer.
- expected exit: `0` both.

## C10 — refusal matrix

| Command | Expected exit | Fragment |
| --- | --- | --- |
| `envctl --state "$STATE" inspect nope` | 2 | `unknown alias or identity` |
| `envctl --state "$STATE" inspect nope --json` | 2 | `"status":"refused"`, `"code":"ENVCTL_INVALID_REFERENCE"`, `"retryable":false` |
| `envctl --state "$STATE" create local --root relative/path` | 2 | `absolute path` |
| `envctl --state "$STATE" create local --root "$STATE/root" --alias demo` (again) | 5 | `already exists` |
| `envctl --state "$STATE" create openshell --root "$STATE/o"` | 4 | `OpenShell requires an already authenticated SandboxClient` |
| `env -u ENVCTL_STATE envctl list` | 2 | `state directory is required` |
| `envctl --state "$STATE" stop demo` | 2 | `refuses resource stop`, `preserved` |
| `envctl --state "$STATE" delete demo` | 2 | `refuses resource delete`, `preserved` |
| `envctl --state "$STATE" bogus` | 2 | `unknown command` |

Every refusal happens **before** any effect: no use is acquired, no process is
started, no file is deleted. `stop`/`delete` never remove user files.

## C11 — no-command refusal

```sh
envctl --state "$STATE" use demo;        echo "exit=$?"
envctl --state "$STATE" use demo --;     echo "exit=$?"
```

- stderr fragment (exactly): `terminal sessions are unavailable in v1; pass a command`.
- expected exit: `2` both.
- Pre-effect: `envctl --state "$STATE" list --json` still shows `"activeUses": 0`.

## C12 — OpenShell BLOCKED without a gateway

```sh
envctl --state "$STATE" providers --json | grep -o '"id": "openshell"[^}]*'
envctl --state "$STATE" create openshell --root "$STATE/o"; echo "exit=$?"
```

- OpenShell requires an already authenticated `SandboxClient` plus its
  same-authority RPC stub from composition. This design has no standalone
  authenticated-client bootstrap, so `providers` reports it `UNAVAILABLE`.
- expected exit for `create openshell`: `4`; no auth, token or fallback is
  invented and no service is started.
- A real OpenShell round trip is **BLOCKED** until such a client exists; it must
  not be counted as passing.

## C13 — hygiene: no secrets, no leaked processes

No secrets:

```sh
export ENVCTL_SENTINEL=do-not-print-this-value
envctl --state "$STATE" providers --json > "$STATE/p.json"
envctl --state "$STATE" inspect demo --json > "$STATE/i.json"
! grep -Eq "$ENVCTL_SENTINEL|TOKEN|SECRET|PASSWORD|API[_-]?KEY" "$STATE/p.json" "$STATE/i.json" \
  && echo "no-secret-shaped-output"
grep -Eq '^[[:space:]]*"[A-Za-z0-9._-]+": "environment/' "$STATE/aliases.json" \
  && echo "aliases-hold-only-identities"
```

- `aliases.json` holds only alias names mapped to `environment/...` identities.
- No credential-shaped value, full environment dump or `--token`-style argv
  appears in any envelope. `envctl` has no secret-bearing option.

No leaked processes:

```sh
envctl --state "$STATE" use demo --timeout 1 -- /bin/sleep 123456; echo "exit=$?"   # expect 7
sleep 6
pgrep -af 'sleep 123456$' || echo "no-leaked-process"
envctl --state "$STATE" list --json | grep -o '"activeUses": [0-9]*'
```

- timeout is a local observation timeout: expected exit `7`; the command may have
  continued and is explicitly cancelled, then re-observed within the grace window.
- after the grace window no `sleep 123456` process remains (`no-leaked-process`).
- `"activeUses": 0` — the recorded Use was released; `list` is the store's own
  view of active uses.

## Not proven (explicit non-goals)

- **units / agents**: no unit or agent assembly, no `LaunchSpec`, no
  Profile/Harness resolution, no sandbox resolution, no `OperationJournal`,
  no records or materialization. `envctl` never imports those owners.
- **ACP**: no ACP frames, reverse requests, permissions/approvals, detach or
  native cancellation semantics. A local SIGINT is not ACP cancellation.
- **model**: no model or provider call of any kind; `use` runs a local OS process
  only.
- **product**: no `ordessa-agent` CLI, no Server/wire/HTTP/WS, no MCP mapping, no
  Skill, no doctor/capabilities service surface, no auth/authorization. `envctl`
  is a standalone reference driver, not the product CLI; exit code `3` is
  reserved but unreachable here because there is no authorization surface.
- **OpenShell**: blocked without an authenticated client (C12).
- **terminal sessions**: unavailable in v1 (C11); `use` is one-shot only.
- **cross-manager concurrency/leases**: only the store's own admission rules are
  exercised; no lease or detach holder exists.
- **`use --json` capture**: command stdout/stderr is captured up to 1 MiB and
  flagged `truncated`; it is not a streaming substitute and may contain the
  child's own output.
