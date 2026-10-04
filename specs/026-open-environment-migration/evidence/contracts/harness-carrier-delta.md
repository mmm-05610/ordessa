# T008-04 Harness public carrier incremental freeze

Source checkpoint: 7335f4254480efba6f31402761661c510c82e2be. Original public-api SHA256 0c8cad1891abc49c76b45258a30edfd305b32a7f3658f30389a92e251631e4b1; identity-map SHA256 a4e601574a020fbb3c20d741312d8efaaf6d00577347a835eba8e5da83d96369. Original frozen artifacts and decision-pending-harness-carrier.md remain historical evidence.

Current user authorizes ordinary implementation choices and completion of original026; choose option A from the pending record to satisfy migration-map physical ownership. This is a carrier/assembly change, not Harness internal functionality or a new guarantee. No user permission or external operations expanded.

## Frozen seam

- New local public domain carrier: plugins/harness/contracts; private npm name @ordessa/harness-contracts; extension ID ordessa.harness-contracts, hostApi2, contract.js. Existing IDs, on-disk identifiers, token literal ordessa.harnessAvailability.v1 remain unchanged.
- Original foundation/product/token/HarnessAvailabilityToken.ts remains the single constructor site. It holds only Token<unknown> and stable identity; platform aggregate exposes opaque HarnessAvailabilityServiceToken, without domain interfaces or behavior.
- Harness carrier owns the unchanged C08 HarnessState/Report/Availability/Absent interface. Its typed HarnessAvailabilityToken is a type assertion/re-export of the SAME opaque platform runtime object. No wrapper, new Token, or duplicate identity.
- Availability absence/invariant/controlled fixture helpers move to Harness domain service module. No real brand probing, paths, CLI, bridge internals or lifecycle business added. Platform runtime service map harness stays an opaque optional injection; registering host-provided value is neutral DI only.
- Desktop/product explicitly composes the domain-provided absence service. Runtime platform public exports no Harness interface/factory; consumers of domain API import domain carrier. Existing shape/absence outcomes stay exact.
- Root owns platform/consumers/workspaces/lock/manifest/import-map/shared source mapping/contracts/status/tests/Git. Luna owns new carrier files only. No test/build/Git authority to Luna.

## Required proof

Public ownership/import purity, unique constructor/literal, strict object identity between platform opaque and Harness typed carrier (including built import-map), npm workspace discovery excluding Python/Go internals, actual default assembly absence honest, typecheck/build. Old-dispose versus new-generation behavior, boundaries and original assertions preserved; tests may change source fixture/import expectation to its mandated carrier, never weaken behavior.

This freeze resolves the ordinary carrier placement choice only. T008-04 remains unchecked until the implementation and required proofs pass. UI01 remains separately queued, not implemented by this change.
