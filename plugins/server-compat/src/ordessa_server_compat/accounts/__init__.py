"""Order 56: managed subscription accounts - records, assets, and reclamation.

A subscription login is a *credential asset*, not native state: the control
plane owns it, every turn materialises a working copy into the Harness home,
and the turn's end reclaims it (the Harness may have refreshed it in place).
This package is the backend half of that model:

* :mod:`records` - the ledger rows (identity, state, asset locator and digest;
  never a token);
* :mod:`assets` - the bounded, declared-files-only archive, its digest, the
  per-account lock, and the reclaim rule that refuses to overwrite an asset
  that changed underneath a turn.
"""
