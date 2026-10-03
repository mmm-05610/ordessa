# ordessa-sandbox-adapters

Per-brand **native-sandbox configuration adapters** for the Sandbox asset
(tasks T05/T05b). Since the foundation checkpoint (`8844c475bc`, merged as
`52906b514d`) the three brand facet descriptors are contributed through the
**real** `harness.configuration-adapters` point — no stand-in seam for the C2
contribution, no invented second registry.

## Who admits what (single authority)

* **The platform admits contributions.** `HarnessContributionRegistry` (behind
  `server_plugin_api.stage_contributions` and the Server plugin host) is the
  composition authority: it validates the payload against the point's
  `ConfigurationAdapterDescriptor` contract, refuses duplicate adapter ids,
  `(harness, native-version × adapter-version)` range overlaps, same-facet
  entry collisions and **cross-facet native-field claim collisions** with the
  typed platform error `HarnessContributionError` ("native field claims
  overlap"), before anything commits; staged-but-uncommitted batches are not
  resolvable; publication, owner identity, unbound-point
  (`ContributionPointUnboundError`), version (`ContributionVersionRefusedError`)
  and busy-retirement (`ContributionOwnerBusyError`) refusals are the host's
  (§C4, verification.md gates 2/3/5).
* **This package admits nothing.** The former private
  `SandboxAdapterRegistry` / `NativeConfigContribution` / `stage_field_claims`
  acted as a second admission authority with private error classes and are
  **deleted** (`test_platform_admission.py::test_package_exports_no_second_admission_authority`
  pins their absence). What the package keeps is the brand *content*: the
  honest `assess / compile / verify` rules below and the descriptor data
  (`points.py`) it hands to the platform.
* The conflict proofs in `tests/test_platform_admission.py` /
  `tests/test_product_lifecycle.py` use a **local stub descriptor** for the
  "second facet" — the Sandbox domain installs and proves this without ever
  importing `ordessa_permissions_*` (extra-gate 2).

## The bound C2 shape

`SandboxAdaptersServerPlugin` builds a `ContributionBatch` of three
`Contribution(point_id="harness.configuration-adapters", api_version="v1",
payload=HarnessSandboxConfigurationAdapter(...))` records. Each callable
payload exposes a public `ConfigurationAdapterDescriptor` and the C2
`assess / compile / verify` methods (point literals pinned
symbol-equal to `ordessa_harness.contributions` in
`tests/test_real_point_binding.py`; third-party closure mirrors the platform's
own contributor fixture — `ordessa-harness-api` + `ordessa-server-plugin-api`,
**no** harness package code: `harnesses.toml` is located via
`importlib.util.find_spec` + `tomllib`, never by importing `ordessa_harness`):

* `facet_id="sandbox.native-configuration"`, `facet_schema_version="1"`;
* `harness_id`/`native_versions` measured from the real `harnesses.toml`
  (codex `2.0`, claude-code `0.81.2`, pi `2.0`) — the descriptor claims exactly
  the recorded pin, nothing wider;
* `adapter_versions` is exactly `(0, 1, 0)` — this distribution's own release
  fact (`pyproject.toml`: `version = "0.1.0"`), the only runtime-adapter
  version fact this tree backs (no production `describe_installation()`
  observer exists here). The Permissions facet independently pins its own
  release fact (also `0.1.0` today — each value backed by its own
  `pyproject.toml`, not copied); see `tests/test_joint_facet_version_binding.py`
  and `specs/011-q5-safety/evidence/t020-*.txt` (T020).
* entries/claims: Codex owns `sandbox_mode` + `sandbox_workspace_write` on the
  `codex-config-toml` file target; Claude owns only the `bashSandbox` /
  `powerShellSandbox` / `monitorSandbox` toggles on `claude-settings-json`;
  **Pi files zero claims** (extension-backed → unsupported/absent) and its
  payload schema admits nothing;
* `payload_schema` is built from the platform `ValueSchema` (closed object, no
  `additional_properties`): a malformed payload — `danger-full-access`, an
  unknown `shell`/path key, a `coverage=all` claim — is refused by the
  platform's schema before any compile even runs (§C2 "no arbitrary shell/path
  writes").

## Brand rules (unchanged semantics, proven from repo evidence)

- **Codex** — only `read-only`/`workspace-write` are writable postures
  (`posture_config.py:77-79`); accepted `sandbox_mode` values come from the
  committed, version-matched App Server schema `SandboxMode` enum. Ceiling
  loosening and admin-enforced disable refuse — never a bypass.
- **Claude Code** — Bash/PowerShell/Monitor scope only; `requiredCoverage` of
  read/edit/MCP/network returns `SANDBOX_COVERAGE_UNPROVEN`; compiled output
  asserts **no** broader coverage (absence, not a flag). Linux/WSL2 bwrap +
  macOS Seatbelt supported, native Windows `SANDBOX_PLATFORM_UNSUPPORTED`, an
  unmeasured OS `SANDBOX_EFFECT_UNKNOWN` — never merged.
- **Pi** — extension-backed only; with no loaded sandbox extension nothing is
  compiled (`SANDBOX_NATIVE_UNSUPPORTED`, zero intents) and bare Pi is never
  configured as isolated. Unknown OS ≠ unsupported; process-scoped changes with
  undeclared cross-session impact refuse with `SANDBOX_EFFECT_UNKNOWN`.

## Published C3 vocabulary and remaining effect boundary

The `harness-api` READY checkpoint publishes the C3 intent DTOs. A compiled
`set_field` can become a real `SetField` through `to_harness_c3(target=...,
source=...)` when the caller supplies an authorized target handle and source.
Missing authority, a foreign facet, or a reset/action without its baseline or
action declaration raises `HarnessContractUnavailable`. DTO conversion is pure;
it does not establish ownership, apply a file change, or verify native behavior.

The callable contribution deliberately reports `Assessment("unknown")`,
`AdapterRefusal(AUTHORIZATION_REFUSED)` and `VerificationUnknown` while its C4
context lacks a Sandbox ceiling, authorized facts and authenticated native
readback. The existing Sandbox-domain brand compilers remain separately
testable; no product path joins those facts to the Harness C4 methods yet.
The empty object used by C4's read-only capability inspection returns typed
`unknown`; it is not a valid Codex compile request. Malformed concrete payloads
return typed `unsupported` assessment / `INVALID_FRAGMENT` refusal, without
letting schema exceptions escape the callable contribution.
The T05 L2 ACP effect probe and readback therefore remain open.

## Test

```
PYTHONPATH=plugins/assets/sandbox/adapters/src \
  <repo>/.venv/bin/python -m pytest plugins/assets/sandbox/adapters -q
```

The package tests exercise product carrier admission, a controlled callable
C2 invocation, C3 DTO conversion, and fail-closed results without a model.
