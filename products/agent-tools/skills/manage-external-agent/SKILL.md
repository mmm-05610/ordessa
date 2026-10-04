---
name: manage-external-agent
description: Assess supported Agent Tools node management for requests to inspect, configure, apply a Profile, stop, or recover an external Agent. Do not use for editing the Profile catalog.
---

For first-time local setup, run `ordessa-agent init --json`. It scans absolute
PATH entries without executing commands, installing packages or changing global
settings. `init --output harness-observation.json --json` saves a new observation
file and refuses overwrite. Found executables are local clues: runtimeReady is
unknown and trusted provider admission is not checked. No candidates gives exit 4.
The caller machine may differ from the service host; a local missing executable
does not prove a remote service lacks that Harness. Use service `doctor` separately.

Run `ordessa-agent capabilities --config services.json --service local --json`
against the user's selected existing service. This release reports
`supports.nodes=false` and `supports.managedInput=false`; node management is
unavailable. Report that limitation and stop before attempting management.
There are no node inspect/apply/configure/stop/recover/reconcile CLI actions in
this release. Do not invent them, import a service's private implementation, or
switch to old Agent/Profile methods to obtain an apparent success.

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
each require their own authoritative evidence; this release cannot produce it.
