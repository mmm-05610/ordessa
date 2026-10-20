"""Stable JSON projections used by pre-existing content identity contracts.

The default=str profile preserves recorded fingerprints. Callers own admission
and model meaning; this module does not introduce a JSON business model.
"""
import hashlib
import json


def digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
