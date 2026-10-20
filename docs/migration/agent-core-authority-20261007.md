# Agent/Profile authority and retained data — 2026-10-07

This note records the current direction against the user-designated source
baseline `3ada3ea5ab47abf09cc2ebc6b59238d95ed344c7`. The current checkout HEAD
`747673c48096da0943c38332beb3f95db2137352` is the policy/work-order checkpoint
used for C02; relative to the source baseline it adds six coordination/policy
documents and no source paths. It supersedes earlier target-layout statements
only where this note explicitly names a newer ruling. It is not a
product-completion or data-migration receipt.

Current authority and next work are indexed by
[`agent-core-engineering`](../implementation/agent-core-engineering/README.md).
The shared contract is the current implementation reference. Earlier public
wire proposals are historical; see
[`agent-tools/public-contract.md`](../implementation/agent-tools/public-contract.md).
The earlier Decision placement in 032 remains historical evidence; see
[`migration-map.md`](migration-map.md) and its current-authority update.

## Current Agent/Profile authority

- Pacthold `AgentServices` owns Profile catalog services, Agent node publication,
  configuration coordination, assembly, lifecycle, managed inputs, operations,
  and material operations. The services share the Environment's existing
  authority and operation records; the product must not create another catalog,
  operation ledger, lifecycle owner, or apply path.
- A Profile is configuration material. A Node is the core identity/binding, and
  a provider-owned Unit/Session remains provider state. Profile read or preview
  does not prove that a provider is installed, available, prepared, running, or
  configured.
- The Server and product are consumers of the public core surface. Historical
  wire method proposals do not establish that a method is registered in the
  current product. Current capability claims must follow the live public
  composition and provider/port evidence.
- Agent assembly and material operations require their real ports and observed
  owner receipts. Missing issuer, context, observation, configuration, input,
  or lifecycle support means that operation is unavailable or unknown; a test
  fixture does not advertise production capability.

## Legacy stores and identifiers

Old Profile and Agent submit databases are retained as user data. The current
path must not read or write those databases, implicitly open them as a fallback,
modify them, or delete them. Their schema and operation semantics are not
claimed to be equivalent to Pacthold's catalog or Environment records; no
automatic conversion is defined here. Existing on-disk names and identifiers
remain unchanged.

An explicit future conversion would require its own reviewed source/target
mapping, isolated test identity and data, conflict/rollback rules, and separate
authorization. No migration utility, conversion result, or user-data change is
claimed by this note.

## Current evidence boundary

The V00 record is a bounded offline checkout baseline, not full product
acceptance:

- Agent tests with current-root source paths: 263 passed, 1 failed, no skips.
  The remaining failure was a retirement-presence assertion: at V00 time,
  `plugins/profile/src/ordessa_profile` existed only as a cache directory with
  17 ignored `.pyc` files, no `.py` source, and no Git-tracked paths. C03 later
  removed only those files and empty directories; the affected check has not
  been rerun, so its post-cleanup result is UNKNOWN. The earlier 257 passed /
  7 failed results were setup trials and are superseded by this correctly
  sourced run.
- The targeted product assembly checks passed 29 tests. They do not establish
  that all Profile, Node, input, provider, lifecycle, or native operations are
  available in the shipped product.
- Direction/import isolation checks passed 16 and failed 25. At V00 time,
  21 retirement-presence cases reported `plugins/harness/src/ordessa_harness`,
  which contained only 107 ignored `.pyc` files (no `.py` source and no tracked
  paths); C03 later removed only those cache files and empty directories. The
  registry count of 8 versus 7 expected and import-first cases remain separate
  observed failures. No post-cleanup test was run and no assertion was changed.
- Independent DSH and Grok Build wheel checks each failed their fresh
  `pip check` because `pydantic-graph` was absent from the tested wheel closure.
  These failures are recorded in the V00 evidence and known-issues ledger.
- The tests do not establish real Harness behavior. The V00 environment reports
  native worker/sidecar/ACP resources absent; unavailable capabilities stay
  unavailable. No real model or user service was used.

Exact commands, raw outputs, and resource boundaries are in
[`V00 evidence`](../implementation/agent-core-engineering/evidence/V00/README.md).
This summary does not replace or upgrade those receipts.
