# ordessa-sandbox-backend

The Sandbox domain's **backend service** for `docs/design/safety-controls`
(task T04b, `plugins/assets/sandbox/backend`, dist `ordessa-sandbox-backend`):
native option/version management and verification for
`sandbox.native-configuration@1` / `sandbox.describe@1` (contracts.md §C2,
§C3, §C4; spec.md FR-05, FR-06, FR-08, FR-09). It builds on
`ordessa-sandbox-api` (types are consumed, never redefined) and registers
through `server_plugin_api` public types only.

This concept remains distinct from Pacthold's neutral execution resource:
nothing here imports, names, or stands in for `SandboxV1`/`runtime_composition`.

## Public surface (`ordessa_sandbox_backend`)

- `SandboxOptionCatalogue` — per `(harnessId, nativeVersionRange)` the
  available native options with their source, platform limits, coverage and
  `lockedByAdministrator` flags. Pins are registered from the real repo
  registry (`plugins/harness/src/ordessa_harness/harnesses.toml`, parsed with
  `tomllib`; no harness import) intersected with the API's brand matrix;
  only `codex`, `claude-code`, `pi` have closed vocabularies. A lookup for an
  unregistered pin or a family without a closed schema (opencode, hermes,
  dsh, qwen, kilo) returns an explicit `unknown` result with **no menu** — a
  UI must never guess options from a brand name, and selecting from an
  unknown result refuses with `SANDBOX_NATIVE_UNSUPPORTED`.
- `NativeSandboxRepository` — persisted intent records by
  `sandboxId + revision` (append-only; a Profile may store only a
  `SandboxIntentReference(id, revision)`, which is all that dataclass
  carries), plus `SandboxEvidence` keyed by
  `(targetHandle, runtimeGeneration)`. Any movement of the target's version,
  config-digest, platform or adapter facts invalidates the receipts; a query
  after invalidation cannot return a stale `verified`. This store holds no
  permissions data and lives in its own file when persisted
  (`from_json_file`) — it never writes harness/permissions config.
- `SandboxVerifier` — the §C2 backend half: given an intent, the current
  pin/platform facts (`VerificationFacts`) and available evidence, answers
  `verified | unsupported | unknown | refused(code)` implementing FR-06
  refuse-before-side-effect: unverifiable (no bound evidence), adapter-absent,
  inexpressible-stricter-than-native, or cross-session-contaminating each
  refuse **before** any message commit / tool side effect, with the API's
  stable codes (`SANDBOX_NATIVE_UNSUPPORTED`, `SANDBOX_EFFECT_UNKNOWN`,
  `SANDBOX_COVERAGE_UNPROVEN`, `SANDBOX_CONFIG_CONFLICT`,
  `SANDBOX_PLATFORM_UNSUPPORTED`, `PROVIDER_BUSY`). `unsupported` and
  `unknown` never merge. Verification itself performs no side effect
  (`verdict.effect_started` is structurally always `False`).
- `SandboxNativeService` — composition-time gates: `stage_field_claims` /
  `stage_pair` refuse a shared native config field between the sandbox facet
  and the permissions native projection **at stage time** via the API's
  `FieldClaimRegistry` (order-insensitive, atomic — nothing commits on
  conflict, so no priority rule can resolve it); `busy()` counts instances
  still using the adapter and `unload`/`uninstall` refuse with
  `PROVIDER_BUSY` while anything is active (§C4); `uninstall_facet()` hides
  the describe region while repository records stay readable (FR-08), and
  `compile()` through a missing facet refuses so no unknown fragment reaches
  Harness (§C3).
- `SandboxBackendServerPlugin` / `build_sandbox_plugin` — registers
  `provided_ports['sandbox.native-configuration@1']` and
  `provided_ports['sandbox.describe@1']` plus exactly one read-only wire
  method `sandbox.describe` (`required_params={"harnessId"}`,
  `optional_params={"nativeVersion","osName","osVersion","platformVersion"}`).
  `descriptor.requires` is empty: Sandbox installs without Permissions
  (enforced by `tests/test_sandbox_backend_dependency_direction.py`, which imports and drives
  the package in a subprocess whose meta-path blocks `ordessa_permissions*`,
  `ordessa_server*`, `ordessa_harness*`, `pacthold`).

## UNBOUND: the native-effect observation seam

`probe.py` defines the consumer-side Protocols `ConfigurationTarget`
(`is_available()`) and `EffectProbe`
(`observe_effect(target_handle, intent) -> EffectObservation`). They are
**UNBOUND**: their only intended implementation is the released
`harness-api` (`ConfigurationAdapter`/`TargetHandle`) once the C0 branch
publishes a checkpoint at a fixed SHA — see
`specs/011-q5-safety/api-requests.md` G3 and
`specs/011-q5-safety/baseline-t00.md`. The closed Harness C3 intent
vocabulary (`SetField`/`ResetField`/`InvokeAction`/`MountContent`,
`TargetHandle`, `FieldClaim`) is **not copied into this package and no
second vocabulary pretending to be it is defined here** (a test pins this).

Consequently this package **never applies configuration**: the Protocols have
no mutating method to call, `CompiledSandboxPlan` is an id+revision+handle
hand-off reference whose `binding` says `UNBOUND`, and no real config file is
written anywhere by this package. `compile`/effect probes against real
brands remain blocked pending the harness-api checkpoint and the T05 probe
work; the in-tree `verified` verdicts exist only for evidence supplied
through the repository seam, which is exactly what T05 will produce under
control.

## Test / run

```sh
cd <monorepo root>
PYTHONPATH=plugins/assets/sandbox/backend/src python -m pytest plugins/assets/sandbox/backend -q
```

Evidence ledgers: `specs/011-q5-safety/evidence/t04b-red-sandbox-backend.txt`
(red against the unimportable package) and
`t04b-green-sandbox-backend.txt` (green).
