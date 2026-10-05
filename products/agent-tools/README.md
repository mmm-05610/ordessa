# Agent Tools 0.1.0a2

Independent CLI and three optional Skills for humans, Agents, scripts and tools.
The implemented slice is discovery and the core-owned Profile catalog:
list/read/create/edit/clone/rename/archive/restore, immutable history refs, and
explicitly unresolved preview. It does not yet prepare Agent nodes, submit tasks,
apply configuration, stop or recover nodes. Three Skill files do not make those
capabilities available. No real model calls were made for this slice.

The client consumes `wire/1` and negotiates the generated `agent-assembly/1`
schema. Existing `profiles.v2.*` or old Agent methods are not fallback paths.
Doctor exit 0 establishes Profile catalog support; its result explicitly shows
`nodes=false` and `managedInput=false`. It does not establish a runnable Agent.

## Install the CLI

From the source tree, into a user-selected virtual environment:

```sh
python3.12 -m venv ./agent-tools-venv
./agent-tools-venv/bin/python -m pip install ./products/agent-tools
./agent-tools-venv/bin/ordessa-agent --help
```

The CLI requires Python 3.10+ and has no runtime package dependencies. It does
not import or bundle Server, Harness, or Pacthold, install Skills globally, or
launch a service. The optional [deployment source](deployment/composition.py)
uses the existing Server with an explicitly supplied fingerprint capability and
absolute isolated data root. It remains outside the CLI wheel. It is not a
complete headless Agent runtime or an implicit daemon command.

## Initialize local discovery

```sh
ordessa-agent init --json
ordessa-agent init --output harness-observation.json --json
```

No service configuration or token is required. Initialization scans this caller
machine's absolute PATH entries for command names published by Harness. It does
not execute binaries, run version probes, install packages, start services or
write global Agent configuration. Relative/empty PATH entries are ignored and
reported. Multiple matching paths remain in search order; no binary is selected
automatically. Use `--path` to explicitly choose a search PATH. The reviewed catalog currently
covers eight families, not every installed Agent. Local discovery is optional
when using a remote service; exit 4 does not block remote Profile operations.
If `scanCompleteForSearchedEntries` is false, inspect the retained scan issues
even when candidates were found and the command returned exit 0.

Each result separates executableFound from installedArtifact/providerAdmission
notChecked and runtimeReady unknown. A local binary does not establish a remote
Server's installation or capabilities. If none is confirmed, exit 4 and inspect
diagnostics; an inaccessible path is scanUnavailable. The optional report is an
observation snapshot, not runtime configuration, and must be a new file.

## Select an existing service

Create `services.json` with an alias and an environment-variable reference:

```json
{"services":{"local":{"endpoint":"http://127.0.0.1:8931","tokenEnv":"ORDESSA_AGENT_TOKEN"}}}
```

```sh
chmod 600 services.json
./agent-tools-venv/bin/ordessa-agent doctor --config services.json --service local --json
./agent-tools-venv/bin/ordessa-agent capabilities --config services.json --service local --json
```

Provide the token through your existing secret facility under the named
variable. Never put it in the configuration, argv, Profile manifest, or output.
Configuration must be a regular non-symlink file without group/other write access.
HTTP requires a loopback IP literal; other endpoints require HTTPS with normal
certificate verification. Userinfo, paths, queries and fragments in the endpoint
are refused. Redirects, ambient proxies and automatic retries are disabled. The
service must already be running under its authorized owner.

## Create and edit a Profile

The following examples call an installed `ordessa-agent` on PATH. Append the
explicit service options on every command. Discover the trusted environment
namespace with `capabilities`, then write a manifest JSON file. The catalog
currently stores opaque leaf references; this slice has no Harness/resource/
configuration-kind discovery or provider validation. Supply actual references
from your authorized installation instead of inventing a runnable definition.

```sh
ordessa-agent profiles create --file manifest.json --profile-id reviewer --name Reviewer \
  --request-id profile-create-1 --config services.json --service local --json
ordessa-agent profiles list --config services.json --service local --json
ordessa-agent profiles entry reviewer --config services.json --service local --json
```

Save returned `data.currentManifestRef` as `profile-ref.json` and retain returned
`data.catalogRevision` for editing. A ref has this complete shape:

```json
{"environmentNamespace":"your-authorized-environment","profileId":"reviewer","manifestRevision":1,"contentDigest":"sha256:actual-64-hex-digest"}
```

This shape example is not a substitute for a service-returned ref.

