"""Third-party DeepSeek dsh Harness; runtime ownership remains with composition ports.

Work Order 43. The family currently consists of the production deployment
template only: the managed sidecar chain composes the pinned artifact's
``dsh --profile acp`` entry through the generic ACP registration, so no branded
provider or projection module exists - exactly the property the registry's
``driver`` field and the capability contract assert.

P-B (``approvals/PB-dsh-pilot-release.md``): this is the first per-Agent
integration package; the implementation moved here from
``pacthold.plugins/harness/dsh/src/ordessa_harness_dsh`` byte-for-byte (three declared edits live in
``production.py``). ``production`` is resolved lazily (PEP 562, same pattern as
the legacy facade and the M1-P-A① root package) so the package import never
pulls the renderer; ``dsh.<NAME>`` resolves on first use and returns the very
object from ``production`` (same module, not a copy). The legacy name
``ordessa_harness_dsh`` is a three-line alias of this package.
"""
from __future__ import annotations

_LAZY_NAMES = (
    "ADAPTER_ARTIFACT_ENTRY",
    "ADAPTER_PACKAGE",
    "ADAPTER_VERSION",
    "ARTIFACT_NAME",
    "ARTIFACT_TARGET",
    "CREDENTIAL_ENVIRONMENT",
    "CREDENTIAL_KIND",
    "DSH_PROVIDER",
    "DshProductionTemplateError",
    "HARNESS_HOME",
    "MODEL_CONTROL_ID",
    "NATIVE_MODEL_VALUE",
    "OFFICIAL_BASE_URL",
    "OUTPUT_TOKEN_LIMIT",
    "PRODUCT_MODEL_ID",
    "STATE_TARGET",
    "capability_claims",
    "deployment_document",
    "documented_differences",
    "harness_deployment",
    "loopback_settings_document",
    "model_aliases",
    "native_model",
    "projection_files",
    "settings_document",
)

__all__ = list(_LAZY_NAMES)


def __getattr__(name):
    if name in _LAZY_NAMES:
        from . import production as _production
        return getattr(_production, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
