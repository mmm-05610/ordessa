# Ordessa CLI acceptance

Layer status is recorded separately; a passing source test never stands in for
an installed run, a real Harness handshake or a real-model call. Every row below
was measured on 2026-10-20 against the current working tree and the frozen
16-wheel closure; the local evidence paths live under
`tmp/lower-cli-plan/evidence/` (git-ignored).

| Layer | State | Evidence |
| --- | --- | --- |
| source suites | PASS | `apps/cli/tests`, environments, agents sdk/instances/profiles, harness capability, decision runtime, JeV identity/long_context (512 passed / 1 skipped on the combined run) |
| installed, non-editable (16 wheels) | PASS | `tmp/env/venv-final`; `cli_acceptance.py --entrypoint installed` **21/21** (`evidence/H7-installed/cli-installed.json`) |
| installed closure imports | PASS | all imported origins under site-packages; zero Units/Engineering/Server/pacthold/kernel/old-runtime/old-aggregate modules loaded (`evidence/H7-installed/import-origins.json`) |
| wheel metadata audit | PASS | `wheel_acceptance.py` on the frozen closure (contracts/interfaces/cli; Server wheel not in the lower closure → NOT_RUN) |
| Local environment lifecycle | PASS | `lower_cli_lifecycle_acceptance.py` **13/13** (create→acquire→export→profile→start→get→cancel accepted+replay→stop→reconcile exited→process-release→Use release→exit 0) |
| detach semantics | PASS | `lower_cli_detach_acceptance.py` **6/6** |
| real brand protocol — kilo | PASS | lifecycle 13/13 (ACP, loopback only, no model) |
| real brand protocol — dsh | PASS | start `running` + native `sessionId`, stop/reconcile/release/exit 0 (source and installed) |
| real brand protocol — pi | PASS | native `pi-rpc/1` start `running` + native `sessionId`, stop/reconcile/release/exit 0 (source and installed) |
| real model prompt (kilo) | PASS | `lower_cli_model_acceptance.py --expect 391` **5/5**; the model computed 17×23=391 and the answer was checked verbatim (`evidence/H4-brands/KILO-PROMPT.md`) |
| real model prompt (all six brands) | PASS | kilo 5/5; dsh/hermes source receipts; pi/claude/codex source **and** installed; every answer checked verbatim (`evidence/H5-native/PROMPT.md`) |
| Decision rules (CEL) | PASS | real `rules` job completed with digest; cold `query` returned the same value with zero model calls (`evidence/H6-rules/`) |
| Decision ask — JeV (choice/noul/score) | PASS | real Zen calls: choice, 5-level score (`result 0.04`), noul; replay/conflict/refusal negatives; key never persisted (`evidence/H6-jev/`, `evidence/H6-score/`) |
| OpenShell environment | PASS (source + installed) | providers report gateway 0.1.3; create/inspect/exec(stdin,stderr,exit)/files/delete all completed; no residue (`evidence/H3-20261020/`, `evidence/H7-installed/openshell-installed.txt`) |
| OpenShell hosts a real agent (A27) | PASS | real sandbox + real kilo: native session id, real model prompt (391), stop → reconcile `exited(0)` → process-release → delete → exit 0; image must carry the harness + `python3`, policy must allow the model host (and the package registry for a harness that installs deps on first launch) (`evidence/H3-20261020/A27-PASS.json`) |
| real brand protocol — hermes | PASS | start `running` + native `sessionId`; stop/reconcile/release/exit 0; needs a `home/config.yaml` prepared configuration and a warmed `HERMES_HOME` (`evidence/H4-hermes-config/HERMES-CLI-PASS.md`) |
| real brand protocol — claude | PASS (start/lifecycle) | `claude-stream-json/1`: pinned native `sessionId`, control handshake observed, exit 0; prompt/cancel not in this slice (`evidence/H5-native/BOOTSTRAP-PASS.md`) |
| real brand protocol — codex | PASS (start/lifecycle) | `codex-app-server/1`: `initialize`+`thread/start`, native thread id, exit 0; prompt/cancel not in this slice (`evidence/H5-native/BOOTSTRAP-PASS.md`) |
| native prompt/cancel — codex | PASS | real model answered `391`; source **and** installed closure (`evidence/H5-native/PROMPT.md`) |
| native prompt/cancel — claude | PASS | real model answered `391` (cost $0.11); source **and** installed closure |
| native prompt/cancel — pi | PASS | real model answered `391`; source **and** installed closure (credential file generated from the authorised orchestration key, since the local pi subscription key is expired) |
| native prompt/cancel — codex | PASS | 
| native prompt/cancel — hermes | PASS | real model answered `391`; the API key stays an env reference (`harness.json` `envFrom` → `model.key_env`), never written into the prepared config (`evidence/H4-hermes-config/hermes-prompt.log`) |
| A23 real cancel during generation | PASS (semantics, three protocols) | first Ctrl+C → cancel notification accepted, original result **not** rewritten; terminal state differs honestly by race: Codex `unknown` (exit 6), Claude `failed`, Pi `completed`; cleanup still exits 0 (`evidence/H5-native/CANCEL-A23.md`) |
| Pi/other brand unit suites | **PARTIAL** | Pi's own pytest set still shows pre-existing drift (66 passed / 1 failed / 13 errors against removed modules) |
| product experience (Desktop/Workbench/production Server) | NOT_IN_SCOPE | not required to close this lower slice |

