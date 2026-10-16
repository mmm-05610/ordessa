"""Pure command-candidate document shape; declarations are supplied by callers.

A candidate is a command name only. Presence grants no installation, execution,
credential, model, session or capability guarantee. This SDK does not encode JSON,
calculate digests, discover plugins or supply a default brand catalog.
"""
from __future__ import annotations

from typing import Iterable, Tuple

HARNESS_COMMAND_CATALOG_VERSION = "harness-command-discovery/1"
CommandCandidate = Tuple[str, Tuple[str, ...]]


def command_catalog(candidates: Iterable[CommandCandidate]) -> dict:
    """Build a fresh document preserving explicitly supplied family/name order."""
    entries = []
    families = set()
    for candidate in candidates:
        if not isinstance(candidate, (tuple, list)) or len(candidate) != 2:
            raise ValueError("Invalid command candidate")
        family, commands = candidate
        if type(family) is not str or not family:
            raise ValueError("Invalid command family")
        if family in families:
            raise ValueError("Duplicate command family")
        if not isinstance(commands, (tuple, list)) or not commands:
            raise ValueError("Invalid command names")
        names = []
        for name in commands:
            if type(name) is not str or not name:
                raise ValueError("Invalid command name")
            if name in names:
                raise ValueError("Duplicate command name")
            names.append(name)
        families.add(family)
        entries.append({"familyId": family, "commands": names})
    return {"catalogVersion": HARNESS_COMMAND_CATALOG_VERSION,
            "candidates": entries}
