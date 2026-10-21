# Ordessa CLI

`apps/cli` owns the single `ordessa` executable. It exposes three capability
groups on one command tree and one JSON envelope (`agent-tools/1`):

```text
ordessa environments providers|list|inspect|create|register|exec|files
                     acquire|release|process-release|export-endpoint
                     endpoint-inspect|use-inspect|launch|stop|delete
ordessa agents       harness list|describe
                     profiles list|create|entry|read|edit|clone|rename
                              archive|restore|preview
                     start|get|prompt|query|reconcile|stop|detach
ordessa decisions    validate|run|get|evidence|query
ordessa list|describe OPERATION|call OPERATION --input FILE
ordessa session
```

There are two explicit modes and no implicit fallback:

- local: `--state ABSOLUTE_DIR` (or `ORDESSA_STATE`) opens only the owner files
  below that private directory;
- remote: `--config FILE --service ALIAS` reuses the bounded, non-retrying
  `ordessa_system_access_client` over `wire/1`.

Global options are `--json`, `--request-id ID`, `--timeout SECONDS`,
`--save-result FILE` and `--help`. A leading `--timeout` bounds the operation
deadline; after a command path it belongs to that command when the command
declares its own `timeout` (for example `environments exec`). `--save-result`
creates a new private file exactly once; an existing path is refused before any
effect. JSON-file arguments accept `FILE#/data/pointer` field references so a
value from a previous result can be reused without hand copying.

Exit codes: `0` completed, `2` refused, `3` accepted, `4` unsupported,
`5` conflict, `6` unknown, `7` observation timeout. `environments exec` returns
the child's exit code when the command completed; the JSON envelope still
reports the execution status separately.

## Install (offline, non-editable)

Build the selected closure from this checkout and install it into a fresh
Python 3.12 environment. No `--no-deps`, `PYTHONPATH` or source-tree import is
used for the acceptance run:

```sh
uv build --wheel --no-build-isolation --out-dir /new/wheels \
  packages/infrastructure packages/interfaces/contracts \
  packages/interfaces/transport/server/plugin-api packages/interfaces \
  packages/execution/agents packages/execution/environments \
  plugins/environments/local packages/execution/decision \
  plugins/decision/rules-cel plugins/harness/kilo \
  packages/interfaces/transport/client/python apps/cli

uv venv --python 3.12 /new/ordessa-venv
uv pip install --find-links /new/wheels --offline \
  "agent-client-protocol==0.12.1" "cel-python==0.5.0" "referencing==0.36.2" \
  "jsonschema>=4.20,<5" "fastapi>=0.115,<1" "PyYAML==6.0.3" "tomli-w==1.2.0"
uv pip install --find-links /new/wheels --offline /new/wheels/*.whl
/new/ordessa-venv/bin/ordessa --help
```

The real brand is the explicit `harness-kilo` extra in the distribution; the
same wheel is included above. The rules engine (`cel-python`) is a hard
dependency because every Decision rules run uses it.

## Ownership and dependencies

- `ordessa_interfaces.channels.cli` owns parsing, help, the one envelope,
  save-result and field references. It imports no owner.
- `ordessa_interfaces.system_access` owns the registry and dispatch; it imports
  no owner.
- `ordessa_agents.capability` owns the Agent/Profile/Harness
  capability adapters; Server and CLI publish the same implementation.
- `apps/cli` owns only the local/remote composition and the foreground session.
- The CLI closure does not import or depend on Units, Engineering, the Server
  runtime, the retired kernel or the old `ordessa-agent` parser. The former
  `ordessa-cli-runtime` distribution is **retired**: removed from the Python
  workspace and source (its deletion is recorded in the current snapshot), and
  it is not part of this wheel's closure.

## First run: environments

```sh
STATE=/tmp/ordessa-demo
ordessa --state "$STATE" environments create local \
  --root "$STATE/work" --alias demo --request-id env-001 --json
ordessa --state "$STATE" environments exec demo \
  --request-id exec-001 -- /usr/bin/printf 'hello\n'
ordessa --state "$STATE" environments files demo write kept.txt kept
ordessa --state "$STATE" environments files demo cat kept.txt --json
```