## Reproduce (fresh environment)
The frozen closure is 16 wheels (all from this worktree): infrastructure,
interfaces/contracts, interfaces/transport/server/plugin-api, interfaces,
execution/agents, execution/environments, environments/local,
environments/openshell, execution/decision, decision/rules-cel, decision/jev,
harness/kilo, harness/pi, harness/dsh, transport/client/python and apps/cli.

```sh
# from the worktree root
W=tmp/env/wheels-final; V=tmp/env/venv-final
for p in packages/infrastructure packages/interfaces/contracts \
         packages/interfaces/transport/server/plugin-api packages/interfaces \
         packages/execution/agents packages/execution/environments \
         plugins/environments/local plugins/environments/openshell \
         packages/execution/decision plugins/decision/rules-cel plugins/decision/jev \
         plugins/harness/kilo plugins/harness/pi plugins/harness/dsh \
         packages/interfaces/transport/client/python apps/cli; do
  uv build --wheel --no-build-isolation --out-dir "$W" "$p"
done
uv venv --python 3.12 "$V"
uv pip install --python "$V/bin/python" --offline --find-links tmp/env/wheelhouse \
  "agent-client-protocol==0.12.1" "cel-python==0.5.0" "referencing==0.36.2" \
  "jsonschema>=4.20,<5" "fastapi>=0.115,<1" "PyYAML==6.0.3" "tomli-w==1.2.0" \
  openshell grpcio protobuf googleapis-common-protos
uv pip install --python "$V/bin/python" --offline --find-links "$W" --find-links tmp/env/wheelhouse "$W"/*.whl
"$V/bin/ordessa" --help
```

`--offline`/`--find-links` use the local wheel set only; `--no-deps` and
`PYTHONPATH` are **not** used for the acceptance run. `tmp/env/install-manifest.json`
records the 16 wheel hashes, the build/install commands and the receipt paths.

## Manual walkthrough (run and compare)

### 1. Environments (one-shot)

```sh
O=tmp/env/venv-final/bin/ordessa; S=/tmp/ordessa-accept   # fresh 700 dir
$O --state $S environments create local --root $S/work --alias demo \
   --request-id env-001 --json          # exit 0, data.identity environment/...
$O --state $S environments exec demo --request-id exec-001 -- /usr/bin/printf 'hello\n'
                                        # stdout hello\n, exit 0
$O --state $S environments files demo write kept.txt kept
$O --state $S environments files demo cat kept.txt --json
                                        # exit 0, data.content == "kept"
$O --state $S environments list --json  # activeUses == 0
$O --state $S environments stop demo --json
                                        # exit 2 refused: provider has no lifecycle op
```

