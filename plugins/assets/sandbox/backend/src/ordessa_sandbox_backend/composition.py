"""SandboxNativeService — composition-time gates and §C4 lifecycle.

Three contracts held in one place:

1. Field-claim conflict (§C2, verification.md extra-gate 3): when the sandbox
   facet and the Permissions native projection touch the same native config
   field, the pair is refused **at stage time** via the API's
   ``FieldClaimRegistry`` — the staging is order-insensitive and commits
   nothing on conflict, so no priority rule can resolve the clash away.
2. §C4 unload semantics: ``busy()`` counts instances still using the adapter;
   unload/uninstall while busy is ``PROVIDER_BUSY`` (never a silent
   detach-then-lose-the-refusal-code).
3. FR-08: uninstalling hides the describe region while the repository's
   stored intents/evidence stay readable; a new compile through a missing
   facet is refused so no unknown fragment reaches Harness.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from ordessa_sandbox_api import (
    FieldClaimRegistry,
    NativeSandboxIntent,
    SandboxApiError,
    SandboxCeiling,
    SandboxErrorCode,
    SandboxEvidence,
    SandboxOption,
)

from .catalogue import CatalogueStatus, SandboxOptionCatalogue
from .repository import NativeSandboxRepository, VerificationFacts
from .verifier import SandboxVerifier, VerdictKind

#: the two logical owners a native config field may be staged for. The
#: Permissions id is a NAME only — this package never imports Permissions.
SANDBOX_ADAPTER_ID = "sandbox.native-configuration@1"
PERMISSIONS_ADAPTER_ID = "permissions.native-projection"


@dataclass(frozen=True)
class FacetDescription:
    """What `sandbox.describe@1` (and the wire method) answers with."""

    region_visible: bool
    status: str  # available | unknown | uninstalled
    options: tuple[SandboxOption, ...]
    reason: str = ""
    locked_by_administrator: bool = False

    def to_wire(self, harness_id: str, native_version: str | None) -> dict:
        return {
            "apiVersion": "sandbox.describe@1",
            "harnessId": harness_id,
            "nativeVersion": native_version or "",
            "visible": self.region_visible,
            "status": self.status,
            "reason": self.reason,
            "lockedByAdministrator": self.locked_by_administrator,
            "options": [
                {
                    "optionId": o.option_id,
                    "status": str(o.status),
                    "source": o.source,
                    "platforms": list(o.platforms),
                    "coverage": list(o.coverage),
                    "lockedByAdministrator": o.locked_by_administrator,
                    "note": o.note,
                }
                for o in self.options],
        }


@dataclass(frozen=True)
class CompiledSandboxPlan:
    """A hand-off reference for the (UNBOUND) harness adapter.

    It names the stored intent and the target handle; it deliberately carries
    NO native configuration vocabulary — the closed ``SetField/ResetField/
    InvokeAction`` intent types are Harness C3's and live behind the
    unpublished ``harness-api`` checkpoint (api-requests.md G3). Binding this
    plan to real configuration is T05's work once the checkpoint publishes.
    """

    sandbox_id: str
    revision: int
    target_handle: str
    binding: str = ("UNBOUND: harness-api checkpoint not published "
                    "(specs/011-q5-safety/api-requests.md G3); applying "
                    "configuration is not this package's function")


def stage_field_claims(registry: FieldClaimRegistry, *,
                       sandbox_fields: Iterable[str],
                       permissions_fields: Iterable[str],
                       sandbox_owner: str = SANDBOX_ADAPTER_ID,
                       permissions_owner: str = PERMISSIONS_ADAPTER_ID) -> None:
    """Validate the WHOLE claim pair against the registry, then commit.

    A shared field raises ``SANDBOX_CONFIG_CONFLICT`` with nothing committed
    — proof the refusal happens at stage time. Because both facets are
    validated as one set, the outcome does not depend on which facet is
    mentioned first: there is no priority ordering to win with.
    """
    owners: dict[str, set[str]] = {}
    for name in sandbox_fields:
        owners.setdefault(name, set()).add(sandbox_owner)
    for name in permissions_fields:
        owners.setdefault(name, set()).add(permissions_owner)
    for native_field, claimants in owners.items():
        existing = registry.owner_of(native_field)
        all_owners = set(claimants)
        if existing is not None:
            all_owners.add(existing)
        if len(all_owners) > 1:
            raise SandboxApiError(
                SandboxErrorCode.SANDBOX_CONFIG_CONFLICT,
                f"native config field {native_field!r} is claimed by "
                f"{sorted(all_owners)}; the composition is refused at stage "
                "time and nothing was committed",
                suggestion="the two business owners must pre-allocate "
                           "disjoint fields — no priority order resolves "
                           "this")
    for native_field, claimants in owners.items():
        registry.claim(adapter_id=next(iter(claimants)), native_field=native_field)


class SandboxNativeService:
    """Composition-time owner of the sandbox facet (logical owner: Sandbox)."""

    SANDBOX_ADAPTER_ID = SANDBOX_ADAPTER_ID
    PERMISSIONS_ADAPTER_ID = PERMISSIONS_ADAPTER_ID

    def __init__(self, *,
                 catalogue: SandboxOptionCatalogue | None = None,
                 repository: NativeSandboxRepository | None = None,
                 verifier: SandboxVerifier | None = None,
                 admin_ceilings: Sequence[SandboxCeiling] = ()) -> None:
        self.catalogue = catalogue if catalogue is not None else SandboxOptionCatalogue()
        self.repository = repository if repository is not None else NativeSandboxRepository()
        self.verifier = verifier if verifier is not None else SandboxVerifier(
            catalogue=self.catalogue, admin_ceilings=admin_ceilings)
        self.field_claims = FieldClaimRegistry()
        self.compiled_intents: list[CompiledSandboxPlan] = []
        self._state = "ready"
        self._active: dict[str, None] = {}

    # ------------------------------------------------------ §C4 lifecycle

    @property
    def state(self) -> str:
        return self._state

    def busy(self) -> int:
        """Active-dependency count: instances still using this adapter."""
        return len(self._active)

    def register_instance(self, instance_key: str) -> None:
        self._active[instance_key] = None

    def release_instance(self, instance_key: str) -> None:
        self._active.pop(instance_key, None)

    def unload(self) -> None:
        if self.busy() > 0:
            raise SandboxApiError(
                SandboxErrorCode.PROVIDER_BUSY,
                f"{self.busy()} instance(s) still use the sandbox adapter; "
                "unloading now would lose the refusal/reconciliation code "
                "under an in-flight request",
                suggestion="release the dependent instances first")
        self._state = "unloaded"

    def uninstall_facet(self) -> None:
        """Detach the facet: UI region hidden, stored values retained."""
        if self.busy() > 0:
            raise SandboxApiError(
                SandboxErrorCode.PROVIDER_BUSY,
                f"{self.busy()} instance(s) still use the sandbox facet; "
                "uninstall is deferred",
                suggestion="release the dependent instances first")
        self._state = "uninstalled"

    def install_facet(self) -> None:
        self._state = "ready"

    def availability(self) -> "tuple[bool, str | None]":
        if self.busy() > 0:
            return False, "PROVIDER_BUSY"
        if self._state == "unloaded":
            return False, "PROVIDER_BUSY"
        if self._state == "uninstalled":
            return False, "UNINSTALLED"
        return True, None

    # ------------------------------------------------------------ describe

    def describe(self, harness_id: str, native_version: str | None, *,
                 platform_os: str = "linux", platform_version: str = "",
                 admin_lock: SandboxCeiling | None = None) -> FacetDescription:
        if self._state == "uninstalled":
            # FR-08: the region disappears; repository records stay readable.
            return FacetDescription(
                region_visible=False, status="uninstalled", options=(),
                reason="the sandbox facet is uninstalled; its UI region is "
                       "hidden while the stored intents/evidence are kept")
        provider_state = ("busy" if self.busy() > 0
                          else "unloaded" if self._state == "unloaded"
                          else "ready")
        result = self.catalogue.lookup(
            harness_id, native_version, platform_os=platform_os,
            platform_version=platform_version, admin_lock=admin_lock,
            provider_state=provider_state)  # busy/unloaded -> PROVIDER_BUSY (§C4)
        if result.status is CatalogueStatus.UNKNOWN:
            return FacetDescription(region_visible=True, status="unknown",
                                    options=(), reason=result.reason)
        return FacetDescription(region_visible=True, status="available",
                                options=result.options, reason=result.source,
                                locked_by_administrator=result.locked_by_administrator)

    # ------------------------------------------------- field-claim staging

    def claim_native_field(self, adapter_id: str, native_field: str) -> None:
        self.field_claims.claim(adapter_id=adapter_id, native_field=native_field)

    def stage_facet_claims(self, *, sandbox_fields: Iterable[str],
                           permissions_projection_fields: Iterable[str]) -> None:
        stage_field_claims(self.field_claims,
                           sandbox_fields=sandbox_fields,
                           permissions_fields=permissions_projection_fields)

    def stage_pair(self, registry: FieldClaimRegistry, *,
                   sandbox_fields: Iterable[str],
                   permissions_fields: Iterable[str]) -> None:
        stage_field_claims(registry, sandbox_fields=sandbox_fields,
                           permissions_fields=permissions_fields)

    # ------------------------------------------------------- verify/compile

    def verify(self, intent: NativeSandboxIntent, live: VerificationFacts, *,
               evidence: SandboxEvidence | None = None,
               admin_ceilings: Sequence[SandboxCeiling] = ()):
        """FR-06 gate: the caller commits nothing unless VERIFIED."""
        return self.verifier.verify(intent, live, evidence=evidence,
                                    repository=self.repository,
                                    admin_ceilings=admin_ceilings)

    def compile(self, intent: NativeSandboxIntent,
                live: VerificationFacts | None = None, *,
                evidence: SandboxEvidence | None = None,
                admin_ceilings: Sequence[SandboxCeiling] = ()) -> CompiledSandboxPlan:
        """Emit an UNBOUND hand-off plan for a VERIFIED intent only.

        A missing/unsettled facet refuses the compile outright (§C3: the next
        round without a compiled provider refuses that facet; no unknown
        fragment is passed through to Harness), and an unverified intent
        refuses with its verdict's stable code.
        """
        if self._state != "ready" or self.busy() > 0:
            raise SandboxApiError(
                SandboxErrorCode.PROVIDER_BUSY,
                "the sandbox facet is not installed/settled; the intent is "
                "not compiled and nothing is forwarded to Harness",
                suggestion="reinstall the facet or drop the sandbox facet "
                           "from this scope")
        if live is None:
            raise SandboxApiError(
                SandboxErrorCode.SANDBOX_INTENT_INVALID,
                "compile needs the current VerificationFacts to bind the "
                "plan to a live target")
        verdict = self.verify(intent, live, evidence=evidence,
                              admin_ceilings=admin_ceilings)
        if verdict.kind is not VerdictKind.VERIFIED:
            raise SandboxApiError(verdict.code, verdict.reason)
        plan = CompiledSandboxPlan(sandbox_id=intent.sandbox_id,
                                   revision=intent.revision,
                                   target_handle=live.target_handle)
        self.compiled_intents.append(plan)
        return plan
