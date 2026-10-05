---
name: use-external-agent
description: Assess whether the standalone Agent Tools CLI can run a task through an external Agent. Use for task execution requests, not Profile editing or node administration.
---

For first-time local setup, run `ordessa-agent init --json`. It scans absolute
PATH entries without executing commands, installing packages or changing global
settings. `init --output harness-observation.json --json` saves a new observation
file and refuses overwrite. Found executables are local clues: runtimeReady is
unknown and trusted provider admission is not checked. No candidates gives exit 4.
The caller machine may differ from the service host; a local missing executable
does not prove a remote service lacks that Harness. Use service `doctor` separately. Local initialization is optional for remote
service use; exit 4 from local discovery does not prevent remote Profile operations.

Use the user's selected existing service and protected config with
`ordessa-agent capabilities --config services.json --service local --json`.
This release implements discovery, Profile data, published Node observation and
owner configuration commands, but has no task submission/result CLI. Preserve
the service's observed supports; the optional deployment currently has
`supports.nodes=false` and `supports.managedInput=false`. Even if a different
compatible service advertises task support, this installed CLI still has no task
commands. Explain that limitation and stop before attempting task submission
or native input. A separately authorized Node preparation can use
manage-external-agent; it does not provide the missing task or result commands.
Do not invent run/watch/result commands, use an older Agent endpoint as a
substitute, silently open a native client, or start a daemon.

The caller can be a human, Agent, script, or other tool; this Skill is guidance,
not authorization or a CLI prerequisite. Do not modify the caller's global
configuration or assume a particular Agent host.

If the user also asks to inspect a Profile, `profiles list`, `profiles entry` and
`profiles show` are available; use their `--help` for parameters. Return a full
fixed ProfileRef and clearly distinguish stored recipe data from a prepared
node, native session, accepted input, or completed task. `nodes list/inspect`
can observe an already published Node when that public method and read authority
are available; its `runtimeVerified=false` does not prove a live Agent. A successful
doctor only establishes the reported supported surface. Preview remains unresolved.

Preserve any existing request/operation identity supplied by the user. A lost
connection is missing evidence, not proof of rejection or cancellation. Never
resend an unknown input or generate a new request-id to evade its uncertainty.
Exit 7 is an observation timeout; it does not mean the remote task stopped.
No model invocation is authorized merely by reading this Skill or discovery.