```sh
ordessa-agent profiles show @profile-ref.json --config services.json --service local --json
ordessa-agent profiles edit reviewer --file revised-manifest.json \
  --expected-catalog-revision 1 --base-manifest @profile-ref.json --request-id profile-edit-1 \
  --config services.json --service local --json
```

Use the actual revision read from the service instead of assuming 1. Edit
captures both catalog CAS and the complete base manifest ref. Metadata operations
have separate CAS; rename/archive do not change immutable manifest content.
Retaining an old ref lets `profiles show @old-profile-ref.json` read historical
content after an edit. History is not overwritten or automatically applied to a
node. Clone, rename, archive and restore each have dedicated commands; read their
action's `--help` for exact parameters.

```sh
ordessa-agent profiles preview @profile-ref.json --config services.json --service local --json
```

Preview currently returns exit 4, `ready=false`, `referenceCoverage=unknown` and
providerUnavailable. It is a refused readiness guarantee, not native
configuration verification or an instruction to start a process.

## Interpret evidence and failures

JSON uses the stable `agent-tools/1` envelope with requestId, serviceRef, status,
data, evidence and error. Read status and evidence together with the exit code:

| Exit | Meaning |
|---|---|
| 0 | A supported catalog/discovery operation completed |
| 2 | Invalid parameters, local configuration or schema |
| 3 | Authentication or authorization refused |
| 4 | Unsupported version/capability, unavailable service, invalid read response, or unresolved preview |
| 5 | Revision, request identity or target precondition conflict |
| 6 | Write outcome unknown; retain request identity and seek authoritative evidence |
| 7 | Read observation timeout; not remote cancellation |

A stale edit produces exit 5 instead of overwriting another writer. Re-read
`profiles entry` and the current manifest, review the change, and use the new CAS
values for a separately authorized edit. Do not change a spent request-id's
payload or revision preconditions.

A disconnect after sending a write produces unknown/exit 6 and does not resend.
Preserve the exact request-id and body. A catalog read may reveal current data
but does not prove which attempt caused it. This slice has no public per-operation
Profile outcome query/reconcile command: wait for authoritative service evidence
or that API before resolving uncertainty. Do not switch services, mint a new
request-id, or repeat a mutation to make an unknown result disappear. No exit
means a model task has completed.

## Build the local distribution

Use the source implementation environment with Pacthold's public core contract
and setuptools/wheel installed. Core is a build-time schema authority only;
the installed client remains independent.

```sh
python products/agent-tools/packaging/generate_schema.py
python products/agent-tools/packaging/generate_harness_catalog.py
python products/agent-tools/packaging/build_bundle.py --output products/agent-tools/dist/bundle-0.1.0a2
```

The first command checks the client mirror. To deliberately regenerate it after
a reviewed core contract change, use `generate_schema.py --write`. Bundle
creation refuses an existing output directory. It contains `cli/*.whl`, three
`skills/*/SKILL.md` directories, `schema.json`, `harness_commands.json`, this README,
[acceptance steps](ACCEPTANCE.md) and `SHA256SUMS`.
Generated assets are ignored by Git. Add `--include-deployment-source` only when
you want the optional composition source copied separately to
`deployment-source/`; it never enters the wheel or starts a service.

From a bundle, after verifying hashes:

```sh
cd /path/to/bundle-0.1.0a2
sha256sum --check SHA256SUMS
/path/to/agent-tools-venv/bin/python -m pip install --no-index --no-deps cli/ordessa_agent_tools-0.1.0a2-py3-none-any.whl
```

Skill installation is optional and host-specific. For project-local copies,
choose a directory yourself and copy `skills/configure-agent-profile`,
`skills/use-external-agent`, and `skills/manage-external-agent` into it. Configure
that host to read the selected directory using its documented mechanism. The
bundle has no global installer and does not change caller Agent settings.

## Verify this slice

```sh
python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests
```

Client contract tests use temporary standard-library HTTPServer fixtures over
real loopback HTTP; they do not substitute for product Server acceptance.
Distribution tests build a wheel, inspect imports/assets, install it into a
fresh isolated venv, verify backend packages are absent, and exercise its entrypoint.
Integration tests separately exercise the composed isolated existing Server and
core catalog; report those counts separately. Missing core/build resources fail
instead of silently skipping. Node lifecycle, DirectoryBinding, leaf provider
routing/material preparation, native input, stop/recovery and real models remain
outside the completed slice.
