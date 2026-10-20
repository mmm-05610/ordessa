# External Change, Review and preparation Package records

The source-level record chain uses the existing EngineeringLibrary,
SQLiteUoWFactory, scoped repositories and command journal. It registers an exact
external baseline/candidate, associates a completed current review by creating
an immutable successor Proposal on the same Change, and saves preparation
document references in the original ImplementationPackage owner.

Public composition uses `application.assembly.build_engineering_service(factory,
EngineeringPorts(...))`. The additional optional ports are `source_materials`,
`method_guard` and `source_review_bindings`. Their demand contracts live in
`application.contracts.source_materials` and
`application.contracts.reviewer_admission`. The source and method ports must
retain the same factory as the service and review admission. Composition selects
implementations; request data cannot select an authority.

`SourceMaterialPort.read` authorizes and reads only the submitted immutable
locator/version. The command verifies its exact digest and length.
`MethodDeclarationGuard` holds the original publication/control guard through
COMMIT, reads exact method resources, and selects the finite preparation document
roles required by that method. `SourceReviewBindingsPort` independently selects
the exact plan and standard; the original reviewer verification and current
trust guard still apply through COMMIT. These ports do not publish methods or
authenticate reviewers by accepting a DTO. Missing ports refuse fresh writes.

The current operations are:

| Operation | Interface | Result |
| --- | --- | --- |
| `engineering.proposals.create` | 2 | Source-only ProposalRef and original Change |
| `engineering.proposals.associate_review` | 1 | Successor ProposalRef on the same Change |
| `engineering.packages.freeze` | 2 | Original PackageRef, `dispatchable=false` |

Review requests and recording use the existing review commands, with the original
Review Target wrapper carrying a scope-bound SourceRef/VersionCapture. The
schema-2 requirement pins its exact method resources. Association requires an
active, complete, passing review over the same source identities, method and
resources; failed, indeterminate, incomplete or withdrawn results cannot advance
the Change. A ReviewRef is never a registered Change.

`PreparedPackagePayload` (`ordessa.implementation-package/v2`) contains the
baseline, candidate, exact ProposalRef, ReviewRefs, method/resources and explicit
`PackageDocument(role, source_ref)` values. Method-specific roles and policy stay
with the method owner. Execution Grant, profile and repository effect manifest
are separate execution-envelope inputs. Prepared content without that envelope
refuses dispatch with `IMPLEMENTATION_ENVELOPE_UNAVAILABLE`.

Exact readback uses `engineering.proposals.get` and
`engineering.references.resolve` with the returned typed ref. It decodes the
original record independently of current external material availability. Bad
canonical record bytes produce `RECORD_CORRUPT`; a missing source during a fresh
operation produces `SOURCE_VERSION_UNAVAILABLE`. Original immutable triggers and
schema signatures remain enforced.

Schema 16 is explicitly selected for this record chain. The default schema 2 and
older supported schemas are unchanged. It widens the original `eng_proposals`
version constraint to 1 or 2, preserving original keys, canonical bytes, indexes,
foreign keys, triggers and the schema-15 acceptance ledger. No external artifact
registry or second command/run state is created. Explicit upgrade from schema 15
uses `adapters.persistence.sqlite.migrations.migrate_schema15(library,
backup_path=...)`, retaining the original backup, data-digest and transaction
checks. Opening a library does not migrate it. This batch exercised only newly
created temporary libraries; it did not migrate user databases.

Historical v1 records remain readable with their original codecs. The new public
create operation does not fall back to v1. Historical method candidates requiring
v1 writers are not executable against the new v2 capability contract. Candidate
2.7 has been published as an exact schema-2 declaration in temporary local
Engineering libraries through `publish_method_declaration`; the original
method-control command separately enables that declaration. It is not compiled
or adopted for execution and has no default Product publication/selection.
Controlled local access/management peers do not establish production authority.

The local source adapters are now exercised in
`engineering/real-source-chain-20261014/` under the implementation evidence root.
`ProjectSourceMaterials` accepts a finite tuple of complete SourceRef/path
mappings, including separate explicit files for two versions of one document.
It is read-only and refuses changed bytes, unavailable files and pin mismatches;
it does not scan projects or provide historical archives. `SQLiteMethodControl`
implements the exact declaration/resource guard on the original publication
store, with declaration control rechecked immediately before original COMMIT.
`DeclaredSourceReviewBindings` binds the frozen standard ID/digest and complete
declared resource pins into the source review. `DecisionReviewerSource` uses
the public Decision runner and original durable reader, checking the manifest,
selected provider, exact request/input and native answer/result digests.

One real free JEV invocation recorded `not_passed`/Engineering `fail`, and the
original association gate refused Package advancement. Its native evidence was
also cold-read in another process. Controlled provider tests cover a passing
full source/review/Package/reconnect chain; that passing test answer is not a
real-model result. Explicit caller-supplied spec/plan/tasks references remain
preparation records without an execution envelope.

Source qualification and exact changes are recorded under
`docs/implementation/packages-convergence-20261012/engineering/external-record-chain-20261014/`.
The source suites do not qualify a current wheel, default Product, Pi or
production reviewer authority. The separate real JEV receipt retains its
nonpassing result; it is not a successful real Package preparation.
