# pacthold

Pacthold is the execution governance kernel and plugin SDK for coding
agents: work core, storage and migrations, execution contracts, extension
loader, service facade, resource contracts and the CLI.

Part of the Ordessa monorepo baseline (2026-09-25); migrated from the
historical `agent-box` repository (branch `work/hd002-bc-native`,
commit `a0b343e0`). The Python import path is `pacthold`. Compatibility
surfaces that intentionally keep their historical spelling: the
`agent_box.plugins` entry-point group, the `AGENT_BOX_HOME` /
`AGENTBOX_*` environment variables, the `~/.agent-box` data directory,
the `agent-box.db` database file, and the resource-contract ids
(e.g. `agent-box.skill@1`).

## Install

```bash
pip install ./packages/execution/kernel        # from the monorepo root
pip install -e './packages/execution/kernel[dev]'   # with pytest
```

## Console script

`pacthold` — the governance CLI (`pacthold --help`).

## Tests

```bash
python -m pytest tests/     # from this directory
```

## Nightly Agent extraction status

The sole Agent/Profile service implementation is now `ordessa_execution_agents` in `packages/execution/agents`. Pacthold retains the original Environment, CoreRegistry, store and SDK descriptors. The reserved `pacthold.agents` owner/ACL/storage IDs remain, while that Python import namespace has no alias. Shared Harness extraction and full acceptance remain partial; see the repository `docs/README.md` and `docs/implementation/nightly/status.md`.
