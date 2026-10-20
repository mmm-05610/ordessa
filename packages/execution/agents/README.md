# Agent execution mechanism

The sole Agent/Profile mechanism is `ordessa_execution_agents`; its public
Profile surface is `ordessa_execution_agents.public`. Profile and Harness
mechanism modules live in this distribution; Unit composition and run records
live in `ordessa_units`. Pacthold retains the original Environment, Store,
CoreRegistry and SDK admission descriptor types; execution services use those
same objects and authorities. The `pacthold.agents` Python import root is
retired without an alias. Its reserved owner, ACL, fingerprint, storage, wire
and persisted identifiers remain unchanged.

This distribution does not import or depend on `ordessa_environments`. The
environment process channel that binds an environment `ProcessHandle` to this
package's `ProcessChannel` contract lives at
`ordessa_units.sessions.environment_channel`; only the Unit composition layer
knows both owners.

`OperationJournal` and `UnitRecords` now live at
`ordessa_units.records` in the `ordessa_units` distribution. The
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
packages/execution/agents/tests`. This distribution requires Python >=3.12;
consumers keep their own declared floors. Installation does not migrate user
databases.
