"""Process-local trusted registry of Claude family owned native channels.

An entry exists only for a unit whose isolated native channel THIS owner
launched and retained: the open effect registers the original handle before it
returns or fails. The registry is live bookkeeping, never durable truth — a
cold restart starts empty, and stop/release effects may act only on entries
present in this exact registry. A unit absent here is never owned by this
owner: borrowed or unknown units are never killed, never released and never
torn down automatically. No pid, argv or secret fact is ever stored here.
"""
from __future__ import annotations

import threading
from typing import Any, Mapping

from ordessa_execution_api.environment.operations import safe_json, sealed_mapping

UNIT_REF_FIELDS = {"environmentNamespace", "unitId", "ownerProviderRef", "sourceRevision"}


class ClaudeChannelRefused(RuntimeError):
    code = "CLAUDE_OWNED_CHANNEL_REFUSED"


def complete_unit_ref(value: Any) -> bool:
    """Published whole-reference shape check; comparison stays JSON-typed."""
    return (isinstance(value, Mapping) and set(value) == UNIT_REF_FIELDS
            and isinstance(value.get("unitId"), str) and bool(value["unitId"])
            and isinstance(value.get("ownerProviderRef"), Mapping))


def same_reference(left, right) -> bool:
    """JSON identity of two owner references, retaining JSON scalar types."""
    try:
        return safe_json(left) == safe_json(right)
    except (TypeError, ValueError):
        return False


class OwnedChannelEntry:
    """Trusted owner record of one owned channel; never consumer-visible."""

    __slots__ = ("unit_ref", "channel", "facts")

    def __init__(self, unit_ref, channel, facts):
        self.unit_ref, self.channel, self.facts = unit_ref, channel, facts


class ClaudeOwnedChannels:
    """Single provider-owned registry binding unit ids to live native handles.

    ``register`` accepts only a channel object this provider explicitly built
    (any object exposing ``close(timeout=...)`` / ``is_alive()`` — the real
    transport implements both); identity of the whole unit reference is
    compared, never regenerated. One live entry per unit id.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._entries: dict[str, OwnedChannelEntry] = {}

    @staticmethod
    def _unit_key(unit_ref):
        if not complete_unit_ref(unit_ref):
            raise ClaudeChannelRefused("complete owner-bound unit reference required")
        try:
            safe_json(unit_ref)
        except (TypeError, ValueError) as error:
            raise ClaudeChannelRefused("complete owner-bound unit reference required") from error
        return unit_ref["unitId"]

    def register(self, unit_ref, channel, facts=None) -> OwnedChannelEntry:
        """Retain one freshly launched owned handle before any effect or reply."""
        key = self._unit_key(unit_ref)
        if not callable(getattr(channel, "close", None)) or not callable(getattr(channel, "is_alive", None)):
            raise ClaudeChannelRefused("owned native channel must own its close and liveness surface")
        if facts is not None and not isinstance(facts, Mapping):
            raise ClaudeChannelRefused("owned channel facts must be a mapping")
        try:
            sealed = None if facts is None else sealed_mapping(dict(facts))
        except (TypeError, ValueError) as error:
            raise ClaudeChannelRefused("owned channel facts are not JSON-encodable") from error
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                if (existing.channel is channel
                        and (existing.facts is None and sealed is None
                             or same_reference(existing.facts, sealed))):
                    return existing
                raise ClaudeChannelRefused("unit already owns another live native channel")
            entry = OwnedChannelEntry(unit_ref, channel, sealed)
            self._entries[key] = entry
            return entry

    def entry(self, unit_ref) -> OwnedChannelEntry:
        key = self._unit_key(unit_ref)
        with self._lock:
            entry = self._entries.get(key)
        if entry is None or not same_reference(entry.unit_ref, unit_ref):
            raise ClaudeChannelRefused("unit is not owned by this native channel owner")
        return entry

    def is_owned(self, unit_ref) -> bool:
        if not complete_unit_ref(unit_ref):
            return False
        with self._lock:
            entry = self._entries.get(unit_ref["unitId"])
        return entry is not None and same_reference(entry.unit_ref, unit_ref)

    def has_live_process(self, unit_ref) -> bool:
        """True only while the owned native process is still running."""
        try:
            entry = self.entry(unit_ref)
        except ClaudeChannelRefused:
            return False
        return entry.channel.is_alive()

    def release(self, unit_ref) -> OwnedChannelEntry:
        """Drop this owner's own handle record; the registry never kills anything."""
        try:
            entry = self.entry(unit_ref)
        except ClaudeChannelRefused:
            raise ClaudeChannelRefused("release requires an owned native channel entry") from None
        entry = self._pop(unit_ref)
        if entry is None:
            raise ClaudeChannelRefused("release requires an owned native channel entry")
        return entry

    def _pop(self, unit_ref):
        key = self._unit_key(unit_ref)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            del self._entries[key]
            return entry
