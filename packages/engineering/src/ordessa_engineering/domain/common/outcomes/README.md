# Common outcomes

`diagnostics.py` owns only minimal ReferenceError constructor/decoder refusal,
preserving code, str and args without constructing `.error`. It imports no model,
business error enum or complete DomainError.

The actual validate_change_set business error catalog, exact subject constraints,
explicit conversion and Result now belong to `changes.errors` and `changes.result`.
Unexpected programming errors still propagate. Their former common modules are
retired without forwarders. See [common](../README.md) for candidate status and
verification limits.
