"""Capture explicitly selected public command declarations at host composition.

This module contains no brand selection table. The caller chooses independent
brand public ports. Canonical encoding belongs to Infrastructure; the SDK only
constructs the document. Capturing names creates no execution or plugin authority.
"""
from __future__ import annotations

from hashlib import sha256
from typing import Iterable

from ordessa_execution_agents.harness.definitions.command_discovery import CommandCandidate, command_catalog
from ordessa_infrastructure.encoding.canonical_json import canonical_bytes


class CapturedCommandCatalog:
    """Captured immutable candidate values with fresh documents for consumers."""
    __slots__ = ("_candidates",)

    def __init__(self, candidates: Iterable[CommandCandidate]) -> None:
        catalog = command_catalog(candidates)
        self._candidates = tuple((entry["familyId"], tuple(entry["commands"]))
                                 for entry in catalog["candidates"])

    def command_catalog(self) -> dict:
        return command_catalog(self._candidates)

    def command_catalog_digest(self) -> str:
        return "sha256:" + sha256(canonical_bytes(self.command_catalog())).hexdigest()

    def command_catalog_document(self) -> dict:
        catalog = self.command_catalog()
        return {"catalog": catalog,
                "catalogDigest": "sha256:" + sha256(canonical_bytes(catalog)).hexdigest()}


def capture_command_catalog(candidates: Iterable[CommandCandidate]) -> CapturedCommandCatalog:
    """Capture caller-selected declarations; an empty selection stays empty."""
    return CapturedCommandCatalog(candidates)
