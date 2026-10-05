# Current acceptance: public CLI and owner configuration

This is a partial implementation. Runnable Agent nodes, native tasks and task
result queries have not been delivered. Installation or passing controlled tests must
not be interpreted as full product acceptance.

## Install without global changes

Choose a fresh virtual environment and use the generated local wheel:

```sh
python3.12 -m venv /your/selected/agent-tools-venv
cd /path/to/bundle-0.1.0a2-init
sha256sum --check SHA256SUMS
/your/selected/agent-tools-venv/bin/python -m pip install --no-index --no-deps cli/ordessa_agent_tools-0.1.0a2-py3-none-any.whl
/your/selected/agent-tools-venv/bin/ordessa-agent --help
```

Alternatively install `products/agent-tools` from this source tree into the
selected venv. Skills are optional project-local source assets; no installation
step modifies global Agent configuration or starts Server.

## Verify the implemented behavior

The source acceptance environment needs the repository's local backend package
closure and test dependencies. Missing resources must fail, not become skips.
Run with the prepared implementation venv or an equivalent isolated environment:

```sh
python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests -q
```

Record test counts and exit code by category, using the implementation evidence
ledger rather than summing historical runs. Separate client/unit and public-wire
contracts, real temporary SQLite/claim tests, controlled native peers, fresh
wheel/venv installation, and real isolated Server processes. Server process
evidence does not establish a real Harness or a model task. The exact dated
receipts and known failures are in `docs/implementation/agent-tools/status.md`;
the older 240-test catalog snapshot is historical, not current full acceptance.

For the installed client, configure an explicit service alias and tokenEnv using
[README](README.md). Exercise `doctor`, `profiles list`, create/edit with actual
manifest references and CAS, and read an old returned full ProfileRef after edit.
A conflicting revision must produce exit 5, authorization refusal exit 3, and
unknown write outcome exit 6 without retries. Preview currently refuses readiness
with exit 4. The optional deployment currently reports nodes=false and
managedInput=false; for another service, preserve its observed flags without
interpreting them as task commands available in this installed CLI.

For an explicit `agent-assembly/2` service, exercise Provider list/describe and
Node list/inspect using complete references returned by the selected service.
Require advertised methods and read authority; method discovery or Bearer alone
does not grant Node access. A published Node is a durable binding observation,
not current native readiness. Missing Node inspect must exit 4; missing storage
or permission must refuse, rather than falsely succeed with an empty catalog.
General capabilities discovery may succeed with profileCatalog=false; doctor
still diagnoses the Profile surface. Do not use that flag to gate Node reads.

With an existing authorized Node owner, exercise configuration describe/inspect,
apply a fixed complete change file and query the returned original operationRef.
Use the owner's observed configuration revision, not a Profile revision. Verify
same-key replay causes one effect, changed payload/revision conflict exits 5,
unknown exits 6 with no resend, and partial retains per-item outcomes. ACK-only
is not applied; restartRequired never restarts. If no operationRef was returned,
this release has no public request-key lookup: a separate inspect cannot prove
ownership or completion of the lost operation. Do not read private databases to
fill that product gap.

Fresh installed positive Node/configuration checks currently use real
Core/SQLite with a controlled owner/HTTP peer. The real optional Server v2
deployment has only Profile/registry read authority; its Node observations are
verified refusals, not production positive Node acceptance. Skills remain optional
instructions; source/frontmatter/bundle checks and readonly instruction reviews
do not establish successful model-agent task use.

The real-service scenarios own only temporary roots/processes. The TCP proxy
scenario commits exactly one create then loses the reply. Reading catalog facts
proves the data exists but does not itself resolve request ownership. There is
no public Profile outcome query yet; retain that gap instead of resending.

## Remaining gates

Production Directory/Invocation/material authority, actual native
capture/receipt/effect/Session owners, full cold recovery, lifecycle and
production installation/admission closure remain incomplete. Controlled Unit
records, scope/journal/configuration management and native write fences exist,
but their controlled evidence does not replace the missing production owners.
Prepare/connect/apply-profile/recover/stop/release/task/result CLI, the old
model/Server assembly migration and real Agent Skill use also remain incomplete.
The current core regression retains 3 inherited direction failures. The ledger
also contains an older targeted Server snapshot with 11 baseline failures;
that suite was not rerun by the Node observation slice. Do not call unrun scope
green. The installed client requires Python 3.10+; this source acceptance uses
Python 3.12, and real model behavior has not been tested.

Exact commands, logs, exit codes, versioned snapshots and known limits live in
`docs/implementation/agent-tools/status.md` and its evidence directory. Real
models and user services still require separate scoped authorization.

## Reproduce an installed-client exercise from source

```sh
/path/to/source-acceptance-venv/bin/python products/agent-tools/acceptance/install_use.py \
  --bundle /your/selected/bundle \
  --evidence /your/selected/new-install-evidence.json
```

Select a newly built bundle for the current source; do not silently reuse an old
release under the same version. The script verifies required assets/checksums and
never overwrites an existing evidence file. It installs the selected bundle wheel into a fresh temporary client
venv, verifies that backend packages are absent, and invokes its actual executable
against an owned temporary existing Server. It checks catalog actions, expected
failures, restart and cleanup. The manifest is deliberately catalog-only with
an absent Harness reference. It does not test Agent execution or models. Only
the service environment needs backend packages; the client environment does not.
Safe command outputs are recorded in the implementation evidence directory;
secrets, databases, temporary venv and owned service processes are cleaned up.

## Initialize local binary observations

From the installed wheel run `ordessa-agent init --json` without service config.
Use `--output` for a new caller-selected observation file. Check local scan scope,
command paths, missing/unavailable diagnostics and runtimeReady unknown. A script
fixture that writes a marker must not run during scan. The output cannot establish
a remote Server's availability. Linux filesystem and isolated-wheel tests cover
this slice; Windows PATHEXT behavior has not been exercised on a Windows host.
