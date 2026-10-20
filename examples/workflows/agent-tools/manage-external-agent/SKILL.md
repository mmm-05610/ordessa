---
name: manage-external-agent
description: Prepare Agent Nodes from fixed public requests, inspect published Agent Nodes and read, change, or reconcile owner configuration through the standalone ordessa-agent CLI. Also assess unavailable lifecycle actions; Profile catalog editing is separate.
---

For first-time local setup, run `ordessa-agent init --json`. It scans absolute
PATH entries without executing commands, installing packages or changing global
settings. `init --output harness-observation.json --json` saves a new observation
file and refuses overwrite. Found executables are local clues: runtimeReady is
unknown and trusted provider admission is not checked. No candidates gives exit 4.
The caller machine may differ from the service host; a local missing executable
does not prove a remote service lacks that Harness. Use service `doctor` separately. Local initialization is optional for remote
service use; exit 4 from local discovery does not prevent remote Profile operations.

Run `ordessa-agent capabilities --config services.json --service local --json`
against the user's selected existing service. Require a matching generated core
schema and the requested entry in `data.coreAgent.supportedMethods` for the
explicit `agent-assembly/3` contract. Discovery grants no authority. Follow each
method's permission result; do not use `supports.nodes=false` or
`configurationManagement=false` to block an advertised pure read. The latter
reflects write authority composition, not read permission.

Use `ordessa-agent nodes --help` for the installed command surface. Append the
same `--config services.json --service local --json` to every invocation below:

```sh
ordessa-agent nodes prepare --file preparation.json
ordessa-agent nodes query-preparation ORIGINAL_REQUEST_ID
ordessa-agent nodes list
ordessa-agent nodes inspect @node-ref.json
ordessa-agent nodes configuration describe @node-ref.json
ordessa-agent nodes configuration inspect @node-ref.json
ordessa-agent nodes configuration apply @node-ref.json --file change.json
ordessa-agent nodes configuration query @node-ref.json ORIGINAL_OPERATION_REF
```

NodeRef has exactly environmentNamespace, instanceId and positive integer
generation; preserve the complete identity returned by the selected service.
Node inspect reads durable publication references, not current native state.
Missing publication returns exit 4. `nodePublicationObserved` and a provider
registry entry do not establish ready or execution permission.

For an explicitly authorized prepare, use a bounded file with exactly requestId,
profileRef, context and options. Use the selected service's complete ProfileRef
and authorized public context references; never supply host paths, commands,
private root facts or plaintext credentials. Do not invent leaf options. Require
advertised agents.nodes.prepare and nodePreparation=true, then obey the actual
authorization result. The default catalog service does not compose preparation.

Only a validated published operation establishes nodePublished=true; save its
full NodeRef and operationRef. runtimeVerified remains false. reserved/running/
unknown, lost receipts and malformed responses exit 6 with no automatic retry.
Use nodes query-preparation with the original requestId in the same selected
service and authenticated realm. This observes only original claimed steps and
may record their confirmation; it never dispatches missing steps or publishes a
Node. It can recover a published original after a lost operationRef. Running or
unknown remains exit 6; do not automatically continue prepare. Missing operation
exits 4, does not prove no effects occurred, and does not authorize a new key.
Do not substitute configuration query, direct database access or a replacement.
Publication does not establish native task execution or current readiness.

Configuration describe reads supported kinds/actions/scope/modes. Configuration
inspect returns the owner's actual snapshot, sourceRevision and explicit unknown
items. Do not fill unknowns from Profile data or assume every native field is
enumerable. A real snapshot remains separate from an authorized mutation.

For an authorized apply, use a bounded change JSON containing exactly requestId,
expectedConfigurationRevision, declarations and applicationPolicy. The version
is the observed owner's native scope revision, never catalog/manifest revision.
Declarations use declarationId/configurationKind/schemaVersion/action/requirement
and optional payload/resourceRefs, according to the advertised schema. Keep
allowDeferred and allowRestart false unless the user explicitly selects otherwise;
changing a policy never grants native permission. Preserve existing SecretRef
identities, and keep plaintext secrets out of change files and output.

Report itemResults and overallOutcome. `allDeclarationsApplied=true` requires
the confirmed core result; partial can include actual applied items, and does not
mean zero effect. restartRequired is pending, never permission to restart;
deferred/unknown/partial may exit 6. Conflict exit 5 requires new authoritative
observation before reconsidering a separately authorized change.

For an unknown change with an original operationRef, configuration query
reconciles that same operation. It can record evidence or finish publication;
it is not an inert log read and never sends a new change. Without operationRef,
this release has no public configuration lookup by request key: retain the original requestId
and report the recovery gap. Do not read the service database or generate a new
requestId to evade uncertainty.

Connect, apply-profile, recover, stop, release and task/result CLI actions
are still unavailable. Report the precise missing action without substituting
older endpoints, private modules, direct native clients or a daemon.

Profile catalog editing is a separate operation. Catalog list/read/create/edit,
clone/rename/archive/restore do not configure or stop an existing node. Do not
edit a Profile as a substitute for applying it to the target. Never treat a
template model or settings value as the runtime configuration owner's observed
truth, or write native configuration files directly.

Discovery and this Skill grant no management authority. Respect the user's exact
scope; do not restart services, mutate user databases, install global Agent
configuration, approve native callbacks, or invoke a model to test recovery.
Skill use is optional for humans, scripts and Agents using the same CLI.

If an earlier operation is unknown, retain its canonical identity and explain
what evidence is missing. Do not retry, change request-id, prepare a replacement
node, or claim the node is stopped because a client disconnected. Cancellation,
confirmed stop, recovered native history, and successful Profile application
each require their own authoritative evidence. Publication/configuration evidence
does not prove these unimplemented lifecycle or task outcomes.


## Reading operation metadata

When the caller needs the durable metadata of an existing operation, use:

`ordessa-agent operations read <operationRef> --config … --service … --json`

只读六字段元数据，不返回正文，不推进/恢复/重发；`hasResult` 不等于任务完成.
