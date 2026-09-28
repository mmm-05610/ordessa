"""Skills-side brand adapters (FR11; pure domain modules + published-API
registration, see base.py header).

The three brand adapters are genuine `ordessa_harness_api.ConfigurationAdapter`
implementations; registration rides the published
`harness.configuration-adapters` contribution point through the plugin's
`ContributionBatch` (`plugin.py`) — the interim "no registration exists"
shape is retired with the harness-api checkpoint.
"""
from __future__ import annotations

from .base import (
    AdapterTarget, Assessment, HarnessAdapterError, NATIVE_RESET, OWNED_REMOVAL_ONLY,
    ObservationResult, RELOAD, RESTART_RESUME, REFUSE, SkillProjection,
    VerificationOutcome, assess, content_ref_for, decide_reconfiguration,
    decide_reset_strategy, decide_update_strategy, evidence_ceiling,
    intent_source_for, mount_content_for, preview_target_handle,
    remove_owned_for, verify,
)
from .capabilities import (
    BRAND_PINS, BRAND_STATEMENTS, NO_EVIDENCE, SUPPORTED, UNSUPPORTED,
    UNKNOWN, CapabilityFact, CapabilityStatement, VersionPin, pin_for,
    registered_brands, statement_for,
)
from .conflict import (
    COLLISION_CODE, NAME_RULES, NativeNameRules, NameConflictError,
    evaluate_against_native_discovery, evaluate_managed_set, name_rules_for,
)
from .contribution import (
    CONFIGURATION_POINT, POINT_API_VERSION, SKILLS_FACET_ID,
    SkillsConfigurationAdapter, configuration_adapters, reconfiguration_decision,
)
from .intent import (
    GenerationBounds, ManagedContentRef, SkillIntentError,
    looks_like_absolute_host_path, sweep_host_path_free,
)
from .producer import (
    CONTRACT_ID as DELIVERY_CONTRACT_ID,
    MANIFEST_NAME as DELIVERY_MANIFEST_NAME,
    SkillDeliveryError, SkillDeliveryInput, SkillDeliverySet,
    SkillDeliveryValue, SkillProjectionSource,
    build_skill_delivery, skill_input_limits,
)
from . import claude, codex, pi

#: The controlled acceptance brands are the modules themselves (each
#: carries its own `HARNESS_ID`); there is deliberately no id -> module
#: dict here, so the capability registry in `capabilities.py` stays the
#: single static brand table of the domain (research-and-reuse.md §能力注册表).

__all__ = [
    "AdapterTarget", "Assessment", "BRAND_PINS",
    "BRAND_STATEMENTS", "COLLISION_CODE", "CONFIGURATION_POINT",
    "CapabilityFact", "CapabilityStatement", "GenerationBounds",
    "HarnessAdapterError", "ManagedContentRef", "NAME_RULES", "NO_EVIDENCE",
    "NATIVE_RESET", "NativeNameRules", "ObservationResult",
    "OWNED_REMOVAL_ONLY", "POINT_API_VERSION", "RELOAD", "RESTART_RESUME",
    "REFUSE", "SKILLS_FACET_ID", "SUPPORTED", "SkillIntentError",
    "SkillProjection", "UNSUPPORTED", "UNKNOWN",
    "VersionPin", "SkillsConfigurationAdapter", "assess", "claude", "codex",
    "configuration_adapters", "content_ref_for", "decide_reconfiguration",
    "decide_reset_strategy", "decide_update_strategy",
    "evaluate_against_native_discovery", "evaluate_managed_set",
    "evidence_ceiling", "intent_source_for", "looks_like_absolute_host_path",
    "mount_content_for", "name_rules_for", "pi", "pin_for",
    "preview_target_handle", "reconfiguration_decision",
    "registered_brands", "remove_owned_for", "statement_for",
    "sweep_host_path_free", "verify",
    "DELIVERY_CONTRACT_ID", "DELIVERY_MANIFEST_NAME", "SkillDeliveryError",
    "SkillDeliveryInput", "SkillDeliverySet", "SkillDeliveryValue",
    "SkillProjectionSource", "build_skill_delivery", "skill_input_limits",
]
