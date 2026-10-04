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
does not prove a remote service lacks that Harness. Use service `doctor` separately.

Use the user's selected existing service and protected config with
`ordessa-agent capabilities --config services.json --service local --json`.
This release implements discovery and the Profile catalog only. It reports
`supports.nodes=false` and `supports.managedInput=false`. Explain that task
execution is unavailable and stop before attempting a prepare or send action.
Do not invent run/watch/result commands, use an older Agent endpoint as a
substitute, silently open a native client, or start a daemon.

The caller can be a human, Agent, script, or other tool; this Skill is guidance,
not authorization or a CLI prerequisite. Do not modify the caller's global
configuration or assume a particular Agent host.

If the user also asks to inspect a Profile, `profiles list`, `profiles entry` and
`profiles show` are available; use their `--help` for parameters. Return a full
fixed ProfileRef and clearly distinguish stored recipe data from a prepared
node, native session, accepted input, or completed task. A successful doctor
only establishes the supported catalog surface. Preview remains unresolved.

Preserve any existing request/operation identity supplied by the user. A lost
connection is missing evidence, not proof of rejection or cancellation. Never
resend an unknown input or generate a new request-id to evade its uncertainty.
Exit 7 is an observation timeout; it does not mean the remote task stopped.
No model invocation is authorized merely by reading this Skill or discovery.
