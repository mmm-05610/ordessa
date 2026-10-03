"""Brand configuration adapters for the native-subagents facet (§C3 triads).

Every module here is a **pure** boundary: content comes in, typed intents
come out. Nothing in this package may touch the filesystem, the network or a
process — the Harness (C0) owns applying an `IntentSet`; this facet owns
only compiling and interpreting it.

Since `harness-api` was published the intent vocabulary is C0's, not ours:
the types that cross this boundary are
:class:`ordessa_harness_api.IntentSet` / `MountContent` /
`RemoveOwnedContent` / `BindSecret` / `InvokeAction` / `Assessment` /
`Verification` / `AdapterContext` / `IntentSource` / `TargetHandle` /
`FieldClaim` / `VersionRange`. The Q3-internal pieces kept here
(`base.Assessment`, `base.CellVerdict`, the observation ladder,
`intents.ManagedItem`, the builder helpers) are **internal implementation
records, never a published cross-tree shape** (SR-1b CA2 resolution).

* `intents` — internal stricter token/grammar builders that emit the real
  intents, and one-shot complete-collection compilation (`compile_all`);
* `base` — the assess/compile/verify triad protocol over the contract types
  and the observation state machine (no `loaded` without a loader
  observation, G11/G12);
* `frontmatter` / `tomlwriter` — the two strict document codecs, each with
  self-verifying round-trip evidence (L1);
* `claude` / `codex` / `pi` — the per-brand triads, versioned per the pins in
  `specs/011-q3-subagents/capability-matrix.md`.
"""
from ordessa_harness_api import (
    AdapterContext, AdapterRefusal, Assessment as ContractAssessment,
    BindSecret, ConfigurationAdapterDescriptor, ContentRef, FieldClaim,
    FieldPath, IntentSet, IntentSource, InvokeAction, MountContent,
    RemoveOwnedContent, ResetField, SetField, TargetDescriptor, TargetHandle,
    VerificationUnknown, VersionRange,
)

from .base import (
    Assessment,
    AssessmentError,
    AssessmentState,
    CellVerdict,
    ConfigurationAdapter,
    ControlEntryObservation,
    DOMAIN_TO_CONTRACT_CODE,
    FileExistenceObservation,
    InvocationEventObservation,
    ItemVerification,
    Match,
    Mismatch,
    NativeLoaderObservation,
    OBSERVATION_KINDS,
    ObservationSet,
    ProjectedArtifactObservation,
    VerifyResult,
    VerifyState,
    adapter_refusal_for,
    as_state_machine,
    attested_states,
    observation_from_json,
    require_state,
)
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .intents import (
    FACET_ID,
    ManagedItem,
    build_invoke_action,
    build_mount,
    build_remove,
    build_rebuild_class_option,
    build_secret_binding,
    compile_all,
    discovery_diagnostics,
    mount_native_name,
    mount_relative_name,
    safe_field_path,
    scan_credential_bearing_fields,
    select_content_target,
    validate_context,
    validate_source,
)
from .pi import AuditedExtensionRegistry, PiAdapter

__all__ = [
    # contract types this facet now speaks (re-exports, not redefinitions)
    "AdapterContext", "AdapterRefusal", "Assessment", "AssessmentError",
    "AssessmentState", "BindSecret", "CellVerdict", "ClaudeAdapter",
    "CodexAdapter", "ConfigurationAdapter", "ConfigurationAdapterDescriptor",
    "ContentRef", "ContractAssessment", "ControlEntryObservation",
    "DOMAIN_TO_CONTRACT_CODE", "FACET_ID", "FieldClaim", "FieldPath",
    "FileExistenceObservation", "IntentSet", "IntentSource",
    "InvocationEventObservation", "InvokeAction", "ItemVerification",
    "ManagedItem", "Match", "Mismatch", "MountContent",
    "NativeLoaderObservation", "OBSERVATION_KINDS",
    "ObservationSet", "PiAdapter", "ProjectedArtifactObservation",
    "RemoveOwnedContent", "ResetField", "SetField", "TargetDescriptor",
    "TargetHandle", "VerificationUnknown", "VerifyResult", "VerifyState",
    "VersionRange", "adapter_refusal_for", "as_state_machine",
    "attested_states", "build_invoke_action", "build_mount", "build_remove",
    "build_rebuild_class_option", "build_secret_binding", "compile_all",
    "discovery_diagnostics", "mount_native_name",
    "mount_relative_name", "observation_from_json", "require_state",
    "safe_field_path", "scan_credential_bearing_fields",
    "select_content_target", "validate_context", "validate_source",
]
