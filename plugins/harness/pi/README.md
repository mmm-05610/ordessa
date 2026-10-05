# Independent Pi provider

Distribution `ordessa-harness-pi`; import `ordessa_harness_pi`. Provider/family ID
remains `pi`. Registration is through the existing core AgentContributionSet,
constructed by the host with a fixed definition reference and implementation
SHA-256. Importing this package performs no launch or discovery.

`PiRuntimeProvider` requires explicit trusted deployment ports for a live Unit,
its canonical configuration lock, exact current native-session binding and
managed RPC writer. Pass the **same core InvocationVerifier** used for that
Unit's Environment. Each effect consumes that core context once and each setter
rechecks the existing grant/current writer before dispatch. Owner `channel`
returns an already bound PiRpcClient over LeaseBoundChannel; it never starts a
replacement process. This private management channel is not returned by connect.

Native configuration support is `pi.model@1` (`provider`, `model`) and
`pi.thinking@1` (`level`), value actions only, live/session scoped. Model maps to
native `set_model(provider, modelId)`. Readback comes from `get_state`; arbitrary
model metadata and secrets are excluded. Version comparison is ownerSerialized,
not a cross-external-writer native atomic CAS. An ACK alone, missing readback,
failed native command or missing durable confirmation remains unknown. Unknown
stops subsequent items; no rollback or resend occurs. Missing required kind or
payload prevents all setters; optional unsupported declarations are explicit.

ConfirmationPort must be backed by the existing owner journal and original
native attempt evidence. `record` durably binds the exact original invocation,
Unit, declaration, before/after readback and returns a scoped reference. `read`
returns only that original attempt receipt; equal current settings cannot settle
an old unknown operation. The provider has no operation dictionary, configuration
cache, additional database or daemon. No production ConfirmationPort is included
in this slice: the host must compose the existing journal; absence is refused.

Preparation/start now directly call the injected existing UnitRecords. A trusted
UnitProjectionPort verifies the fixed core plan/root/digest, revalidates the
original consumed start context and supplies current journal/publication/native
owner evidence. Preparation reserves only; start fixes opening before the
channel factory opens the pinned isolated installation. Pi initializes by native
get_state and re-reads the same sessionId before confirmation. Every native
creation edge rechecks current authority. Unknown keeps the original live handle,
records unknown and never launches a replacement, kills it or sends a prompt.

query_step only reads the original creation through the projection after core
query verification. describe_access requires a confirmed existing session and
live handle. connect requires a trusted explicit lease port, which binds native
payloads behind per-write revoke/expiry/drain/epoch cuts; no unrestricted client
is returned. Absent ports leave these capabilities out of supportedMethods.
Current configuration ports are still independently injected and remain required
for configuration management. stop/release/recover remain unavailable until
original journal settlement and cold native evidence are composed. Production
plan/owner/factory/lease/confirmation composition and Pi P/M remain PARTIAL; no
fixture port is a default production implementation.

Tests are controlled C, including real Python fixture subprocesses for framing.
Native Pi process P and authorized model task M are separate and not claimed by
these tests. No third-party install/update or model call is required for tests.


Unit identity uses only the original UnitReservation.public_ref: exact
`environmentNamespace/unitId/ownerProviderRef/sourceRevision`. Prepare returns
that immutable original reference; every lifecycle/configuration use verifies
the complete received identity against the trusted original journal projection.
Raw two-field handles, altered owner/generation/source/environment and extra or
missing fields are rejected before native effects. Configuration UnitOwnerPort
must expose read_unit from that same authorized journal, not a caller field
copy. Unit publication also binds that same Unit and canonical configuration
scope/current epoch. Tests' explicit controlled public_ref is C proof only,
not production provenance or native readiness evidence.

Configuration targets now come directly from the original authorized
UnitReservation.configuration_target_ref, retaining environment/scopeId/revision
and ownerProviderRef/sourceRevision. Publication and configuration owner
inspection must match that exact property; apply/query verification, snapshots
and original result confirmations retain the same full target. Comparisons use
type-sensitive safe_json so boolean generation cannot impersonate an integer.
The target's fixed sourceRevision is distinct from the native snapshot revision.
The Pi package does not generate target provenance or strip it to raw scope.
