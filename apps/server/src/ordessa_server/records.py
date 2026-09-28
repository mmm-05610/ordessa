"""Canonical product-record encoding — a re-export of the published contract.

The implementation moved to `server_plugin_api.record_encoding` in T014-S2c:
three plugins encode and digest records with these helpers, and reaching into
this host module for them was the rule-3 breach that slice closed. The host's
own neutral use cases keep importing them from here (and the published object
is the same function object, so a digest computed through either path is
byte-identical by construction).

The stored-data invariant lives with the implementation: `digest`'s `sha256:`
prefix and `canonical`'s JSON settings are what existing rows were written
with, so they are published once and never duplicated here.
"""
from __future__ import annotations

from server_plugin_api.record_encoding import (
    MAX_CANONICAL_BYTES,
    canonical,
    digest,
    reject_sensitive_keys,
)

__all__ = ["MAX_CANONICAL_BYTES", "canonical", "digest", "reject_sensitive_keys"]
