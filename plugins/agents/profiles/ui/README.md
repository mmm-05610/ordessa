# Agent Profile Catalog UI extensions

This directory contains two JavaScript extension workspaces, not the retired Python
Profile backend plugin:

- `api/` (`@ordessa/plugin-profile-api`, extension id `ordessa.profile-api`) defines
  the shared Profile Catalog contract and schema mirror.
- `frontend/` (`@ordessa/plugin-profile-frontend`, extension id
  `ordessa.profile-frontend`) consumes `WorkbenchToken` and `WirePortToken`, then
  contributes the Profile settings section through Workbench composition. Its client
  calls the Agent Profile Catalog wire methods and validates the published schema
  mirror before accepting catalog responses.

The Profile state authority remains `ordessa_agents` in
`packages/execution/agents`; these UI packages are consumers. The default Desktop
manifest is `apps/desktop/packaging/product/extensions.json`. Extension ids and wire
method names remain stable.

Typecheck each workspace from the repository root:

```sh
npm run typecheck --workspace @ordessa/plugin-profile-api
npm run typecheck --workspace @ordessa/plugin-profile-frontend
```

Tests are in each workspace's `tests/` directory and can be run with `npx vitest run
--root <workspace-path>`. Do not use the retired `pip install -e plugins/profile` or
`plugins/profile/tests` commands; there is no active Python Profile package at that path.
