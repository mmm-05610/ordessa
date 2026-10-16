# Engineering common

This is an implementation candidate pending user code review. The confirmed
three groups contain shared values, local constraints and mechanisms. Business
IDs, references, record invariants and closed decoders belong to their actual
owners. Structure confirmation, technical verification and user acceptance are
separate steps.

| Common owner | Remaining responsibility |
| --- | --- |
| `models/values.py` | RealmId/ProjectId/ActorId, Digest, UtcInstant, RelativePath and primitive validation, bounded collections and explicit duplicate refusals. |
| `models/identity.py` | Scope and ActorRef attribution; no record schema, authentication or permission. |
| `models/refs.py` | Generic bounded BlobRef. Its content identity excludes the storage locator; it grants no download permission. |
| `models/selection.py` | ContentSelector over supplied bytes/JSON values and its existing 16 MiB bound. |
| `outcomes/diagnostics.py` | Minimal ReferenceError preserving code/str/args. No business code enum, full DomainError or `.error` construction. |
| `mechanisms/codec.py` | Canonical/value projection, strict generic parsing helpers and Digest/Actor/Scope/Blob/selector decoders. No business catalog or decoder registration. |
| `mechanisms/hashing.py` | Existing domain-prefixed hashing over caller-selected projections, using pure infrastructure encoding. |
| `mechanisms/selection.py` | select_bytes, verify_selection and SelectorChecks cache/work budget over supplied bytes. No retrieval or authority lookup. |

Business owners now define their contracts directly:

| Owner | Contracts moved out of common |
| --- | --- |
| `artifacts/{refs,method_binding,provenance}.py` | ArtifactRevisionRef and IDs; captured MethodRef/ExactMethodResourceRef; sources, captures, claims, evidence and generation facts. Separate closed ref/method/provenance codecs live here. |
| `changes/{refs,baselines}.py` | ProposalRef and IDs; RepositorySnapshotRef used by implementation intent baselines and review targets. These captured values provide no missing repository authority. |
| `changes/{errors,result}.py` | Existing business DomainErrorCode/DomainError and Result consumed by validate_change_set. The six permitted error subject classes stay closed; conversion from exact ReferenceError remains explicit. |
| `reviews/{refs,targets,identity,evidence}.py` | Review/Submission identity, closed SubjectRef/Target/TargetSet, review schema identity and captured reviewer evidence. Separate ref/target codecs live here. |
| `approvals/{refs,ref_codec}.py` | ApprovalRef and its closed decoder; no grant issuance or verifier. |
| `application/usecases/preconditions.py` | VersionExpectation projection from ReadSet. Actual SQLite CAS still consumes ReadSet.versions with the original signed-63-bit range. |

Captured MethodRef is a domain material pin. The existing MaterialBudget
conversion to the distinct methods SnapshotRef remains explicit. Domain imports
no methods stage. Submission and repository snapshot representations do not
enable unavailable resolvers. RecordIdentity keeps the review-specific schema
{1,2} restriction; it is not a universal identity. Actor/evidence values do not
replace the injected authorization or trust authorities.

Common imports only common and existing pure infrastructure encoding. Artifacts
imports only its own leaves and common. Review targets imports artifact refs and
the pure changes refs/baselines leaves, never changes models. Changes models may
depend on review requirements. The review record's existing seal/reduce algorithm
now belongs to `reviews.models`; gate rules depend on models and no return edge
remains. Runtime and TYPE_CHECKING domain graphs are acyclic. Every root/group
initializer stays thin with no forwarding, eager exports or lazy alias.

Nine former flat modules and the five former business common modules
(`models.provenance`, `models.trust`, `models.mutation`, `outcomes.errors`,
`outcomes.result`) are retired. No universal Ref base, optional-field Ref bag,
open decoder registry or old execution fallback was added. Exact-type, scope,
kind, digest and unknown-field checks remain with each owner. Common parsing
helpers take explicit refusal codes; actual callers retain their previous codes.

Domain/architecture checks passed 193 tests with zero skips. The original
application/SQLite/canonical checks passed 352 and failed one methods snapshot
test using a retired constructor field, with zero skips. The failure is preserved
for its owner. A frozen pre/post-source comparison matches schema 1/2 artifact
and review wire/digests, captured values, Result and 40 malformed decoder cases.
The strict prototype gate still refuses old pinned source paths with
`operation_registry_source_unavailable`; shared pins are left to the coordinator.
No full Engineering or product acceptance is claimed.

Current mapping, raw failures, dependency graphs, exact hashes and selective
candidate synchronization are in the
[source evidence](../../../../../../docs/implementation/nightly/evidence/common-responsibility-20261009/README.md).
The corresponding review record is kept separately in the
architecture-review worktree at
`docs/verification/common-responsibility-20261009/README.md`; no copy is
linked from this checkout. Earlier
[three-group evidence](../../../../../../docs/implementation/nightly/evidence/common-three-groups-20261009/README.md)
remains historical. The review tree is a partial source snapshot, not a runnable
installation. NewType distinctions are not statically verified. Production
auth/trust, unavailable baseline/submission services and broader engineering
closure remain outside this consolidation.