Local `stop`/`delete` are reported as unsupported (the provider owns no such
lifecycle); user files are preserved. `acquire`, `launch`, `export-endpoint` and
`process-release` are session-only: a one-shot process cannot retain the
original Use/process handles, and the CLI refuses to pretend it can.

## Decisions

`--job FILE` accepts a `decision-job/1` document. Rules payloads use the CEL
engine's shape (`{"checks":[...],"default":{...}}`):

```json
{
  "spec_version": "decision-job/1", "job_id": "demo-rules", "version": 1,
  "input": {"score": 7},
  "limits": {"max_model_calls": 0, "max_steps": 4,
             "max_value_bytes": 4096, "timeout_seconds": 5.0},
  "steps": [{"id": "gate", "type": "rules", "engine": null,
             "when": {"fact": "input.score", "op": "gte", "value": 1},
             "payload": {"checks": [{"id": "high", "when": "input.score >= 5"}],
                         "default": {"answer": "accept"}}}],
  "result": {"from": "gate", "path": ["values", "default"]}
}
```

```sh
ordessa --state "$STATE" decisions validate --job /tmp/rules-job.json
ordessa --state "$STATE" decisions run --job /tmp/rules-job.json \
  --request-id decision-001 --save-result /tmp/decision.json --json
ordessa --state "$STATE" decisions query \
  --original-request-id decision-001 --job /tmp/rules-job.json --json
ordessa --state "$STATE" decisions get --digest <digest> --json
```

`query` reads the original claim/result by request id and recomputed input
digest. It never claims, executes or resends. A pending claim returns
`accepted`/`pending`; a different input returns `CONFLICT`; a missing record is
an explicit refusal. `ask` steps require a real provider/permit; with none
configured the run is refused (`PROVIDER_UNAVAILABLE`), never silently downgraded.

## Agents (foreground session)

A one-shot Agent start is refused: it needs the retained Use/endpoint handles.
Use one session process. The Session keeps one event loop, one Environment
owner and one Agent/Profile owner.

Ctrl+C has two distinct steps and never rewrites the original result:

1. **First press during an active `agents prompt`** sends the provider's native
   `session/cancel` notification (durable claim, one write, same request id
   replays) and **keeps waiting** for the original call. It prints the
   notification state, not a cancellation claim.
2. **Second press** stops waiting locally; whatever the original call recorded
   stays `unknown`/retained. A cancel request is not an outcome.

Outside a prompt, Ctrl+C cancels the local command immediately (as before).
`exit` reports retained work and refuses a normal exit until it is released.

```sh
ordessa --state "$STATE" session
```

Inside the session (the file arguments are real templates):

```text
# roots.json: every root key the installed harness requires
{"work":".","home":"home","config":"config","data":"data","state":"state","cache":"cache","tmp":"tmp"}

environments create local --root /tmp/ordessa-demo/work --alias demo --request-id env-001 --json
environments acquire demo true --request-id use-001 --json --save-result /tmp/demo/use.json
environments export-endpoint --use-identity /tmp/demo/use.json#/data/useIdentity \
  launcher observe communicate terminate detach files \
  --roots /tmp/demo/roots.json --request-id ep-001 --json --save-result /tmp/demo/endpoint.json
agents harness list --json
agents profiles create demo-profile --name Demo --manifest /tmp/demo/profile.json \
  --request-id prof-001 --json --save-result /tmp/demo/profile-result.json
agents start --profile-ref /tmp/demo/profile-result.json#/data/currentManifestRef \
  --endpoint-ref /tmp/demo/endpoint.json#/data/endpointRef \
  --request-id start-001 --timeout 30 --json --save-result /tmp/demo/start.json
agents get --start-request-id start-001 --json
agents stop --instance-ref /tmp/demo/start.json#/data/instanceRef \
  --request-id stop-001 --timeout 30 --json --save-result /tmp/demo/stop.json
agents reconcile --instance-ref /tmp/demo/start.json#/data/instanceRef --request-id rec-001 --json
environments process-release --endpoint-ref /tmp/demo/start.json#/data/processEndpointRef \
  --request-id prel-001 --json --save-result /tmp/demo/prelease.json
environments release --use-identity /tmp/demo/use.json#/data/useIdentity \
  --request-id rel-001 --json --save-result /tmp/demo/release.json
exit
```

A Profile manifest must pin an installed harness:

