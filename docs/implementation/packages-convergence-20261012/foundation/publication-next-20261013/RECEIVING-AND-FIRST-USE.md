# Dependency receiving and first use · 2026-10-13

This supplements the bounded source checkpoint `1be105e`. It does not turn
that checkpoint into a complete product installation or completed migration.

## Agents dependency repair received

Execution's new Agents wheel has SHA-256
`f6ad79ccffb90922b8101c98625abd9efdaea4649572edeb4cf569d6a7397b19`.
Its metadata directly declares `tomli-w>=1.2.0,<2` and `PyYAML>=6.0.3,<7`.
Foundation independently verified its ZIP, digest, metadata and all 120 runtime
payloads. The payloads are byte-identical to the previous wheel; the original
Agents typing marker remains the single byte `0a`.

The owner's clean installation started without Agents, `tomli_w` or `yaml`,
resolved the actual declared requirements offline, imported the original
private-generation module and passed `pip check`. This closes the earlier
missing-declaration request. It does not inherit whole-product qualification.
The earlier V5 consumer gate remains a dated result with its recorded manual
supplement; its source/wheel/receipt bytes have not been rewritten.

The source delta is only the Agents `pyproject.toml` dependency line, received
from the owner's immutable source capture. Every other TOML value is unchanged.
Source SHA-256:
`9d6e8f86178dda6c8845da28233e494eea39320b01af4ea63b42b07f556fac7e`.
Owner source-manifest SHA-256:
`71503633688921a99aa635393c38e405f6392623dda27925f66a869c2d6f1e34`.
Owner clean-install receipt SHA-256:
`8363640c1ffd0416d074154631e3ac93bc8e9d131045642c4c3005179f92c529`.

## First-use sequence and current limits

Use Python 3.12 for the currently verified package set. Agents' advertised
minimum Python version is not qualification of Python 3.10 or 3.11; its current
C1 dependency requires Python 3.12. Use a new, explicitly selected development
environment and data root. Do not migrate a real database as an installation
step, borrow another worktree's editable environment, or inject source paths to
hide missing wheel payloads.

1. Receive the exact current dependency-closed wheels and verify their metadata,
   payloads and installed origins. Fresh Agents metadata is received; the
   changing Engineering/Interfaces product composition still needs its fresh
   paired artifact receipts. The independent source branch is a partial
   development snapshot and does not contain the complete Interfaces/Server
   source set.
2. Select the public composition deliberately. A bare host uses
   `ordessa_server.composition.runtime.build_runtime(data_root, server_plugins=())`.
   Omitting `server_plugins` resolves exactly one installed
   `ordessa.server_product` entry point and refuses if absent or ambiguous.
   Installing a plugin does not enable it implicitly.
3. For the Pi product route, use
   `ordessa_server.composition.product_runtime.build_product_runtime` with the
   real matching `PiExecutionSelection` and `PiExecutionPorts`. Required facts
   include the existing immutable Profile revision, selected Environment and
   isolation, provider/model declaration, executable identities and credential
   source; ports come from their actual owners. The explicit permission factory
   must authorize this same selected runtime. ACP opt-in must be an exact
   boolean; a fixed effect-write guard requires that opt-in. Do not substitute
   fixture identities, fabricated grants or another captured principal.
4. For Work, use the same Engineering library and explicitly selected schema
   and capabilities. Assignment/acceptance requires the schema15 owner and
   configured capabilities; a machine bearer does not grant those roles. Start
   requires a real selected MethodRef obtained through the actual method-control
   owner, the same-scope ProposalRef, and an immutable method-valid `work_inputs`
   ArtifactRevisionRef. MethodRef is obtained from that selection, not added as
   a `start` command parameter. The first resume additionally needs the real summary,
   DID baseline, source-review plan, decisions and standard-profile revisions,
   plus the selected method/proposal binding. Use the actual current-condition
   digests and ordinal. `start` waits; it does not dispatch, grant or accept.
5. Keep execution completion and Engineering acceptance separate. Current
   receiving still needs the original report-only submission guard, authorized
   reviewer/query producers and the selected Unit validity guarantee at the
   Engineering COMMIT boundary. A protocol or refusing facade is not a bound
   producer. Do not reintroduce file/test scanning as acceptance evidence.

There is no newly qualified user-facing launch command in this supplement.
Formal Work/Pi startup, a successful model response, live in-flight cancellation,
accepted Work and complete product installation remain unqualified. The prior
Pi prompt failed with Connection error and upstream consumption was unknown;
this note authorizes no replay, paid fallback, new credentials or service change.

## Remaining source and retirement boundaries

The approved target retires C1. Its remaining 25 members still have production
consumers: Units admission/record facts, Agents/Harness provider declarations,
Server host-composition facts, profile/prompt/workspace resources and unresolved
identity/service/credential seams. They must move to those semantic owners.
No replacement common/compat/central API is proposed. Empty facades need no new
semantic owner; aggregate exports and package markers exit with their consumers
and packaging. Zero static imports do not justify deleting frozen codec vectors
or unknown-result fences.

The Interfaces delta15, CAS/RequestKey, resume75 and confirmed71 subsets do not
adopt the missing whole-source inputs. Current C1, composite Interfaces' four
source roots, bindings, Server and Product need precise owner-approved inputs
and fresh wheel receipts; the reusable CLI is a separate supported surface.
Candidate930 remains an inventory, and unknown inherited Apps/staged
authentication bytes remain excluded.

This supplement applies zero deletions. The old Harness/Kernel/runtime-compat
and server-compat receivers are still being checked. Formatting findings in
the previous frozen source remain disclosed; they do not block this metadata
receiving and have not triggered any rewrite of frozen owner bytes.
