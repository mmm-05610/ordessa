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

Preparation/start/connect/stop/release/recover are currently absent from
supportedMethods. This slice does **not** satisfy the full AU003 Unit lifecycle.
The existing UnitRecords has no public read-free prepared handle usable for start
without another authorization context, nor stop/release settlement primitives;
core preparation DTO/composition and deployment evidence are still required.
Methods raise typed `PI_PROVIDER_UNAVAILABLE`; neither no-op success nor legacy
fallback is provided. See REUSE.md for source-based route comparison.

Tests are controlled C, including real Python fixture subprocesses for framing.
Native Pi process P and authorized model task M are separate and not claimed by
these tests. No third-party install/update or model call is required for tests.
