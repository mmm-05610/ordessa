# Engineering method mechanisms

Definitions is the pure foundation; validation consumes definitions; loading and compilation consume definitions and validation. Neither validation nor compilation imports loading. Methods imports neither application, domain nor adapters.

`loading.loader.load_method` performs explicit bounded reads through `definitions.contracts.sources.ResourceReader`; `loading.parsing` owns the sole strict parser. `loading.captured` reconstructs caller-constructible caches from immutable bytes, without IO. LoadedMethod proves capture only.

Safe public `compile_method`, `validate_method`, and `freeze_method` now belong to `application.orchestration.methods`: they reconstruct captured input before using pure validation/compilation. The compiler kernel is private, has no IO/store authority and performs complete validation. The retired compiler public entry and loading publication/content/ports files have no forwarding aliases. Application content operations belong to `application.orchestration.method_content`; pure content schema checking belongs to `validation.schema`.

Modern CompiledProgram typed fields remain the semantic authority. `compilation.encoding` alone owns external program encoding/decoding, canonical projections, derived digest and legacy consumer views; definitions does not import it. Historical schema1 remains explicit and read-only. `definitions.models.identity.method_digest` is the sole method-domain digest helper, using infrastructure canonical bytes without changing hash domains. Shared defaults belong to `definitions.defaults`; validation report/phase belong to `definitions.contracts.validation`.

Resource references, templates, method_content.value validation, entry, roles/skills, required capabilities, original limits, golden byte semantics, and finite refusals are retained in the implementation. Local schema closure uses no remote retrieval. The application still needs injected trusted catalogs; DTO fields do not authenticate. Publication uses the original store's atomic released-identity enforcement, not a second ledger.

Phase1 source migration is awaiting coordinator integration and serial verification, including persistence consumers, original source/golden/history assertions and distribution checks. No whole-product completion is claimed.

## Schema 2: declaration only

`read_method_definition(loaded)` is the public, pure typed reader for the closed `ordessa.methods/actions-v1` schema-2 contract. It rebuilds every projection from the captured source bundle, validates the action/routing declarations and bundled schema closure, and returns `MethodDefinition` with the existing `MethodRef` type. Its source-capture pin is `method_digest("method-snapshot", {schema_version, method_id, release_version, manifest_sha256, resource_digests})`; `resource_digests` is sorted by resource id and contains exact `{id, sha256}` pairs. This is an immutable source pin only, not a publication or registry binding.

Schema 2 has no entry action and no execution compiler. `validate_method` reports `METHOD_EXECUTION_UNSUPPORTED`; `compile_method` returns that error after capture verification and never falls back to the V1 `WorkflowSpec` compiler. `ActionStep` is a finite ordered declaration, and step-local admission names only that step's bound input slots. These gates are declarative and are not executed here. Schema-1 `WorkflowSpec` remains solely because existing consumers still call the original interpreter. It is not part of candidate 2.7.0 and cannot execute schema 2.

Candidate [incremental-engineering 2.7.0](../../../../../methods/incremental-engineering/candidates/2.7.0/README.md) is unpublished and declaration-only. It supplies no production profile: profile selection and independent reviewer selection are explicit caller inputs; no profile id is invented, and the independent-review admission still requires a future trusted application port. The external-only DID/review/package sample remains blocked by the current domain contracts documented in the phase handoff.
