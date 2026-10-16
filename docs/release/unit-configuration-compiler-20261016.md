# Unit configuration compiler binding

The original Unit admission context can now receive an explicitly selected pure configuration compiler through `bind_configuration_offer_compiler` and `unit_services`. Without this binding, configuration offers remain unavailable. This replaces an unconditional refusal in the read aggregation; it adds no runtime-provider registry or lifecycle dispatch.

Trusted application composition chooses the compiler implementation. Harness declaration metadata does not authenticate a native producer. Reads check the original context, currently admitted definition and provider generation, compiler descriptor, and current definition-level policy before accepting results. Published Unit services cannot replace their compiler binding. Existing proposal/source validation remains in place. No Grant, issuer, store, native channel, or model process is created.

Validation against the exact PR source snapshot: the existing Codex pure-read suite and nine additional boundary cases pass, 36 tests total. The original public-route positive case and read-denial assertions remain. CI runs this suite independently so another Codex module collection failure cannot hide it.

Pure compiler binding grants no managed-input or native lifecycle authority. The later [captured Unit input follow-up](unit-captured-input-20261016.md) replaces the unsupported coordinator through the formal fresh Unit owner and preserves the original acceptance/replay/query scenario there; it still requires explicit real capture and Workspace authority ports.
