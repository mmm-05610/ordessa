"""The mandatory policy layer over the REAL published permissions-api surface.

`assignments/ports.MandatoryPolicyPort` always named Q5 as its supplier; the
`permissions-api` checkpoint
(specs/011-plugin-rollout/checkpoints/permissions-api.json, publication
``bcd4387bec`` / ``codex/011-permissions-api-ready-r3`` ``6ac8f54a14``) is that
answer. What the published API actually offers for a *content-assignment*
consumer is the administrator **ceiling**, not an intent and not a ruling:

* ``ordessa_permissions_api.PolicyCeiling``
  (`plugins/permissions/api/src/ordessa_permissions_api/ceilings.py:156`) is
  "an upper bound that cannot be widened": it is only constructible from a
  trusted-source record (`from_record`, ceilings.py:172; `is_trusted`,
  ceilings.py:224 — signed + source in {signed-admin, host-trusted} + scope
  rank >= USER, `_CEILING_MIN_SCOPE_RANK`, ceilings.py:38), so a project- or
  session-scoped record can never pose as a mandatory rule;
* its entries are ``hard_denies`` / ``require_approval``
  (ceilings.py:165-166) of `CeilingEntry` (ceilings.py:94), which refuse an
  `allow` outright (ceilings.py:104-108) — a ceiling can only restrict;
* the tool vocabulary is closed and contains the key ``skill``
  (`rules.py:41-43`), matched against a bounded glob target
  (`TargetMatcher`, rules.py:114, `CeilingEntry.matches`, ceilings.py:135);
* `TOOL_EXPOSURE` (ceilings.py:71-79) states that an allow on ``skill`` implies
  `ExposureLevel.EXEC`, so a ceiling whose `maximum_exposure` rank is below
  that bounds every skill enable (the "allow-max" face of the same authority);
* the persisted store of that authority is
  `ordessa_permissions_backend.PolicyRepository.ceilings_current()`
  (`policies.py:132`), which is exactly what the published backend wires the
  authorizer on
  (`plugin.py:148`, provided port name `permissions.authorizer@1`,
  plugin.py:43 / registration plugin.py:165).

What the API does NOT offer, and this adapter therefore does not pretend:

* **no mandatory ENABLE.** A ceiling entry can only deny or require approval
  (ceilings.py:104-108); "the admin forces this skill on at this revision" has
  no vocabulary in permissions-api. `MandatoryRule(decision="enable")` stays a
  seam the resolver supports and the real supplier never emits today.
* **no project / harness / revision dimension.** `PolicyCeiling`'s record
  fields (ceilings.py:32-34) carry policyId/scope/revision/source/signed/
  deny/requireApproval/maximumExposure/effectiveFrom only; the harness-scoped
  object is `PermissionIntent` (intents.py:32-38), which by its own docstring
  "can only narrow" (intents.py:3) and is therefore the *overridable*
  configuration layer, not the mandatory one. So `rules()` receives
  `principal`/`project_id`/`harness_id` and can only honour the data-root
  dimension the ceiling actually has — see `scope_dimensions_not_expressed`.
* **no execution ruling re-used as a content answer.** `Authorizer.evaluate`
  (authorizer.py:73) needs an `OperationRequest` with an argument digest,
  native request id and session bindings; using it for content assignment
  would be a second policy engine, so the adapter reads the same *input* the
  authorizer reads (its ceiling provider) instead of its *output*.

Fail-visible discipline (the reason `NotConfiguredMandatoryPolicyPort` exists):
the resolver's seventh layer must never read an outage as "no constraints".
This mirrors `profile_facet.NotConfiguredProfileLayerPort` for §G3.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Sequence

from .api.errors import AssetDomainError
from .assignments.model import DECISION_DISABLE
from .assignments.ports import MandatoryRule

#: The closed tool-key vocabulary member this domain speaks about
#: (`rules.py:41-43`; `skill` is in the set, so a ceiling can bound it).
SKILL_TOOL_KEY = "skill"

#: The published provided-port name of the permissions backend service
#: (`plugins/permissions/backend/src/ordessa_permissions_backend/plugin.py:43`,
#: registered at plugin.py:165). Skills does NOT declare it in
#: `descriptor().requires`: the host grants another plugin's ports only along a
#: declared dependency (server_plugin_api/contract.py:258-270), and a hard
#: require would invert dependency (contracts.md 可选注册不能反转依赖), so the
#: composition hands the object in through the plugin constructor instead.
PERMISSIONS_AUTHORIZER_PORT = "permissions.authorizer@1"

#: The layer is not readable. Deliberately distinct from "no rule exists":
#: an outage must not fold into permissive (tests/test_no_execution.py
#: discipline; verification.md G05/G06 不可用不以静默过滤达成"成功").
MANDATORY_POLICY_UNAVAILABLE = "MANDATORY_POLICY_UNAVAILABLE"
#: A write that contradicts a mandatory constraint (G06 管理员强制规则被覆盖,
#: refused at the write edge instead of only at resolve time).
MANDATORY_POLICY_CONFLICT = "MANDATORY_POLICY_CONFLICT"

_NOT_COMPOSED_REASON = (
    "no permissions surface is composed: the mandatory layer was NOT read, "
    "which is not the same fact as 'the administrator published no rule'")


def mandatory_layer_unavailable(detail: str, *, reason: str = "") -> AssetDomainError:
    """The single refusal shape for every unreadable mandatory layer."""
    return AssetDomainError(
        MANDATORY_POLICY_UNAVAILABLE,
        "the mandatory policy layer could not be read from the published "
        f"permissions surface; the resolver refuses instead of treating the "
        f"outage as 'no constraints'{' (' + reason + ')' if reason else ''}",
        detail=detail)


def _permissions_api() -> Any:
    """Lazy import: this package must stay importable without permissions-api
    (the layer is optional by dependency direction, AGENTS.md rule 3). The
    public package path only — never `ordessa_permissions_api._internals`."""
    try:
        import ordessa_permissions_api as api
    except Exception as exc:  # noqa: BLE001 - classify as an unavailable layer
        raise mandatory_layer_unavailable(
            f"import ordessa_permissions_api failed: {exc}",
            reason="permissions-api not importable") from exc
    return api


def coerce_ceiling_source(source: Any) -> Callable[[], Any]:
    """Normalise every published shape of "the ceilings in force" into one
    zero-arg callable, without a second policy engine:

    * a callable — the `ceiling_provider` seam the backend itself uses
      (Authorizer authorizer.py:59-66, wired to `policies.ceilings_current`
      at backend plugin.py:148);
    * an `Authorizer`-like service object — its `ceiling_provider`;
    * a `PolicyRepository`-like store — `ceilings_current()` (policies.py:132).
    """
    if source is None:
        raise mandatory_layer_unavailable("no ceiling source was supplied",
                                          reason="not composed")
    for attr in ("ceiling_provider", "ceilings_current"):
        candidate = getattr(source, attr, None)
        if callable(candidate):
            return candidate  # bound: the published store/provider owns the read
    if callable(source):
        return source
    raise mandatory_layer_unavailable(
        f"unsupported permissions surface: {type(source).__name__}",
        reason="no published ceiling read surface")


class NotConfiguredMandatoryPolicyPort:
    """The shipped default when no permissions surface is composed.

    The honest reading of "absent": the layer contributed no rule because it
    was never asked one — which the consumer must be able to SEE, not infer.
    So this port carries `unavailable_reason` (the resolver turns it into a
    `mandatory_policy_unavailable` diagnostic in every resolve view, and
    `SkillsService` turns it into `mandatoryPolicy.status == "unavailable"` on
    every assignment write) and never claims "everything is allowed":

    * `rules()` answers an empty tuple only together with that reason; the
      reason is the product, the empty tuple is its placeholder. A caller that
      ignores `layer_status()` gets the same visible proof through the two
      surfaces above.
    * it is NOT injected when a real surface exists — `plugin.py` prefers
      :class:`PermissionsCeilingMandatoryPolicyPort`.
    """

    def __init__(self, *, reason: str = _NOT_COMPOSED_REASON) -> None:
        self.unavailable_reason = reason

    def rules(self, *, principal: str, project_id: str | None,
              harness_id: str | None) -> tuple[MandatoryRule, ...]:
        return ()

    def layer_status(self) -> dict[str, Any]:
        return {"status": "unavailable", "reason": self.unavailable_reason,
                "source": "ordessa_skills.mandatory_policy"}


class PermissionsCeilingMandatoryPolicyPort:
    """`MandatoryPolicyPort` read from the published administrator ceiling.

    One read, one projection: `ceiling_source` is the very surface the backend
    authorizer consumes (`policies.ceilings_current`, policies.py:132 — see
    coerce_ceiling_source), each record is rebuilt through
    `PolicyCeiling.from_record` when it arrives raw so the provenance check is
    the API's and not ours (ceilings.py:172-206), and untrusted provenance
    refuses the whole read (ceilings.py:224) rather than being downgraded to
    "no limit". Skills decides no policy here: it reflects what the ceiling
    forbids (hard_denies on the closed `skill` tool key) and what the ceiling's
    exposure bound makes unreachable (TOOL_EXPOSURE[skill] == EXEC,
    ceilings.py:78).

    `asset_id_source` supplies the catalogue's skill asset ids: a ceiling
    pattern is a glob over targets (rules.py:142) while a `MandatoryRule` names
    one assetId, so the expansion needs the id universe — the same shape
    `plugin.py` already uses for the Profile facet contribution
    (`asset_ids=lambda: records.list(kind="skill")`, plugin.py:205).
    """

    #: real surface: no unavailability reason
    unavailable_reason = None

    #: The identity dimensions the port accepts but the ceiling cannot express
    #: (see the module docstring: no project/harness/revision vocabulary in a
    #: PolicyCeiling record). Recorded so an integration report can name it.
    scope_dimensions_not_expressed = ("project_id", "harness_id",
                                      "rule revision pin")

    def __init__(self, *, ceiling_source: Any, asset_id_source: Any,
                 principal_note: str = "data-root principal") -> None:
        self._read = coerce_ceiling_source(ceiling_source)
        self._asset_ids: Callable[[], Sequence[str]] = asset_id_source
        self._principal_note = principal_note

    # -- MandatoryPolicyPort ----------------------------------------------------

    def rules(self, *, principal: str, project_id: str | None,
              harness_id: str | None) -> tuple[MandatoryRule, ...]:
        """Every skill the ceilings in force hard-deny, as disable rules.

        Deduplicated by assetId (the resolver refuses two mandatory rules for
        one asset, resolver.py:333-337) and revision-free: a ceiling pins no
        content revision, so `revision=None` always means "no pin" here rather
        than "the lower pin stands" — with decision `disable` the resolver
        never reads a revision anyway.
        """
        return tuple(
            MandatoryRule(asset_id, DECISION_DISABLE)
            for asset_id in sorted(self._denied_by_asset()))

    def approval_required(self, *, principal: str, project_id: str | None,
                          harness_id: str | None) -> tuple[dict[str, Any], ...]:
        """The `require-approval` entries, reflected NOT converted.

        An approval requirement is an execution-time constraint (the API's own
        ruling is `PendingApproval`, and nothing here may spend it), so it
        never becomes a `disable`/`enable` `MandatoryRule`; the resolver
        surfaces it as a typed diagnostic so `previewEffective` shows the
        admin's intent without Skills pretending to enforce it.
        """
        out: list[dict[str, Any]] = []
        for ceiling in self._ceilings_in_force():
            for asset_id, entry in self._matching(ceiling.require_approval):
                out.append({
                    "assetId": asset_id, "policyId": ceiling.policy_id,
                    "ceilingRevision": ceiling.revision_digest,
                    "pattern": None if entry.target is None
                    else entry.target.pattern,
                })
        return tuple(out)

    def layer_status(self) -> dict[str, Any]:
        ceilings = self._ceilings_in_force()
        return {
            "status": "consulted",
            "source": "ordessa_permissions_api.PolicyCeiling",
            "ceilings": [item.revision_digest for item in ceilings],
            "principal": self._principal_note,
            "scopeDimensionsNotExpressed": list(
                self.scope_dimensions_not_expressed),
        }

    # -- the read (the only permissions-api touch points) -------------------------

    def _ceilings_in_force(self) -> tuple[Any, ...]:
        api = _permissions_api()
        try:
            raw = self._read()
        except api.PolicyRefusal as refusal:      # codes.py, published type
            raise mandatory_layer_unavailable(
                refusal.human_readable[:512], reason="store refusal") from refusal
        except AssetDomainError:
            raise
        except Exception as exc:  # noqa: BLE001 - an outage is never permissive
            raise mandatory_layer_unavailable(
                f"ceiling source raised {type(exc).__name__}: {exc}",
                reason="provider failed") from exc
        items = tuple(raw or ())
        # `intersect_ceilings` refuses an empty input as
        # POLICY_ADAPTER_MISSING (ceilings.py:293-298) because an execution
        # ruling needs a bound. Content resolution is different: an empty
        # store means "no admin rule published", which is readable only when
        # the READ ITSELF WORKED — and it just did, above.
        built: list[Any] = []
        for item in items:
            ceiling = item if isinstance(item, api.PolicyCeiling) \
                else api.PolicyCeiling.from_record(item)
            if not ceiling.is_trusted:            # ceilings.py:224
                raise mandatory_layer_unavailable(
                    f"ceiling {ceiling.policy_id} is not from a trusted "
                    "provenance; a lower-scope record may not pose as a "
                    "mandatory rule", reason="POLICY_SCOPE_UNVERIFIED")
            built.append(ceiling)
        return tuple(built)

    def _matching(self, entries: Iterable[Any]) -> Iterable[tuple[str, Any]]:
        asset_ids = self._known_asset_ids()
        for entry in entries:
            for asset_id in asset_ids:
                # CeilingEntry.matches(tool, target), ceilings.py:135: the
                # closed key test plus the bounded-glob target test, both the
                # API's own.
                if entry.matches(SKILL_TOOL_KEY, asset_id):
                    yield asset_id, entry

    def _denied_by_asset(self) -> dict[str, list[dict[str, Any]]]:
        api = _permissions_api()
        denied: dict[str, list[dict[str, Any]]] = {}
        exposure = api.TOOL_EXPOSURE.get(SKILL_TOOL_KEY)
        if exposure is None:  # vocabulary drift: refuse, never assume
            raise mandatory_layer_unavailable(
                f"the published TOOL_EXPOSURE table has no {SKILL_TOOL_KEY!r} "
                "entry; Skills cannot guess an exposure class",
                reason="vocabulary drift")
        for ceiling in self._ceilings_in_force():
            for asset_id, entry in self._matching(ceiling.hard_denies):
                denied.setdefault(asset_id, []).append({
                    "policyId": ceiling.policy_id,
                    "ceilingRevision": ceiling.revision_digest,
                    "kind": "hard_deny",
                    "pattern": None if entry.target is None
                    else entry.target.pattern,
                })
            # The allow-max face: an allow on `skill` implies EXEC
            # (ceilings.py:78), so a strictly lower exposure bound denies every
            # skill in the catalogue — the API's own arithmetic, not ours.
            if ceiling.maximum_exposure.rank < exposure.rank:
                for asset_id in self._known_asset_ids():
                    denied.setdefault(asset_id, []).append({
                        "policyId": ceiling.policy_id,
                        "ceilingRevision": ceiling.revision_digest,
                        "kind": "maximum_exposure",
                        "pattern": None,
                        "maximumExposure": ceiling.maximum_exposure.value,
                    })
        return denied

    def _known_asset_ids(self) -> tuple[str, ...]:
        try:
            ids = self._asset_ids()
        except Exception as exc:  # noqa: BLE001 - catalogue outage is visible
            raise mandatory_layer_unavailable(
                f"the skill catalogue could not be listed: {exc}",
                reason="asset id source failed") from exc
        return tuple(str(item) for item in ids)


__all__ = [
    "MANDATORY_POLICY_CONFLICT", "MANDATORY_POLICY_UNAVAILABLE",
    "PERMISSIONS_AUTHORIZER_PORT", "SKILL_TOOL_KEY",
    "NotConfiguredMandatoryPolicyPort", "PermissionsCeilingMandatoryPolicyPort",
    "coerce_ceiling_source", "mandatory_layer_unavailable",
]
