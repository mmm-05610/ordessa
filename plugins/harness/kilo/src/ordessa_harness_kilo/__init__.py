"""Third-party Kilo CLI Harness; runtime ownership remains with composition ports.

Work Order 43 follow-up. The family currently consists of the production
deployment template only: the managed sidecar chain composes the pinned
artifact's native binary (`kilo acp`) through the generic ACP registration,
so no branded provider or projection module exists.
"""
from .production import (
    ADAPTER_ARTIFACT_ENTRY,
    ADAPTER_PACKAGE,
    ADAPTER_VERSION,
    ARTIFACT_NAME,
    ARTIFACT_TARGET,
    CREDENTIAL_ENVIRONMENT,
    CREDENTIAL_KIND,
    KiloProductionTemplateError,
    KILO_PROVIDER,
    MODEL_CONTROL_ID,
    NATIVE_MODEL_VALUE,
    OFFICIAL_BASE_URL,
    PRODUCT_MODEL_ID,
    STATE_TARGET,
    adapter_environment,
    capability_claims,
    config_document,
    deployment_document,
    documented_differences,
    harness_deployment,
    loopback_config_document,
    model_aliases,
    native_model,
    projection_files,
)

__all__ = [
    "ADAPTER_ARTIFACT_ENTRY", "ADAPTER_PACKAGE", "ADAPTER_VERSION", "ARTIFACT_NAME",
    "ARTIFACT_TARGET", "CREDENTIAL_ENVIRONMENT", "CREDENTIAL_KIND",
    "KiloProductionTemplateError", "KILO_PROVIDER", "MODEL_CONTROL_ID",
    "NATIVE_MODEL_VALUE", "OFFICIAL_BASE_URL", "PRODUCT_MODEL_ID", "STATE_TARGET",
    "adapter_environment", "capability_claims", "config_document",
    "deployment_document", "documented_differences", "harness_deployment",
    "loopback_config_document", "model_aliases", "native_model", "projection_files",
]
