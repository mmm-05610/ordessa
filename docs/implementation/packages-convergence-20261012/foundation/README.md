# Foundation convergence checkpoint · 2026-10-12

## Authorization and coordination

The user authorized publishing verified development checkpoints to the existing
`codex/nightly-restructure-20261009` branch. Foundation's Sol is the sole Git
operator. This does not authorize a `main` merge, force push, reset, remote
branch deletion, history rewrite, or publication of sensitive or unattributed
files. Sol coordinates, decomposes work, reviews contracts and integrates;
multiple Luna agents execute ordinary source, documentation and test changes.
Tests, installs and builds remain serially scheduled by Sol. This checkpoint
records authorization; it does not claim that a commit or push has happened.

## Accepted ownership and public contracts

The accepted engineering and module-boundary standard is
[engineering-standard.md](../../../standards/engineering-standard.md), Library
revision 4, exactly 54,161 bytes, SHA-256
`c4602cff1d219225cab13a8d8e09c136473e6020700d16e17230df59e2be5e89`.
Machine-readable dependency rules are in
[package-boundaries.json](../../../../tooling/checks/package-boundaries.json).

`ordessa_infrastructure` owns technical identifiers, discovery, encoding,
database, filesystem, process and security facilities. Consumers retain their
business schema, migration policy, transaction authority and resource lifecycle.
The published SQLite connection API validates explicit configuration and
preserves caller-owned connection and transaction semantics. The technical CAS
and `RequestKey` contracts are available in Infrastructure; the original store
owner must still implement and consume them in its transaction boundary.

The 81-file Harness consumer slice moves 141 old import groups to the real
`ordessa_execution_agents.harness.definitions` owner. The
[consumer checkpoint](consumer-batch-81/README.md) documents its bounded test
scopes and remaining integration gaps. This is a verified consumer slice, not
full C1 retirement or product acceptance.

## Verification and remaining limits

Infrastructure source tests and its noneditable wheel each passed 175 tests
with zero skips. The CAS source and installed-wheel scopes each passed 206 tests
with zero skips; these overlapping runs are not additive. The Python boundary
fixtures passed 33 tests and the JavaScript fixtures passed 24. Full repository
boundary checks remain red, and complete product dependency closure and
installation have not been qualified. The consumer checkpoint describes other
bounded and unresolved scopes. No product-completion claim is made.

The candidate publication history still requires resolution of binary restore
snapshots and local-path metadata. Removing files in a later commit would leave
their blobs reachable in history. Do not publish until the history and exact
file ownership manifest are safe. This summary links only the accepted standard,
public boundary rules and sanitized consumer checkpoint; detailed local
receipts remain private.
