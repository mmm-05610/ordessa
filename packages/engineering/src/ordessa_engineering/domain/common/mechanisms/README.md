# Common mechanisms

Pure operations over caller-supplied values and bytes: canonical value decoding,
recursive projection, generic strict parsing, common-value decoders, existing
domain-prefixed hashing, and bounded content selection/verification with a
per-resolution cache. No retrieval, authority lookup or trust judgement.

Business owners define their closed ref/provenance/target and record codecs and
choose their own hash payloads. No open decoder registry lives here. Actual
business callers explicitly retain their prior refusal codes. BlobRef owns
exclusion of its storage locator from content identity. See [common](../README.md)
for candidate status, exact dependencies and verification limits.
