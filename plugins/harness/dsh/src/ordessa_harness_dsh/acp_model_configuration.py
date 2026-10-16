"""dsh configuration adapter (``assets.model-provider.dsh``), facet
``assets.model-provider`` — pure assess/compile/verify, E1.

Honest absence (freeze §2/§3): this package pins NO dsh model-configuration
facts — the dialect table is empty, the native target is ``None`` and the
provider exposes no configuration methods (no configuration evidence port
exists for dsh in this tree). The adapter therefore:

- ``assess``: every choice is ``unsupported`` with that exact reason — the
  npm CLI pin is a channel pin, never a model-configuration fact.
- ``compile``: typed refusals only; the protocol compilation surface is
  honestly absent (no MountContent/BindSecret/CompileIntent is ever produced).
- ``verify``: always ``unknown`` — no pinned readback evidence exists; a
  written/acknowledged value can never be presented as an applied fact.

Kind label ``dsh.model`` is registered for the day gate evidence arrives.
"""
from __future__ import annotations

from typing import Any, Mapping

from . import acp_model_facts as common
from ordessa_execution_agents.harness.definitions.model_compilation import (
    AdapterContext, Assessment, ChoiceRequest, Refusal, Verdict,
)

ADAPTER_ID = "assets.model-provider.dsh"
CONTRIBUTOR_VERSION = "1"

#: The dsh model kind label; a registration identity, never an applied fact.
DSH_MODEL_KIND = common.DSH_MODEL_KIND

_ABSENT_REASON = ("dsh has no pinned model-configuration evidence port in this "
                  "package; the protocol compilation surface is honestly absent")


def registration_manifest() -> dict[str, Any]:
    return {
        "adapter_id": ADAPTER_ID,
        "facet_id": "assets.model-provider",
        "facet_schema_version": 1,
        "api_version": "v1",
        "harness_id": "dsh",
        "kind": DSH_MODEL_KIND,
        "supported_native_versions": common.RANGE_STRINGS["dsh"],  # "" — empty by design
        "native_target": common.NATIVE_TARGET["dsh"],              # None — absent by design
        "entries": ("assess", "compile", "verify"),
        "payload_schema": "model-provider.choice.v1",
        "claims": {},  # no pinned dsh configuration claims exist in this tree
    }


class DshAdapter:
    adapter_id = ADAPTER_ID
    registration_manifest = staticmethod(registration_manifest)

    def assess(self, context: AdapterContext, request: ChoiceRequest) -> Assessment:
        if not isinstance(context, AdapterContext):
            raise TypeError("adapter context required")
        return Assessment("unsupported", _ABSENT_REASON, harness_id="dsh",
                          native_version=context.harness_version)

    def compile(
        self, context: AdapterContext, before: Mapping[str, Any],
        desired: ChoiceRequest,
    ) -> Refusal:
        if (not isinstance(context, AdapterContext)
                or context.target_handle.harness_id != "dsh"
                or not common.identity_text(context.target_handle.identity)):
            return Refusal("target-conflict",
                           "dsh compiler requires its own explicit target identity")
        # The surface is honestly absent: even a well-formed choice refuses
        # with the exact absence reason — no invented intents, no secret binds.
        return Refusal("capability-unsupported", _ABSENT_REASON,
                       details={"kind": DSH_MODEL_KIND})

    def verify(self, context: AdapterContext, observed: Mapping[str, Any]) -> Verdict:
        if (not isinstance(context, AdapterContext)
                or context.target_handle.harness_id != "dsh"
                or not common.identity_text(context.target_handle.identity)):
            return Verdict("unknown", "dsh instance target identity evidence unavailable")
        return Verdict("unknown",
                       "dsh has no pinned model readback evidence in this package; "
                       "an acknowledgement is never an applied fact")
