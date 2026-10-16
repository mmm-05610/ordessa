# Agent execution mechanism

The sole Agent/Profile implementation is `ordessa_execution_agents`, with its
public entry point at `ordessa_units.public`. Profile, unit,
execution and Harness-record modules live under this distribution's source
tree. Pacthold retains the original Environment, Store, CoreRegistry and SDK
admission descriptor types; execution services use those same objects and
authorities. The `pacthold.agents` Python import root is retired without an
alias. Its reserved owner, ACL, fingerprint, storage, wire and persisted
identifiers remain unchanged.

`OperationJournal` and `UnitRecords` now live at
`ordessa_units.records` in this same distribution. The
former `ordessa-harness-records` distribution and `ordessa_harness_records`
import root are retired. The cutover map records the source revision, original
file digests and 39 switched consumer files in a 49-project workspace
inventory: [records cutover map](../../../docs/implementation/nightly/evidence/W06/records-cutover-map.json).
The migration did not change database table identities or access user
databases. The preserved pre-restructure README is indexed in the
[archive](../../../docs/archive/pre-restructure/README.md).

The records move does not finish shared Harness contracts or materialization.
The Managed Codex codec/service split remains pending, and real native use and
cold recovery have not been verified. W06 remains PARTIAL. Server's
`state/agent-owner/operations.sqlite` and Agent Tools'
`plugins/profile/native-configuration.sqlite` are distinct composition paths;
the records package does not choose, merge or provision either path.

Install through `python-workspace.json` from this same worktree, then run
`.venv-nightly/bin/python -m pytest --asyncio-mode=auto -q
packages/execution/agents/tests`. Selected Agent capability requires Python
>=3.10; bare Server remains >=3.9 and needs explicit agents/decision extras for
those adapters. Installation does not migrate user databases.
