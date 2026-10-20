# Harness availability public carrier

The Workbench Interfaces layer owns this brand-neutral availability contract and its pure absence/report helpers. Desktop and extension consumers use `@ordessa/harness-contracts` and its explicit exports. The package name, extension id and shared foundation Token identity are retained. `contract.ts` reuses the single opaque Token from the foundation carrier; it creates no provider, registry, execution state or admission authority.

This carrier does not own Python Harness providers or Agent state. Those contracts belong to `ordessa_execution_agents.harness.definitions`, and runtime providers/records belong to Agents and independent brand plugins. Controlled fixture helpers model availability only and cannot prove an installed native Harness or grant execution. The former `plugins/harness/contracts` source entry has been retired.
