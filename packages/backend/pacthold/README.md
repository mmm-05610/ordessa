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
pip install ./packages/pacthold        # from the monorepo root
pip install -e './packages/pacthold[dev]'   # with pytest
```

## Console script

`pacthold` — the governance CLI (`pacthold --help`).

## Tests

```bash
python -m pytest tests/     # from this directory
```
