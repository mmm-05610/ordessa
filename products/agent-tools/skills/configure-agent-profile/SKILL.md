---
name: configure-agent-profile
description: Create, inspect, clone, or edit an Agent Profile using the standalone ordessa-agent CLI. Use for Profile catalog work; applying a Profile to a running node is a separate management task.
---

For first-time local setup, run `ordessa-agent init --json`. It scans absolute
PATH entries without executing commands, installing packages or changing global
settings. `init --output harness-observation.json --json` saves a new observation
file and refuses overwrite. Found executables are local clues: runtimeReady is
unknown and trusted provider admission is not checked. No candidates gives exit 4.
The caller machine may differ from the service host; a local missing executable
does not prove a remote service lacks that Harness. Use service `doctor` separately. Local initialization is optional for remote
service use; exit 4 from local discovery does not prevent remote Profile operations.

Use an already installed `ordessa-agent` and a user-selected protected service
configuration. The CLI also works directly for humans and scripts; loading this
Skill is optional. Do not install into global Agent settings or start a service.

Run `ordessa-agent doctor --config services.json --service local --json` first.
Require matching core schema and `data.coreAgent.supports.profileCatalog=true`.
Profile catalog success does not imply a runnable Agent. `nodes=false` and
`managedInput=false` do not prevent separately advertised publication/configuration
reads; check the requested method and its authority. This release still has no
task input, apply-profile, stop, or recover CLI. For an explicitly authorized
prepare through the public service, follow manage-external-agent; catalog edits
do not prepare or configure an existing Node.

Use `ordessa-agent profiles --help` and the action's `--help` for current syntax.
List with `profiles list`; inspect metadata with `profiles entry PROFILE_ID`.
Read a fixed manifest with `profiles show @profile-ref.json`. A complete ProfileRef
includes environmentNamespace, profileId, manifestRevision, and contentDigest.
Keep catalogRevision distinct from manifestRevision.

Create from a manifest JSON file using `profiles create --file manifest.json
--profile-id reviewer --name Reviewer --request-id UNIQUE_ID`. Edit with
`profiles edit reviewer --file manifest.json --expected-catalog-revision REVISION
--base-manifest @profile-ref.json --request-id UNIQUE_ID`. Append the same explicit
`--config`, `--service`, and `--json` options to each invocation. Clone, rename,
archive and restore have dedicated actions; consult their help rather than
guessing argument names. Mutations must be within the user's authorized scope.

Preserve exact opaque leaf references and schema-controlled values supplied by
the caller. If the service advertises `agents.providers.list/describe`, use
`ordessa-agent providers list` and `providers describe @definition-ref.json` to
observe admitted providers. This does not validate every resource/configuration
declaration or prove runtime readiness. Do not invent model names, resource refs, or native
configuration. Manifests never contain plaintext credentials; use an existing
SecretRef. Tokens are supplied only by the configuration's tokenEnv reference.

Return the catalog entry and fixed currentManifestRef. Editing creates a version;
it never applies it to a running node. `profiles preview @profile-ref.json` returns
exit 4 with ready=false and referenceCoverage=unknown until providers are present;
report this limitation rather than calling the Profile runnable.

Read both the JSON status and exit code. Conflict exit 5 requires re-reading the
catalog entry and base ref before the user-authorized edit is reconsidered.
Unknown exit 6 is never permission to resend or change request-id. Retain the
request identity and report the missing evidence; there is no automatic mutation
recovery command in this release. An unchanged input may reuse its request-id only
when deliberately invoking the same operation under the documented service
idempotency contract. Do not reuse an id with a changed payload or CAS precondition.
