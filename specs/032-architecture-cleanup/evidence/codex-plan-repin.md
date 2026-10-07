# Codex offline evaluation plan repin

The integrated Codex provider source changed while the current synthetic
`packages/backend/decision/evaluation/codex-unknown-plan.json` still pinned its
previous implementation. `codex_flow_probe.NativeBinding` compares the plan's
descriptor digest to `reviewed_code_digest(Path(native.__file__))` before owner
activation. It also compares the entire provider identity and evidence refs to
the actual owner's offer. The stale pin therefore rejects the legitimate
offline plan before the tests reach their intended compiler or authorization
checks.

This change updates exactly three current-plan fields:

- `fixture.offer.descriptor_digest`
- `fixture.offer.provider_ref.identity.provider_ref.implementationDigest`
- `fixture.offer.evidence_refs[0].descriptorDigest`

Old digest: `sha256:efc79c0ce56c4849d3bddce262b6cc7192068fad364c7ba376df6959631579c7`.

New digest: `sha256:7f72485fd7a024ecd40ceb872b54144b99a9fd937f3bb0ac64aa500649fc3b7a`.

The new value was computed from the current 51275 source bytes of
`plugins/harness/codex/src/ordessa_harness_codex/provider.py` using the actual
`reviewed_code_digest` function extracted from
`packages/backend/decision/src/ordessa_decision/runtime/flow.py`. Its SHA-256
input is `decision.reviewed-code/1\n`, followed by the decimal source byte
length, a newline, the source bytes and a final newline. The plain source
SHA-256 is `ad3025865a0ac427da146dbe294f67ccab4f9ae5724326cfa51674437c0629e0`.
The latest source commit at inspection was
`7b6528689a8efa2f5c71d2aca3c37555a25e6b62`.

The provider's `describe_configuration_offers` returns its implementation
digest in the descriptor and in its computed evidence reference; the core
provider identity carries that same implementation digest. All three fields
must therefore be repinned together. The provider still declares
`codex.defaults`, schema `0.157.1`, `supportStatus=unknown`, incomplete offers
and `durability=computed_nonpersistent`. The plan retains its synthetic task,
unknown support, proposal-only scope, budgets and expected `clarify` outcome.

No test or runtime validation was changed. The existing tampered implementation,
schema, generation, offer and evidence cases still assert refusal before key
access. The live authorization test still requires `live_authorization_required`.
No history receipt or prior evidence was rewritten; this is a current-plan
source pin, not new authorization or live-model evidence.

Validation in this slice: source inspection and digest computation only.
Tests were not run because the coordinating agent owns the test slot. No real
model call, credential read, service operation or Git write was performed.
