# Explicit change review criteria

Review the exact baseline and candidate source identities and immutable captures supplied by the caller. The sample identity uses source `did-baseline-v1` / `did-candidate-v2`, document locator `project-files:alpha:design/DID.md`, versions `baseline-v1` / `candidate-v2`, and content digests `baa554d94798eab1445037e3c2d4a50d03022cc239deed4569dca8544c8e2960` / `80b04c5b572379d267a85d0aeab2c4c612d24256591ad9791e93ee99e76d2443`. Scope is realm `example-realm`, project `alpha`; these are externally supplied references, not snapshots or git commits.

Use the method's JEV review operation to assess the supplied candidate against the captured baseline and scope. Identify claims and evidence, distinguish supported changes from gaps, and return a completed review result with an explicit passed/not-passed/unknown conclusion. The method's later registration gate consumes that exact recorded result and only allows passed reviews. No additional manual-review step is inserted. Never infer that a digest recovers historical content. This text is guidance, not a machine predicate.

The action does not collect discussion, infer or create a DID, or register a change automatically. Registration is a separate explicit operation after a review decision.
