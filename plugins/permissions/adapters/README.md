# ordessa-permissions-adapters

T03/T03b: per-brand permission **policy adapters** for the
`permissions.policy-adapters` facet (docs/design/safety-controls/contracts.md
§C1), declared on the **real** Harness public contribution point.

Three adapters - `PiAdapter`, `CodexAdapter`, `ClaudeAdapter` - each keyed by
`(harnessId, nativeVersionRange)`, exposing exactly the §C1 compile shape:

- `supports(evidence) -> supported | unsupported | unknown`
- `compilePolicy(snapshot) -> IntentSet | Refusal`
- `verifyPolicy(observation) -> Confirmed | Unknown | Mismatch`

## Composition authority (who admits what)

Since the foundation checkpoint the platform owns admission; this package
only declares. The split:

- **This package (declares)**: `PolicyAdaptersPlugin.build()` returns a
  `ServerPluginRegistration` whose `contributions` batch carries one
  callable `PolicyConfigurationAdapter` payload per brand, each carrying a
  `ConfigurationAdapterDescriptor`, on the point
  `harness.configuration-adapters` (api_version `v1`, facet
  `permissions.policy-adapters`). `contribution.py` builds them from
  measured evidence: `harnesses.toml` identity pins (`PINNED_NATIVE_VERSIONS`,
  drift-guarded by tests), `posture_config.py` writable paths as
  `entries`/`claims`, and the public contract `ValueSchema` as
  `payload_schema`. `adapter_versions` is pinned exactly to this
  distribution's own release fact (`pyproject.toml`: `version = "0.1.0"` —
  formerly `[1.0.0, ∞)`, a self-declared unbounded minimum no observation in
  this tree backed and disjoint from the Sandbox facet's exact pin, which made
  joint two-facet admission version-wise unsatisfiable; T020, see
  `specs/011-q5-safety/evidence/t020-*.txt` and
  `tests/test_adapter_version_evidence.py`). Field claims follow §C2 pre-allocation: claude claims
  `permissions.ask` / `permissions.deny`; codex claims `approval_policy`
  only (`sandbox_mode` belongs to the Sandbox facet); pi claims nothing
  (extension-backed).
- **The platform (admits)**: the point's conflict registry
  (`ordessa_harness.contributions`, bound by the product composition via the
  public `server_plugin_api` staging protocol) refuses duplicate adapter ids,
  overlapping `(harnessId, nativeVersionRange)` for one facet/entries set,
  and cross-facet field-claim conflicts - at composition, never last-wins.
  The Server host owns point binding (typed unbound/version refusals),
  owner injection, publish-on-commit visibility and `ContributionOwnerBusyError`
  unload protection.

The former private `PolicyAdapterRegistry` - a second authority duplicating
the platform's duplicate/overlap refusals - has been removed. What remains
(`PolicyAdapterDescriptor`, `select_adapter`) is pure data / pure lookup with
no admission power.

The C2 carrier uses the measured C1 `supports` and `compilePolicy` methods.
Its optional snapshot resolver must be installed by a trusted backend and
return a typed policy snapshot with a trusted effective ceiling bound to the
observed native pin. The default product has no such resolver: `assess` is
`unknown`, `compile` refuses, and `verify` stays `Unknown` without an
operation-bound native receipt. A controlled resolver can project the exact
C1 compiled fields into C2 `SetField` intents only where the descriptor has
an owned claim and a matching target authority. Codex sandbox writes are
outside the Permissions claim; Pi has no native file claim. Both refuse
those projections instead of silently dropping fields.
For the controlled C2 path the fragment item id must be the descriptor's
`adapter_id`, which is the source id on emitted intents; no arbitrary caller
item id is inferred from the JSON payload.

Compile is **pure**: no network, no subprocess/spawn, no `$HOME`/user-config
access, no key reads (enforced by an AST gate in `tests/`). The adapters emit
only native fields measured in this repository (see `cells.py` / `matrix.py`
for the per-cell evidence); a capability without evidence answers
`unsupported`/`unknown` and supports only explicit refusal - never allow.

Domain independence (verification gate 2): installing Permissions requires
only `ordessa-permissions-api`, `ordessa-server-plugin-api` and
`ordessa-harness-api` - never the Sandbox domain. The field-claim conflict
proof (gate 3) uses a locally defined stub facet inside this package's tests.

Blocked by seam gaps, honestly registered:

- G1: the live backend has no policy snapshot resolver bound to this carrier;
  its default contribution remains fail closed. This package does not consume
  a compiled intent into a pre-effect runtime decision.
- G2: no native-receipt plumbing is bound to the C2 carrier; `verifyPolicy`
  defines and tests C1 semantics over a typed observation, but C2 `verify`
  cannot confirm a JSON value match alone.
