# ordessa-permissions-api

The typed domain contract of the Ordessa **permissions** domain: what a rule
may say, what an administrator may bound, what a decision is bound to, and how
those combine. Pure domain code — no storage, no service, no host import, no
network, no subprocess, nothing under `$HOME`.

Consumers: the Permissions backend (`evaluate`/`decide`/`query` authority), the
per-brand permission adapters, and the Profile/Settings/Chat surfaces. None of
them may invent a second rule model.

## What one ruling is made of

| Type | Role |
| --- | --- |
| `TypedRule` | tool identity + optional bounded target matcher + one of `allow`/`ask`/`deny` |
| `PolicyCeiling` | an administrator/host upper bound, only constructible from a trusted, signed record |
| `EffectiveCeiling` | the **intersection** of every ceiling in force (never last-wins) |
| `PermissionIntent` | a Profile/session wish: it can narrow, never widen |
| `OperationRequest` | the attributed pre-side-effect operation (principal, session, channel, generation, tool, target, **argument digest**) |
| `EffectivePolicySnapshot` | the runtime identity one decision was computed under, digest-verified |
| `AuthorizationDecision` | one ruling about one already-bound operation, with an expiry |
| `ApprovalRequest` / `ApprovalState` / `ApprovalFact` / `NativeReceipt` | the approval DTOs, keeping the existing `server_approvals` vocabulary (`open`/`settled`/`invalid`, `allow`/`deny`, `once`/`bounded`) |

Entry points: `synthesize(...)` (data-model 规则合成 1..5) and
`evaluate_authorization(...)` (the §C1 `Denied | AllowedOnce | PendingApproval`
shape). Both are pure functions over the types above.

## Refusal, not coercion

Anything malformed is refused with a typed `PolicyRefusal`: unknown record
keys, unknown actions, brand mode names used as actions, unbounded or
wildcard-only patterns, negative or non-integer priorities, naive timestamps,
a snapshot missing one binding field, a digest that no longer matches its
bindings. Nothing is defaulted, and an absent pattern never silently means
`*`.

## Supported, refused, unknown: three answers

* **supported** — the model can state the outcome, and the outcome is
  `allow`, `ask` or `deny`.
* **unsupported** — `POLICY_ADAPTER_MISSING`, `PERMISSION_UNKNOWN_TOOL`: this
  cannot be honoured at all. The user is told to fix the provider or the
  vocabulary.
* **unknown** — `POLICY_SCOPE_UNVERIFIED`, `APPROVAL_RESULT_UNKNOWN`: we cannot
  tell. Side-effecting operations stay blocked, the existing operation is
  queried, and no retry is implied.

`unsupported` and `unknown` are different `CodeKind`s and different result
types; no code path merges them, and no unresolved fact is ever read as an
`allow`. `CodeKind.VIOLATION` covers the third case: the policy actively
refused (`POLICY_CEILING_VIOLATION`, `APPROVAL_STALE`, `APPROVAL_NOT_ACTIONABLE`).

## Wire families (T010, contracts §C4)

`wire_family.PERMISSION_ERROR_FAMILIES` maps every code this package can emit
to an **existing** family of the platform's closed wire vocabulary — the names
the foundation publishes in `server_plugin_api.wire_errors` (`FAMILIES`,
`STATIC_ERROR_FAMILIES`, `family_for`). No family is invented and no static
row is overridden: `APPROVAL_STALE` repeats the platform's own
`APPROVAL_INVALID` answer verbatim, `POLICY_SCOPE_UNVERIFIED` keeps the
`family_for` fall-through (`UNAVAILABLE`), and the remaining business rows
arrive the way the platform defines business rows to arrive — as the
`wire.error-families` contribution payload the backend plugin publishes.
The platform defines no family that collapses `unsupported` with `unknown`,
so the split survives the mapping (`CAPABILITY_UNSUPPORTED` versus
`UNAVAILABLE`/`OUTCOME_UNKNOWN`, disjoint and guard-tested); the two codes
were never merged at the code level either, per §C4. `wire_body_for(...)`
projects a `PolicyRefusal` onto the wire body — family in the `code` slot,
exact spelling in `details.internalCode`, source/target/remedy alongside,
and no field a tool argument or credential could ride through.

