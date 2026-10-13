# Engineering method mechanisms

Definitions is the pure foundation; validation consumes definitions; loading and compilation consume definitions and validation. Neither validation nor compilation imports loading. Methods imports neither application, domain nor adapters.

`loading.loader.load_method` performs explicit bounded reads through `definitions.contracts.sources.ResourceReader`; `loading.parsing` owns the sole strict parser. `loading.captured` reconstructs caller-constructible caches from immutable bytes, without IO. LoadedMethod proves capture only.

Safe public `compile_method`, `validate_method`, and `freeze_method` now belong to `application.orchestration.methods`: they reconstruct captured input before using pure validation/compilation. The compiler kernel is private, has no IO/store authority and performs complete validation. The retired compiler public entry and loading publication/content/ports files have no forwarding aliases. Application content operations belong to `application.orchestration.method_content`; pure content schema checking belongs to `validation.schema`.

Modern CompiledProgram typed fields remain the semantic authority. `compilation.encoding` alone owns external program encoding/decoding, canonical projections, derived digest and legacy consumer views; definitions does not import it. Historical schema1 remains explicit and read-only. `definitions.models.identity.method_digest` is the sole method-domain digest helper, using infrastructure canonical bytes without changing hash domains. Shared defaults belong to `definitions.defaults`; validation report/phase belong to `definitions.contracts.validation`.

Resource references, templates, method_content.value validation, entry, roles/skills, required capabilities, original limits, golden byte semantics, and finite refusals are retained in the implementation. Local schema closure uses no remote retrieval. The application still needs injected trusted catalogs; DTO fields do not authenticate. Publication uses the original store's atomic released-identity enforcement, not a second ledger.

Phase1 source migration is awaiting coordinator integration and serial verification, including persistence consumers, original source/golden/history assertions and distribution checks. No whole-product completion is claimed.
