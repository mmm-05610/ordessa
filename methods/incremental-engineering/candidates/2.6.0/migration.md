# Incremental Engineering candidate 2.6.0 migration

This is a new unqualified candidate revision copied from the complete 2.5.0
candidate. The exact pre-copy inventory is in
`docs/source-inventory-2.5.0.json` (74 files, 411,500 bytes; canonical sorted
inventory SHA-256
`e212ef383000f673f917575f27b5dff2f735329c78fc86efa387336cda2bc7fc`). The
2.5.0 candidate and older snapshots remain unchanged.

## Method-bound Decision policy

This revision removes the copied `matching_validated_evaluation_required`
quality-admission declaration. For `claim_support`, an exact, complete
`supported` Decision answer may take the declared `pass` disposition only
after the original source has correlated the exact method, question-set,
request, and material versions; supplied every required full CheckKey exactly
once; and satisfied the declared evidence requirements. Current source,
reviewer identity, access, and permission guards still apply through the
original commit boundary. `contradicted` is `violated` and blocks;
`insufficient` blocks. Ties, missing or incomplete answers, truncation,
unmapped values, unknown source/evidence, and absent required evidence remain
unknown/manual or reject according to the original owner contract.

A Decision answer is not a Grant, proof of an asserted fact, or permission to
advance. The original independent review, acceptance Gate, adoption Grant, and
CAS remain required. Typed resource references and versions, full CheckKeys,
raw-response provenance, exact immutable method/material references, complete
review requirements, and current guards remain bound to the original records.

There is no model-quality flag, confidence threshold, argmax, untrusted
`evaluated` Boolean, automatic approval, or host fallback. The two semantic
criteria use the existing finite Choice v1 contract. Coverage options
`conflicting`, `partial`, and `complete` map to `violated`, `insufficient`,
and `satisfied`; drift options `drift_detected` and `no_drift_detected` map
to `violated` and `satisfied`. Numeric scores and native booleans are not
treated as discrete choices. Both criteria declare `satisfied: pass`,
`violated/insufficient: block`, and `unknown: manual`. Missing, tied,
incomplete, truncated, or unmapped answers remain `unknown`.

The candidate index is a byte-integrity list only. The descriptor evidence in
the copied `implemented-owner-contracts.json` is not a production catalog.
The copied `validation.json`, `docs/candidate-revision-notes.md`, and the
older checkpoint files are historical 2.5.0 records, not 2.6.0 qualification
receipts. Source and independent-review bindings must still identify the exact
Decision request, method/question-set version, fixed material versions,
complete CheckKeys, evidence refs and current authority guards; original
permission, ReviewRecord and acceptance/adoption gates remain authoritative.
This revision has no MethodRef snapshot, publication, or execution authority.
