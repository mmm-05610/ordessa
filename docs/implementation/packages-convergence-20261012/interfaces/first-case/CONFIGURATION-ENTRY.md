# First case: configuration entry and startup boundary

Status: the default-product CLI's closed JSON `--user-config` path is wired to
`default_runtime(engineering_options=...)`. Root reports that the actual CLI
started and served HTTP, persisted the requirements and DID documents, and
read both back byte-for-byte equal. A Work start was correctly refused with
`WORK_WAIT_AUTHORITY_UNAVAILABLE`; this is not a claim of Pi or full Work
readiness. The original copy was mistakenly placed at
`docs/interfaces/first-case/CONFIGURATION-ENTRY.md`; it was moved here without
changing bytes (both locations had SHA-256
`da0a97d1f9a8567cb2e764fec844f1fa839a9d20b28f20e20b09dd60acc91887` at the
move boundary).

## First-case bootstrap file

Use a fresh, explicit library path selected for this case. The first-stage JSON
contains only Engineering library creation/configuration; it does not claim
that Profile, Environment, method, proposal, Unit, or Pi execution ports have
been produced:

```json
{
  "version": 1,
  "engineering": {
    "libraryPath": "/tmp/ordessa-first-user-case-20261013/work/engineering.sqlite",
    "libraryId": "first-user-word-count",
    "realm": "first-user-word-count",
    "project": "first-user-word-count",
    "schemaVersion": 15,
    "createLibrary": true,
    "machineCapabilities": ["engineering.capabilities"]
  }
}
```

Start the ordinary default product with `--user-config <absolute-json-path>`
and the case's explicit `--data-root`. The config file is strict UTF-8 JSON,
limited to 1 MiB, and rejects duplicate JSON keys, unknown fields, unsupported
schemas, relative library paths, implicit creation, and duplicate machine
capabilities. The path in this example must be new; the original Engineering
selector refuses `createLibrary: true` if the file already exists, so this
command does not migrate or overwrite an existing database. The machine
capability list is explicit and is passed unchanged through the original
Engineering selector; it is not augmented by the loader.

`--user-config` cannot be combined with existing Engineering, native, sidecar,
plugin-root, or mount options. In particular, all native harness, adapter,
continuation, installed-artifact, additional-adapter, Pi-profile-bridge and
profile-harness options are refused before startup. The normal product
`default_runtime` receives the original `engineering_options` shape. This
bootstrap creates/selects no Pi owner and performs no model call.

## Separate persisted-selection reader

`composition.product_user_configuration.resolve_product_user_configuration`
is a later-stage reader, distinct from the `--user-config` bootstrap file. It
accepts a decoded object or UTF-8 JSON text/bytes (maximum 1 MiB). Its root
object has exactly `version`, `piSelection`, and `engineering`; version is
integer `1`. Unknown keys are refused, so callbacks, function paths,
executable paths, token values, and role grants cannot enter through this
document.

`piSelection` names an existing immutable Profile revision, existing
Environment identity/provider/isolation/sharing, an existing Profile model
declaration id, and its provider/model selection. The reader obtains the
revision through ProfileService and inspects the Environment through the
selected EnvironmentManager. The model catalogue must be supplied by the
actual selected owner. Executable locations and the credential-source
reference are a separate closed `trusted_launch` input from trusted product
policy; this mapping is not currently produced by default product startup.
The reader never opens the credential source or executable paths.

`engineering` names one ProposalRef, the complete configured set of review
request phases in the selected method, and optional exact material revision /
prior CommandKey provenance pairs. The reader resolves the selected Proposal
and every phase through the original SQLiteReviewBindings before returning.
This means those Proposal, workflow, and material revisions must already exist;
the reader does not manufacture future refs. A material CommandKey is only
typed provenance configuration here. The original
SQLiteReviewAuthorshipSource verifies the completed journal record and exact
returned artifact when an actual ReviewPlan is evaluated.

## Remaining boundary

The first-case startup and material persistence do not create real Profile,
Environment, Proposal, phase, author, or reviewer references, and do not bind a
Pi owner. Work therefore continues to refuse until its original authority and
selected Unit inputs are available. Bootstrap any later values only through
their original public owner operations; do not use placeholder refs, a second
Runtime, a synthetic Environment, or permissive callbacks.