## Absence is never "no limit"

`PolicyCeiling.unverified(...)` is the explicit "no trusted record" ceiling, and
`intersect_ceilings([])` refuses with `POLICY_ADAPTER_MISSING`. A decision that
needs enforcement therefore refuses on both paths instead of inheriting a
permissive default. A ceiling whose provenance is unsigned, invented, or whose
scope is a session or a project is refused at construction: a low-trust input
cannot promote itself into an upper bound.

## Why the legacy list is not reused as an engine

`server-compat/profiles/permissions.py` resolves an ordered list where the
**last match wins**, so a later `allow` reverses an earlier `deny` — and its
output is posture only: it never saw an administrator ceiling. The legacy
vocabulary (tool keys, `allow`/`ask`/`deny`) is kept so migration inputs stay
readable, and its rule lists migrate as *user intent* (`PermissionIntent`),
where:

* ordering carries no authority at all — equal-priority conflicts resolve
  `deny` > `ask` > `allow`, and last-match widening is impossible by
  construction;
* an `allow` that overrides a stricter rule needs a verifiable
  `AdminAuthorization` bound to that exact tool, target, ceiling revision and
  expiry, and may not use a prefix wildcard;
* no intent rule, authorized or not, can relax a ceiling: a hard denial stays
  a denial and a `requireApproval` entry never degrades into `allow`.

`tests/test_legacy_last_match_divergence.py` asserts both halves of that
difference against the real legacy module.

## Brand names are not Ordessa results

`allow`/`ask`/`deny` are Ordessa's interpretation layer. `plan`, `auto`,
`bypassPermissions`, `untrusted`, `on-failure` and the rest are one brand's own
names and live only in `BrandMode`, validated against that brand's declared
vocabulary (`BRAND_NATIVE_MODES`). Two brands sharing a spelling do not share a
mode, and a brand with no declared vocabulary (`pi` today) is `unsupported` —
never an empty mode set that "probably means ask".

## The neutral authorizer port (T017, §C1 `permissions.authorizer@1`)

`ports.py` publishes `PERMISSIONS_AUTHORIZER_PORT` /
`PERMISSIONS_AUTHORIZER_PORT_VERSION` and the `PermissionsAuthorizerPort`
protocol — `evaluate`, `decide`, `reconcile`, `busy` (the §C1 "query" is
answered by `reconcile`; the backend exposes no second name for it) — with
the exact parameter surface of the real backend class, verified member by
member in `tests/test_neutral_authorizer_port.py` and pinned against the
backend's registration literal read from source text.

Who may consume it: the Harness pre-side-effect gate, the Chat approval
region, and Desktop-facing adapters — i.e. anyone that today would otherwise
import `ordessa_permissions_backend` internals or guess the signature. They
fetch the instance through the host's port registry under the published
name; this package supplies only the contract and its DTOs and stays
stdlib-only (a guard test imports it with the backend and platform packages
blocked).

What stays host-side: the implementation and its storage (`ApprovalFacts`,
`PolicyRepository`), the executor's `evaluate_with_grant` re-validation path
(deliberately not on the public port), the trusted-input plumbing that feeds
`evaluate` (authenticated principal, session/execution facts, native
generation and normalized tool/target/argument digest), and deactivation
control — a host must consult `busy()` before unloading the provider so an
open approval never disappears with it. Presence of the port is not
readiness; a missing, stale or unobserved input refuses.

## What this package does not do

No approvals service or repository (T02), no per-brand adapter compilation or
verification (T03), no `SandboxV1` and no native sandbox configuration (the
sandbox asset owns that), no UI, and no authorizer *implementation* — the
port in `ports.py` is the contract the backend instance is checked against.
The DTOs here are the shapes those layers exchange; the enforcement seam is
the Harness pre-side-effect hook that calls them.
