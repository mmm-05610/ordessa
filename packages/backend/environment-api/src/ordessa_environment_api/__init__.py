"""``ordessa_environment_api`` — frozen open-environment contract types.

Spec 026 order 002 freeze. This package is the compiled contract surface for
E1 (environment), E3/F3 (relationships / single writer), E4/F4 (data areas,
host interaction, secrets), E5 (persistent references), C1 (submission) and
C2 (recovery). It is deliberately:

* **stdlib-only** — no product dependency, no plugin import, no I/O at import;
* **state-free** — dataclasses and protocols only, no registries, no globals
  that mutate on import, no side effects;
* **wire-stable** — every DTO has a canonical JSON encoding produced by
  :mod:`ordessa_environment_api.codec`; the TypeScript mirror in
  ``packages/desktop-platform/contracts/foundation/src/open-environment``
  must produce byte-identical output for the shared vectors in
  ``tests/contracts/vectors``.

Method names and field names are frozen here (spec 026 §E3 "方法名由002冻结");
semantic changes require a new contract version tag, not an in-place edit.
"""
from .identity import (
    ActivityRef,
    ActivationRef,
    ControlRef,
    EnvironmentId,
    ObjectRef,
    ParticipantInstanceRef,
    RequestKey,
    SubscriptionRef,
    SurfaceRef,
    UsageRef,
)
from .targets import (
    AuthorityKey,
    AuthorityRegistration,
    CanonicalFactTarget,
)
from .guarantee import (
    FingerprintDescriptor,
    GuaranteeLevel,
    InputCapture,
)
from .sequences import (
    RecoveryBinding,
    SequenceTriple,
    UnclassifiedDeliveryFact,
)
from .receipts import (
    ActivationReceipt,
    ActivityReceipt,
    BindingSnapshot,
    CreationReceipt,
    CurrentFactView,
    CutReceipt,
    UsageRecord,
)
from .references import (
    ChangeReservation,
    PersistentReference,
    ReferenceStatus,
    RevisionSelector,
)
from .services import (
    DataAreaDescriptor,
    HostDialogRequest,
    HostDialogResult,
    HostDialogStatus,
    SecretAvailability,
    SecretRef,
)
from .errors import (
    AdmissionRefusedError,
    AuthorityConflictError,
    ComparisonUnavailableError,
    EnvironmentError,
    GuaranteeUnavailableError,
    IdentityMismatchError,
    UnknownResultError,
)
from .ports import (
    DataAreaPort,
    PolicyPort,
    ProtectedFingerprintPort,
    RelationshipPort,
    SecretPort,
    StorePort,
)

CONTRACT_VERSION = "oe-contract/1"

__all__ = [
    "CONTRACT_VERSION",
    "ActivityRef", "ActivationRef", "ControlRef", "EnvironmentId",
    "ObjectRef", "ParticipantInstanceRef", "RequestKey", "SubscriptionRef",
    "SurfaceRef", "UsageRef",
    "AuthorityKey", "AuthorityRegistration", "CanonicalFactTarget",
    "FingerprintDescriptor", "GuaranteeLevel", "InputCapture",
    "RecoveryBinding", "SequenceTriple", "UnclassifiedDeliveryFact",
    "ActivationReceipt", "ActivityReceipt", "BindingSnapshot",
    "CreationReceipt", "CurrentFactView", "CutReceipt", "UsageRecord",
    "ChangeReservation", "PersistentReference", "ReferenceStatus",
    "RevisionSelector",
    "DataAreaDescriptor", "HostDialogRequest", "HostDialogResult",
    "HostDialogStatus", "SecretAvailability", "SecretRef",
    "AdmissionRefusedError", "AuthorityConflictError",
    "ComparisonUnavailableError", "EnvironmentError",
    "GuaranteeUnavailableError", "IdentityMismatchError",
    "UnknownResultError",
    "DataAreaPort", "PolicyPort", "ProtectedFingerprintPort",
    "RelationshipPort", "SecretPort", "StorePort",
]