```json
{"schemaVersion": "1",
 "harnessDefinitionRef": {"environmentNamespace": "<from harness list>",
                          "definitionId": "kilo", "revision": "0.1.0a1"},
 "declarations": []}
```

Ordering matters: `stop` records a terminate request; `reconcile` is the
independent exit observation (it may need to be repeated); only after
`state: exited` does `process-release` release the original transport (and only
if it was observed exited). `environments release` then releases the Use. The
work directory is preserved.

The first real brand is **kilo** (`kilo acp`, ACP over stdio). The CLI supplies
`KILO_CONFIG_CONTENT='{"autoupdate":false}'` and
`KILO_DISABLE_MODELS_FETCH=1` as explicit non-secret launch data, and it starts
the resolved absolute binary in a private working directory. Kilo needs a
loopback interface for its internal service; it does not need external network
for `initialize`/`session/new`. A prompt would call a real model and is outside
this delivery's authorization.

Optional trusted overrides live in `<state>/harness.json` (data only, never
credentials):

```json
{"providers": {"kilo": {"command": ["/absolute/path/to/kilo"],
                        "env": {"KILO_CONFIG_CONTENT": "{\"autoupdate\":false}"}}}}
```

### Hosting an Agent on OpenShell (verified)

An OpenShell Use can export an agent endpoint (`launcher observe communicate
terminate detach files`) once the sandbox is READY; the provider already speaks
the gateway's bidirectional `ExecSandboxInteractive` channel, and the CLI adds a
guarded stdin writer plus remote command/PATH/directory handling. A real kilo
harness was bootstrapped and prompted through that endpoint
(`agents start` → `agents prompt` → `agents stop` → `reconcile` → release).

Operational requirements, all explicit:

- the image must contain the harness **and** `python3` (the file helper probe);
  `node:22` plus `npm i -g @kilocode/cli` is a working example;
- the policy must allow the model host for prompts (`network_policies.<name>
  .endpoints:[{host,port}]` with a non-empty `binaries` allow-list — without
  `binaries` even DNS is refused);
- a harness that installs provider dependencies on first launch also needs the
  package registry once; bake those dependencies into the image to keep egress
  limited to the model host later;
- credentials stay in the launching environment: `harness.json` `envFrom`
  binds e.g. `KILO_PROVIDER_KEY`, never a file in the image.

Remote termination is a sandbox-local unique `kill -TERM` (argv pattern passed
through the environment so the kill shell cannot match itself) followed by a
stdin half-close so the supervisor finalizes the exec session. Only the
resulting `exit` receipt is recorded as a confirmed exit; if no receipt arrives
the outcome stays `unknown` (the fixed process observation requires an integer
exit code for `exited`). `agents cancel` remains a native protocol notification,
`stop` is process termination and `detach` releases the transport; they are not
interchangeable, and a written notification is not proof the provider stopped
generating.

## Harness admission and supported brands

No harness entry point is loaded unless the state directory admits it explicitly:

```json
{"allowlist": ["kilo", "pi", "dsh"],
 "providers": {"kilo": {"command": ["/absolute/path/to/kilo"]}}}
```

Semantics: a missing `allowlist` admits nothing; an installed-but-unlisted
provider is reported as `notAdmitted` and its module is never imported; a listed
but uninstalled provider is reported as `allowlisted provider is not installed`.
Every provider command is an absolute argv list; credentials are only ever
environment **references** (`envFrom`), never literals.

Verified on this chain (2026-10-20, source and installed closure):

| brand | protocol | verified |
| --- | --- | --- |
| kilo | ACP | start/prompt(real model)/query/cancel/stop/detach/release |
| dsh | ACP | start (native session id) / stop / reconcile / release |
| pi | `pi-rpc/1` (native, not ACP) | start (native session id) / stop / reconcile / release |
| hermes | ACP | start (native session id) / stop / reconcile / release (needs a `home/config.yaml` prepared configuration and a warmed `HERMES_HOME`) |
| claude | `claude-stream-json/1` (native, not ACP) | start (pinned native session id) / stop / reconcile / release |
| codex | `codex-app-server/1` (native, not ACP) | start (native thread id) / stop / reconcile / release |