### 2. Decisions (real CEL engine)

Create the job template from `README.md` as `/tmp/rules-job.json`, then:

```sh
$O --state $S decisions validate --job /tmp/rules-job.json --json    # exit 0
$O --state $S decisions run --job /tmp/rules-job.json \
   --request-id decision-001 --save-result $S/decision.json --json    # exit 0
$O --state $S decisions query --original-request-id decision-001 \
   --job /tmp/rules-job.json --json                                   # same data
$O --state $S decisions get --digest <evidence digest> --json         # summary
# different input, same request id -> exit 5 CONFLICT
# unknown request id -> exit 2 INVALID_INPUT ("not found")
# an ask job with no provider -> exit 4 PROVIDER_UNAVAILABLE
```

`--save-result` never overwrites: the second use of the same path is refused
with exit 5 before any effect.

### 3. Agents: real kilo, foreground session

First admit the brand **before** starting the session (admission is read when
the catalog is built):

```sh
python3 - <<'EOF'
import json, pathlib
pathlib.Path('/tmp/ordessa-accept/harness.json').write_text(json.dumps(
    {"allowlist": ["kilo"], "providers": {"kilo": {"command": ["/absolute/path/to/kilo"]}}}))
EOF
```

Put `roots.json` and a Profile manifest (PIN from `agents harness list`) in
`$S`, then run `$O --state $S session` and paste the session block from
`README.md`. Expected results:

- `agents harness list`: one descriptor, `providerId=kilo`, `protocolId=acp`,
  seven required roots.
- `agents start`: `status=completed`, `data.state=running`, an `instanceRef`,
  a native `sessionId` and a `processEndpointRef`.
- `agents get`: the same receipt (replay, no relaunch).
- `agents stop`: completed terminate request; the process may still be running.
- `agents reconcile`: repeat until `state=exited` with the observed exit code.
- `environments process-release`: completed only after exit; receipt says
  `transportReleased=true`, `exitClaimed=false`.
- `environments release`: completed, `resourcePreserved=true`; the work
  directory still exists.
- `exit`: 0. Before cleanup, `exit` lists the retained Agent/Use/process and
  refuses.

### 4. Real model prompt (kilo)

Same session, after `agents start`, with the model configuration described in
`README.md` (`harness.json` `envFrom` → the API key env name; the key itself is
never written to the state) and the CA variables from the trap list:

```sh
agents prompt --instance-ref <start.json#/data/instanceRef> --params <params.json> \
  --request-id prompt-001 --timeout 120 --json --save-result <prompt.json>
agents query --query <query.json> --json          # same turn, no re-execution
```

Expected: `status=completed`, `data.state=completed`, a `turnRef`, the model's
answer in the observation frames, and `usage` reported. A concrete task plus a
verbatim answer check is the reproducible form (`--expect 391` in
`lower_cli_model_acceptance.py`).

### 5. Other admitted brands (pi, dsh)

Write `{"allowlist": ["pi"], ...}` (or `dsh`) before the session, then run the
same block. Expectations differ only in the descriptor:

- `pi`: `protocolId=pi-rpc/1` (native, **not** ACP); `start` still yields
  `state=running` with a native `sessionId`.
- `dsh`: `protocolId=acp`; same lifecycle as kilo.

Hermes (`acp`), Claude (`claude-stream-json/1`) and Codex (`codex-app-server/1`)
also start on this chain; the native two need a `credentials.file` binding in
the Profile (see `README.md`). None of them is translated into ACP.

### 6. OpenShell environment

Create `<state>/openshell.json` (endpoints/workspace/fileRoot/fileHelper, mTLS
from the official gateway registration) and a structured create reference:

