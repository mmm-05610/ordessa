# Review binding selection lifecycle (entry 85)

`SQLiteReviewBindings` may now be created either with its existing explicit
`ProposalRef` and nonempty phase tuple, or unbound with exactly
`proposal_ref=None, phases=None`. Partial or placeholder selections, including
an empty phase tuple, are rejected. Every runtime resolution on an unbound
instance fails with `METHOD_TARGET_BINDINGS_UNAVAILABLE`; there is no latest-
proposal lookup or fallback.

An unbound instance can receive one selection through
`bind_selection(context, *, proposal_ref, phases)`. The call checks the real
`CommandContext` and `Scope`, reads the exact Proposal from the original
Engineering SQLite UoW, enters the original `MethodControl.guard_method`, then
re-reads and validates the Proposal closure and every phase through the existing
`_resolve`/`_bind` path. This resolves each declared immutable material input,
workflow review-request node, target and document type. Selection is assigned
only after all checks succeed. A failed attempt leaves the object unbound and
can be retried; a successful selection is immutable for that instance and a
second bind is refused. Owner reads happen outside the selection mutex to avoid
inverting its lock order with the original library/method guards; publication
uses a short compare-and-set under the mutex, so competing validated selections
cannot overwrite one another.

This is an in-memory source initialization lifecycle, not persisted state,
authorization, or a grant. The read uses the original library and method guard;
review execution still requires the existing review admission, access and
reviewer authorities. It does not by itself create or advertise a production
review capability, bind missing product ports, or qualify method publication.

The new focused test is
`packages/engineering/tests/application/test_review_binding_bootstrap85.py`.
It uses the original schema-15 SQLite fixture and existing method-control path.
This task did not run tests, build or install; qualification remains with the
coordinating serial executor.
