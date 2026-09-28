"""Ordessa Permissions backend - the §C1 authorizer service and the one
authoritative store for approval facts (T02).

Composition of this package:

* `ApprovalFacts` - the migrated single authority over `server_approvals`:
  legacy identity (table name, ID shape, event names, CAS, `decideRequestId`
  idempotency) plus native correlation, native receipts with an explicit
  `Unknown` reconcile outcome, and once-spendable operation-bound grants.
* `PolicyRepository` - persisted `PolicyCeiling` (trusted-source provenance
  only) and `PermissionIntent` records, in separate stores with revision
  history, so a lower layer cannot raise the upper bound (FR-01).
* `Authorizer` - the `permissions.authorizer@1` service: ruling delegated to
  the pure domain (`ordessa_permissions_api`), record-keeping delegated to the
  two stores, fail-closed everywhere.
* `PermissionsAcpAdmission` - the `acp.admission.gate` adapter over the
  authorizer (T07/G1): the public ACP DTO admission port, with `ready`
  derived from installed authority plus authoritative native-session and
  runtime-generation evidence, never assumed.
* `PermissionsHostAcpAuthority` - the same port handed back to the channel
  fence as its permit verifier (T021): the tool-execution half is answered
  here (a plain bool against the recorded approval and its one-use grant),
  while the submission half refuses until the composition injects the bound
  admission record only it can mint.
* `LegacyProfileRulesMigration` - the read-only T012 importer of legacy
  Profile permission rules into USER-scope intent, with `needsReview` on
  every entry whose last-match-wins semantics are not provably equivalent
  (such entries never resolve to allow) and no fabricated ceiling.
* `PermissionsBackendPlugin` - host registration: both ports above, the
  approval UI's two wire methods and the read-only `permissions.policy.describe`
  summary for the Settings region; no wire path forges a ruling. Its
  `stop_hooks`/`disposal` bind the `busy()` fact to host deactivation (T018),
  and the gated `approval_route="legacy-delegated"` mounts the OLD
  `approvals.decide` wire method onto the same single authorizer (T019) -
  see the package README for the migration sequence.

Depends only on the standard library, `ordessa_permissions_api` and
`server_plugin_api`; the database is injected. `PermissionsHostAcpAuthority`
(T021) offers this lane to the channel fence as its permit verifier: it owns
the tool-execution half outright (a plain bool against the recorded approval)
and refuses the submission half until the composition injects the bound
admission record, which no plugin may mint. The native ACP receipt plumbing,
that permit record and the product wiring of the evidence source stay
C0-owned seams (G1/G2/G4/G5) and are NOT implemented or faked here.
"""
from __future__ import annotations

from .admission import PermissionsAcpAdmission, submission_argument_digest
from .authorizer import Authorizer
from .delegate import (LEGACY_DECIDE_METHOD, LEGACY_DECIDE_OPTIONAL,
                       LEGACY_DECIDE_REQUIRED, LegacyApprovalDelegate)
from .describe import (DESCRIBE_OPTIONAL_PARAMS, DESCRIBE_REQUIRED_PARAMS,
                       POLICY_DESCRIBE_METHOD, PolicyDescribe)
from .errors import (ApprovalNotFound, ApprovalRouteClosedError, CorrelationConflict,
                     DualAuthorityError, PermissionsBackendBusyError)
from .facts import INVALID, OPEN, SETTLED, ApprovalFacts, VersionConflict
from .host_authority import (PERMIT_SEAM_UNPUBLISHED, PermissionsHostAcpAuthority,
                             PluginAdmissionRefused)
from .migration import LegacyImportIssue, LegacyProfileRulesMigration, LegacyRuleImport
from .policies import PolicyRepository
from .plugin import AUTHORIZER_PORT, PLUGIN_ID, PermissionsBackendPlugin

__version__ = "0.1.0"

__all__ = [
    "AUTHORIZER_PORT",
    "ApprovalFacts",
    "ApprovalNotFound",
    "ApprovalRouteClosedError",
    "Authorizer",
    "CorrelationConflict",
    "DESCRIBE_OPTIONAL_PARAMS",
    "DESCRIBE_REQUIRED_PARAMS",
    "DualAuthorityError",
    "INVALID",
    "LEGACY_DECIDE_METHOD",
    "LEGACY_DECIDE_OPTIONAL",
    "LEGACY_DECIDE_REQUIRED",
    "LegacyApprovalDelegate",
    "LegacyImportIssue",
    "LegacyProfileRulesMigration",
    "LegacyRuleImport",
    "OPEN",
    "PERMIT_SEAM_UNPUBLISHED",
    "POLICY_DESCRIBE_METHOD",
    "PermissionsAcpAdmission",
    "PermissionsBackendBusyError",
    "PermissionsBackendPlugin",
    "PermissionsHostAcpAuthority",
    "PluginAdmissionRefused",
    "PLUGIN_ID",
    "PolicyDescribe",
    "PolicyRepository",
    "SETTLED",
    "VersionConflict",
    "submission_argument_digest",
]