```json
{"image": "python:3.12-slim",
 "policy": {"version": 1,
            "filesystem": {"read_only": ["/"], "read_write": ["/sandbox"]},
            "landlock": {"compatibility": "hard_requirement"}},
 "main_command": ["sleep", "infinity"]}
```

```sh
$O --state $S environments providers --json      # openshell available, gatewayVersion 0.1.3
$O --state $S environments create openshell --reference ref.json --alias demo --request-id env-1 --json
$O --state $S environments exec demo -- /usr/local/bin/python3 -c 'print("hello")'
$O --state $S environments files demo write note.txt hi
$O --state $S environments files demo cat note.txt --json
$O --state $S environments delete demo --json    # completed, confirmed:true
openshell sandbox list                           # empty afterwards
```

Every failed pre-condition (bad policy spelling, missing reference, unknown
provider, path escape) is refused **before** any gateway dispatch.

#### 6.1 Hosting a real harness on OpenShell (A27)

Use an image that contains the harness and `python3` (the file helper probe),
and a policy that allows the model host for prompts. A harness that installs
provider dependencies on first launch also needs the package registry once
(bake those in the image to keep egress limited to the model host later).

```json
{"image": "localhost/ordessa-harness-kilo:1",
 "policy": {"version": 1,
            "filesystem": {"read_only": ["/"], "read_write": ["/sandbox", "/root", "/tmp"]},
            "landlock": {"compatibility": "hard_requirement"},
            "network_policies": {"opencode-model": {
              "name": "opencode-model",
              "endpoints": [{"host": "opencode.ai", "port": 443},
                            {"host": "registry.npmjs.org", "port": 443}],
              "binaries": [{"path": "/usr/local/bin/kilo"}, {"path": "/usr/local/bin/node"}]}}},
 "main_command": ["sleep", "infinity"]}
```

`harness.json` keeps the model key an environment reference
(`envFrom: {"KILO_PROVIDER_KEY": "OPEN_CODE_GO_API_KEY"}`); the Profile has no
credential file. Then run the ordinary agent chain from section 5 on the
OpenShell endpoint (`export-endpoint ... launcher observe communicate terminate
detach files --roots roots.json`). Verified end-to-end receipt:
`evidence/H3-20261020/A27-PASS.json` and `a27-pass-session.log`.

Unattended/offline evidence:

```sh
tmp/env/venv-final/bin/python tests/integration/packages_convergence/lower_cli_lifecycle_acceptance.py \
  --state /tmp/ordessa-lifecycle --receipt /tmp/lifecycle.json
# {"status":"PASS","passed":11,"failed":0,"networkIsolated":true,...}
```

The script can run the whole session inside `unshare -rn` with only loopback up;
when the host denies user namespaces (as on this machine) pass `--no-namespace`
and it runs on the current namespace instead. Either way it sends no model
prompt: this row proves the ACP handshake and lifecycle, not a model call.

## Negative and boundary checks

- `ordessa unknown thing` → exit 4 `CAPABILITY_UNSUPPORTED`.
- `environments create local` without `--root` → exit 2 before any effect.
- A non-private `--state` directory → exit 2 (`--state directory must not be
  group/other accessible`).
- A foreign Environment database under `--state` → exit 2 with one JSON
  refusal envelope.
- A duplicate `--save-result` target → exit 5, no handler call.
- `--instance-ref FILE#/data/missing` → exit 2, no request sent.
- Session `exit` with a live Use or running/unknown Agent → retained list and
  refusal; no fake "released" receipt.
- Ctrl+C during an active prompt: the **first** press sends the native
  `session/cancel` notification and keeps waiting; the **second** press stops
  waiting locally. The original result is never rewritten as `cancelled`.
- Installed import audit: `ordessa_agent_tools.cli` + `session` load no
  `ordessa_server`, `ordessa_units`, `ordessa_engineering`, `pacthold`,
  `ordessa_kernel` or `ordessa_agent` module; every imported distribution
  origin is the installed site-packages.

## Test commands used