Native brands never receive ACP frames: each provider exports its own
`open_native_session` and `prompt_handler`. `agents prompt`/`cancel` dispatch by
the instance's protocol id — ACP keeps its `session/prompt`/`session/cancel`
path, while each native brand encodes its own frames:

| brand | prompt | completion | cancel |
| --- | --- | --- | --- |
| codex | `turn/start` | `turn/completed` | `turn/interrupt` |
| claude | one `type=user` line | `type=result` | `control_request{interrupt}` |
| pi | `prompt` | `agent_settled` (not `agent_end`) | `abort` |

Real-model prompt rows verified on this chain (source and installed closure):
**all six brands** (kilo, dsh, pi, hermes, claude, codex) answered `391` to
17×23; pi/claude/codex were also verified from the installed closure. Hermes
keeps its key as an `envFrom` reference named by `model.key_env`; dsh keeps
`DEEPSEEK_API_KEY` in a bound `.env` (non-secret `DEEPSEEK_BASE_URL` and
`DEEPSEEK_DEFAULT_MODEL` must come from the launch environment, because dsh
refuses them inside a `.env`). Pi's local subscription key
is expired (403) — its row uses a credential file generated from the authorised
orchestration key. Hermes prompts through ACP and needs a warmed data root.

### Credential bindings (native brands)

Codex and Claude authenticate from files. Declare the binding **visibly in the
Profile**; the Profile carries paths, never secrets:

```json
{"declarationId":"credential-binding-1","configurationKind":"credentials.file",
 "schemaVersion":"1","action":"value","requirement":"required",
 "payload":{"sourcePath":"/home/me/.codex/auth.json","rootKey":"home","relativePath":"auth.json"}}
```

The CLI copies it into that environment's private root at preparation time
(mode 0600, must stay inside an approved root, absolute source, regular file,
≤ 256 KiB). Target roots: Codex `$CODEX_HOME` = `home`; Claude
`$CLAUDE_CONFIG_DIR` = `config`. The bytes never enter the Agent records,
receipts or evidence.

## Environment traps (these are not CLI bugs)

- **Model calls and TLS.** Kilo's model HTTP stack needs the system CA exposed:
  set `NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt` and
  `NODE_USE_SYSTEM_CA=1`. Without them a real prompt fails inside the brand with
  `-32603 unknown certificate verification error`.
- **Proxy vs loopback.** Loopback gRPC (OpenShell gateway) must never go through
  an ambient proxy: unset `http_proxy/https_proxy/all_proxy` for the CLI process
  (the OpenShell binding does this itself for loopback).
- **`no_proxy` with `[::1]`.** A lowercase `no_proxy` containing `[::1]` makes
  `httpx2` fail URL parsing, which surfaces as a misleading
  `PROVIDER_UNAVAILABLE`. Use `127.0.0.1,localhost` instead.
- **Admission is read at session start.** Writing `harness.json` inside a running
  session has no effect; write it before starting the session.
- **Job limits.** A decision job's `limits.timeout_seconds` is capped at 30 by
  the host; larger values are refused before any effect. The JeV provider's
  `decision.json.timeoutSeconds` is a separate per-call bound (up to 300).
- **Rules result path.** A `rules` step exposes `{"values":…,"disposition":…}`, so
  `result.path` must start with `["values", …]`.
- **OpenShell sandbox names** are limited to 19 characters; the provider derives
  the name itself. The internal runtime image is **not** a workload image — use a
  normal image with `python3` for file capabilities (`python:3.12-slim` verified).
- **Prepared configurations.** A `prepared-configuration-ref` must carry a full
  `bound-path/1` location (`schemaVersion`, `rootKey`, `relativePath`) and is
  verified against the real bytes at export time.
- **`environments files` takes a short exclusive Use**, so the order is
  `create → files → acquire → export-endpoint`.

## Known limits of this slice

- No production Server identity/project mapping, Desktop/Workbench or product
  packaging is included.
- Engineering, Units and the frozen upper runtime are untouched.
- Full-repository Unit retirement remains incomplete; the new CLI closure does
  not import Units.
- Real-model prompt/ask calls need explicit scope/budget authorization; a
  passing run does not grant it.
- Pi has no real-model prompt evidence (unit-tested only); Hermes real-model
  prompt was not re-run this round.
- The installed real-model prompt row remains open (see `ACCEPTANCE.md`).
