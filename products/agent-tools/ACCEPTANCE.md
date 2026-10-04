# Current acceptance: Profile and public foundations

This is a partial implementation. Runnable Agent nodes, native tasks and task
result queries have not been delivered. Installation or 240 passing tests must
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
ledger rather than summing historical runs. The current frozen snapshot has:

| Category | Tests | Evidence boundary |
| --- | ---: | --- |
| Client and isolated wheel | 49 | Client HTTP fixtures and installed entrypoint |
| Bundle | 6 | Asset integrity, not Agent use |
| Thin wire contract | 16 | Real temporary SQLite, no HTTP service |
| Registry lifecycle | 17 | Controlled owner/registry doubles |
| Profile core | 32 | Real isolated SQLite |
| Directory binding | 20 | Temporary Workspace DB, filesystem facts and controlled authority |
| Operation store | 34 | Real SQLite, concurrency and self-owned crash processes |
| Invocation authority | 53 | Real durable claim, controlled authority/current-state ports |
| Deployment boundary | 11 | Isolated existing Server composition and owned paths |
| Server plus CLI | 2 | Real isolated HTTP service, subprocess CLI and TCP response loss |

For the installed client, configure an explicit service alias and tokenEnv using
[README](README.md). Exercise `doctor`, `profiles list`, create/edit with actual
manifest references and CAS, and read an old returned full ProfileRef after edit.
A conflicting revision must produce exit 5, authorization refusal exit 3, and
unknown write outcome exit 6 without retries. Preview currently refuses readiness
with exit 4; doctor must report nodes=false and managedInput=false.

The real-service scenarios own only temporary roots/processes. The TCP proxy
scenario commits exactly one create then loses the reply. Reading catalog facts
proves the data exists but does not itself resolve request ownership. There is
no public Profile outcome query yet; retain that gap instead of resending.

## Remaining gates

Production Directory/Invocation authority and provider admission, a real Harness
unit reservation, owner-issued shared configuration scope, versioned Unit/Session
journal migration, native correlation/query, configuration/material routing,
actual lease/transport fencing, managed session/input reservation, node and task
CLI commands, and real Agent Skill use remain unverified or unimplemented.
The core regression retains 3 inherited direction failures; the targeted Server
regression retains 11 identical fixed-baseline failures. Do not hide them or call
the whole regression green. Python 3.9 and real model behavior were not tested.

Exact commands, logs, exit codes, versioned snapshots and known limits live in
`docs/implementation/agent-tools/status.md` and its evidence directory. Real
models and user services still require separate scoped authorization.

## Reproduce an installed-client exercise from source

```sh
/path/to/source-acceptance-venv/bin/python products/agent-tools/acceptance/install_use.py
```

This script installs the existing bundle wheel into a fresh temporary client
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