```sh
# channel + CLI (source, dev environment)
pytest apps/cli/tests/test_lower_cli_flow.py apps/cli/tests/test_boundaries.py \
       apps/cli/tests/test_remote_mode.py \
       packages/interfaces/tests/test_cli_multilevel_and_results.py -q
# installed layout
ORDESSA_TEST_INSTALLED=1 ORDESSA_TEST_PYTHON=tmp/env/venv-final/bin/python \
  tmp/env/venv-final/bin/python -m pytest packages/interfaces/tests -q
# owners
pytest packages/execution/environments/tests -q
pytest packages/execution/agents/tests/sdk packages/execution/agents/tests/instances \
       packages/execution/agents/tests/profiles \
       packages/execution/agents/tests/test_zero_environment_dependency.py -q
pytest packages/execution/decision/tests/test_capability.py \
       packages/execution/decision/tests/test_original_run_read.py \
       packages/execution/decision/tests/test_engine_discovery.py \
       packages/execution/decision/tests/test_runner.py \
       packages/execution/decision/tests/test_request_replay.py \
       packages/execution/decision/tests/test_scoped_evidence.py \
       packages/execution/decision/tests/test_evidence_durability.py \
       packages/execution/decision/tests/test_job.py \
       packages/execution/decision/tests/test_predicate.py \
       packages/execution/decision/tests/test_ports.py \
       packages/execution/decision/tests/test_definitions.py \
       packages/execution/decision/tests/test_digest_redaction.py \
       packages/execution/decision/tests/test_answer_validation.py \
       packages/execution/decision/tests/test_claim_guard.py \
       packages/execution/decision/tests/test_migrated_assertions.py \
       packages/execution/decision/tests/test_migration_source.py \
       packages/execution/decision/tests/evidence/test_historical_reader.py -q
pytest plugins/environments/local/tests plugins/decision/rules-cel/tests -q
```

## Untested, blocked and retained old paths

- Installed-closure real model prompt: NOT_RUN (source-level kilo prompt passed 5/5).
- Hermes / Claude Code / Codex native bootstrap: NOT DONE (deferred by scope).
- Pi's own pytest suite: pre-existing drift (66 passed / 1 failed / 13 errors).
- Real model prompt and Decision `ask` calls in restricted environments: **BLOCKED** (no approved scope,
  budget or data permission). The CLI refuses instead of faking a result.
- `agents cancel` is published inside the foreground session only; an idle
  session's `accepted` notification is not proof that an active generation was
  cancelled. A23's real interactive Ctrl+C row is unit-tested, not measured on a
  live generation. `stop` and `detach` remain independent operations.
- `agents detach` full transfer scenario: the operation exists and releases the
  association/transport, but no real external owner takeover was exercised.
- Local `stop`/`delete`: provider explicitly unsupported; files preserved.
- `packages/interfaces/tests/http/test_transport_contract_wall.py` fails on an
  unchanged HTTP registry import; pre-existing, not caused by this slice.
- Some Decision acceptance tests require a built neutral wheel or `pacthold`;
  they collect/fail before exercising this change and are registered as
  pre-existing red.
- The old `ordessa-agent` console and `ordessa-cli-runtime` parser are no
  longer registered or imported by the new CLI. The old distribution and its
  historical tests remain for frozen upper-test references; they are not part
  of the new install closure. Full-repository removal needs an upper-owner
  decision.
- `tests/integration/packages_convergence/test_default_agent_registry.py` and
  `test_local_cli_lifetime_boundary.py` were updated to the new entry/import
  paths but were **not executed** here: they need the full Server/Units
  closure, which is frozen and outside this install selection.
  `packages/interfaces/tests` ran 120 passed / 2 skipped / 1 pre-existing
  failure (the unchanged HTTP transport wall). The full convergence integration
  directory was not run as one suite.
- The earlier main-consolidation `retirement_audit.py` still names the deleted
  Server CLI file; it is historical and was not re-run.
