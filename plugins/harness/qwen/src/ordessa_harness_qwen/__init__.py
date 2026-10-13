"""Third-party Qwen Code Harness; runtime ownership remains with composition ports.

Work Order 43. The family currently consists of the production deployment
template only: the managed sidecar chain composes the pinned artifact's
`qwen --acp` entry through the generic ACP registration, so no branded
provider or projection module exists.
"""
from .production import (
    ADAPTER_ARTIFACT_ENTRY,
    ADAPTER_PACKAGE,
    ADAPTER_VERSION,
    ARTIFACT_NAME,
    ARTIFACT_TARGET,
    CREDENTIAL_ENVIRONMENT,
    CREDENTIAL_KIND,
    HARNESS_HOME,
    MODEL_CONTROL_ID,
    NATIVE_MODEL_VALUE,
    OFFICIAL_BASE_URL,
    PRODUCT_MODEL_ID,
    QwenProductionTemplateError,
    QWEN_PROVIDER,
    STATE_TARGET,
    capability_claims,
    deployment_document,
    documented_differences,
    harness_deployment,
    loopback_environment,
    model_aliases,
    native_model,
    projection_files,
)

__all__ = [
    "ADAPTER_ARTIFACT_ENTRY", "ADAPTER_PACKAGE", "ADAPTER_VERSION", "ARTIFACT_NAME",
    "ARTIFACT_TARGET", "CREDENTIAL_ENVIRONMENT", "CREDENTIAL_KIND", "HARNESS_HOME",
    "MODEL_CONTROL_ID", "NATIVE_MODEL_VALUE", "OFFICIAL_BASE_URL", "PRODUCT_MODEL_ID",
    "QwenProductionTemplateError", "QWEN_PROVIDER", "STATE_TARGET", "capability_claims",
    "deployment_document", "documented_differences", "harness_deployment",
    "loopback_environment", "model_aliases", "native_model", "projection_files",
]
