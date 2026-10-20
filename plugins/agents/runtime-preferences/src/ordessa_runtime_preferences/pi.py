"""Pi configuration adapter (``assets.runtime-preferences.pi``), facet
``assets.runtime-preferences`` — pure assess/compile/verify at document
evidence level.

Targets the agent-dir user settings (``pi.settings.json`` handle).
Native surface facts and per-key citations live in :mod:`.keys` (this
module adds no brand facts of its own); the assess/compile/verify behavior
is the shared engine. Registration manifest: :func:`registration_manifest`.
"""
from __future__ import annotations

from typing import Any, Mapping

from . import common, engine, keys
from .types import (
    AdapterContext, Assessment, IntentSet, PreferenceRequest, Refusal,
    Verdict,
)

BRAND = "pi"
ADAPTER_ID = "assets.runtime-preferences.pi"
CONTRIBUTOR_VERSION = common.CONTRIBUTOR_VERSION


def registration_manifest() -> dict[str, Any]:
    """The registration facts this adapter contributes under; the bridge
    turns these into the real C2 ``ConfigurationAdapterDescriptor``."""
    return {
        "adapter_id": ADAPTER_ID,
        "facet_id": common.FACET_ID,
        "facet_schema_version": common.FACET_SCHEMA_VERSION,
        "api_version": "v1",
        "harness_id": BRAND,
        "entries": (common.ENTRY,),
        "payload_schema": common.PAYLOAD_SCHEMA_ID,
        "native_target": keys.NATIVE_TARGET_NAMES[BRAND],
        "cells": {group: keys.cell(BRAND, group).status for group in keys.GROUPS},
    }


class PiAdapter:
    adapter_id = ADAPTER_ID
    registration_manifest = staticmethod(registration_manifest)

    def assess(self, context: AdapterContext,
               request: PreferenceRequest) -> Assessment:
        return engine.assess(BRAND, context, request)

    def compile(self, context: AdapterContext, before: Mapping[str, Any],
                desired: PreferenceRequest) -> IntentSet | Refusal:
        return engine.compile(BRAND, context, desired)

    def verify(self, context: AdapterContext, observed: Mapping[str, Any]) -> Verdict:
        return engine.verify(BRAND, context, observed)


