# Ordessa interfaces

System-access strict envelope schemas, exact reference values and offline owner-schema admission. Real owner business schema bindings, server/client adapters and generated TS contracts are pending.

This is an actual Python distribution in python-workspace.json, installed from this source. Three-wheel verification and controlled tests are recorded in docs/implementation/nightly/status.md. Package existence and controlled tests do not prove full runtime integration.


## Current Server identity mechanism (partial W10)

`system_access/server/authentication.py` is a neutral single-process mechanism selected once by ServerRuntime. It authenticates the existing instance bearer as a machine, checks exact scope/capability grants and serializes trusted revocation with synchronous admitted work. It owns no credential store or business database. Default Server grants are empty; approval/consent capabilities cannot be granted to this machine path. The issuer marker prevents accidental JSON construction, not hostile code already trusted inside the process.

Original local owner ACLs remain; `guard_legacy` requires an explicit local identity mapping. Async sending rechecks per frame, while async authenticated handlers require a task-aware lease and are currently refused. These controls do not establish human identity, a production operation catalog, project ownership or full product acceptance. See [W10 evidence](../../docs/implementation/nightly/evidence/W10/README.md).

## Generic capability host and CLI

`ordessa-interfaces-contracts` is an independent standard-library distribution.
Owners publish capability descriptors and handlers through `ordessa.capabilities`;
the interface host imports no owner implementation or application assembly.

`system_access/{registry,discovery,operations,queries,projections,assembly}.py`
implement the generic host. `channels/cli.py` and `channels/mcp.py` receive an
application-built host. Environment-specific host modules and temporary
`capability_host` / `cli_generic` paths have been removed without aliases.

The installed `ordessa` script belongs to `apps/server` and calls
`ordessa_server.entrypoints.cli:main`. Application composition supplies the local
environment provider, OS principal and owner services. `--state DIR` or
`ORDESSA_STATE` chooses the local development registry. Resource/use request and
alias ownership stays in environments; the application adds no runtime journal.

The CLI supports `list`, `describe <operation-id>`,
`call <operation-id> --input <file|->`, and descriptor-declared shortcuts including
`environments`. JSON mode returns one `agent-tools/1` envelope with
`operationRef` and `evidenceRefs`; generic error codes replace environment-specific
host errors. Human mode uses generic JSON projections, while process operations
emit their captured stdout/stderr and propagate child exit codes. Output is
bounded; this does not claim live streaming.

Local resource stop/delete refuse and preserve files. OpenShell remains unavailable
without explicit authenticated provider composition. No model or service starts
are needed for controlled acceptance. See [ACCEPTANCE.md](ACCEPTANCE.md) and
[assertion migration](../../docs/implementation/packages-convergence-20261019/TYPED-HOST-RETIREMENT.md).
