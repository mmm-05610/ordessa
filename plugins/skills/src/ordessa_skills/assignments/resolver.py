"""The deterministic six-layer resolver (FR04/FR06/FR08; data-model.md
§解析顺序; verification.md G05/G06/G07).

The one order, low to high, that no native folder depth may change
(FR06: 按确定顺序解析，不因 native 文件夹层级改变 Ordessa 的覆盖语义 —
this module never looks at a file path at all; a skill's internal tree
layout is not an input and provably cannot reorder anything, see
tests/test_assignments_resolution.py)::

    user-global/any → user-global/harness → project/any → project/harness
    → profile → session override

Semantics implemented literally (data-model.md):

* a layer without an entry for the assetId **inherits** (keeps the previous
  state) — inherit is the absence, never a stored disable
  (G06 「inherit 被当 disable」);
* ``enable(revision)`` overrides both prior state AND revision;
* ``disable`` excludes;
* on top of all six sits the non-overridable admin policy layer
  (:class:`~ordessa_skills.assignments.ports.MandatoryPolicyPort`,
  G06 「管理员强制规则被覆盖」).

ONE function — :func:`resolve_effective` — computes the result; both the
read-only preview (``resolve/previewEffective``) and the per-commit plan
enter through :class:`SkillsResolutionService`, which funnels both into
:meth:`SkillsResolutionService.effective` (contracts.md: 查询与每次提交的
plan 共享同一解析算法). The sharing is proven in
tests/test_assignments_snapshot.py by call-counting that single method.

All assignment rows and asset rows are read inside ONE SQLite transaction,
so the row versions the result reports are one consistent snapshot
(FR08's freeze needs no torn reads). Cross-domain Profile state is read
through the injected port outside that transaction — data-model.md is
explicit that 跨业务 DB 无伪造原子性 and staleness is caught later by
:func:`ordessa_skills.assignments.snapshot.matches_frozen`.

Refusals are typed (引用缺失、版本未批准等为类型化拒绝;
不可用不以静默过滤达成"成功"): unknown workspace, unknown/harness-mismatched
profile, unknown asset reference, foreign-owned content, missing or
unapproved revision all raise; none of them filters an item out quietly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from ..api.evidence import SELECTED, attest
from .authorization import AssetAuthorization, origin_of
from .model import (
    ANY_HARNESS,
    DECISION_DISABLE,
    DECISION_ENABLE,
    LAYER_MANDATORY,
    LAYER_ORDER,
    LAYER_PROFILE,
    LAYER_PROJECT_ANY,
    LAYER_PROJECT_HARNESS,
    LAYER_SESSION_OVERRIDE,
    LAYER_USER_GLOBAL_ANY,
    LAYER_USER_GLOBAL_HARNESS,
    SCOPE_PROJECT,
    SCOPE_USER_GLOBAL,
    AssignmentError,
    SkillAssignment,
)
from .ports import (
    MandatoryPolicyPort,
    MandatoryRule,
    ProfileLayerPort,
    RevisionGate,
    SessionOverride,
)
from .store import ASSIGNMENTS_TABLE, AssignmentStore


def _db_layer(row_scope_kind: str, row_scope_id: str, row_harness_key: str,
              target: "ResolutionTarget") -> str | None:
    """Which of the four DB layers one stored row belongs to for this
    target — or None when the row is not part of the target's chain
    (another project's rows never leak in, G05; another brand's harness
    rows become an absence diagnostic instead of vanishing silently)."""
    harness = None if row_harness_key == ANY_HARNESS else row_harness_key
    if row_scope_kind == SCOPE_USER_GLOBAL:
        if harness is None:
            return LAYER_USER_GLOBAL_ANY
        return LAYER_USER_GLOBAL_HARNESS if harness == target.harness_id else None
    if row_scope_kind == SCOPE_PROJECT:
        if row_scope_id != (target.project_id or ""):
            return None
        return LAYER_PROJECT_ANY if harness is None else (
            LAYER_PROJECT_HARNESS if harness == target.harness_id else None)
    return None


@dataclass(frozen=True)
class ResolutionTarget:
    """The authorized target of one resolution (contracts.md: 输入已授权
    target(project/harness/profile)). Identity values, never paths."""

    project_id: str | None = None
    harness_id: str | None = None
    profile_id: str | None = None
    session_ref: str = ""
    #: layer 6 — the session's pending item overrides, supplied per call by
    #: the existing Profile session-item mechanism (ports.py, Z1 G3(b)).
    session_overrides: tuple[SessionOverride, ...] = ()
    runtime_generation: int = 0

    def view(self) -> dict[str, Any]:
        return {
            "projectId": self.project_id,
            "harnessId": self.harness_id,
            "profileId": self.profile_id,
            "sessionRef": self.session_ref,
            "runtimeGeneration": self.runtime_generation,
        }


@dataclass
class ResolverDeps:
    assignments: AssignmentStore
    revisions: Any                 # SkillRevisionStore (digest of a revision)
    approvals: RevisionGate        # resolve-time installed+approved check
    authorization: AssetAuthorization
    profile: ProfileLayerPort | None = None
    mandatory: MandatoryPolicyPort | None = None
    #: brand capability lookup; defaults to the domain capability registry
    capability_lookup: Callable[[str], Any] | None = None


@dataclass(frozen=True)
class Resolution:
    included: tuple[dict[str, Any], ...]
    excluded: tuple[dict[str, Any], ...]
    diagnostics: tuple[dict[str, Any], ...]
    #: layer_key joined with "|" → row_version, the versions actually read;
    #: frozen verbatim into the snapshot (FR08/G18).
    assignment_revisions: Mapping[str, int]
    profile_revision: Mapping[str, Any] | None
    target: ResolutionTarget
    server_scope: str
    principal: str

    def view(self) -> dict[str, Any]:
        """The wire/preview projection (camelCase, no host paths)."""
        return {
            "target": self.target.view(),
            "serverScope": self.server_scope,
            "resolvedSkills": [dict(item) for item in self.included],
            "excludedSkills": [dict(item) for item in self.excluded],
            "diagnostics": [dict(item) for item in self.diagnostics],
            "assignmentRevisions": dict(self.assignment_revisions),
            "profileRevision": (dict(self.profile_revision)
                                if self.profile_revision else None),
        }


def _validate_override(asset_id: str, decision: str, revision: int | None,
                       code: str) -> None:
    """The tri-state row rules mirror SkillAssignment for injected inputs:
    enable records a revision, disable records none (data-model.md)."""
    if decision == DECISION_ENABLE and (not isinstance(revision, int) or revision < 1):
        raise AssignmentError(code, f"an enable entry for {asset_id} needs a revision")
    if decision == DECISION_DISABLE and revision is not None:
        raise AssignmentError(code, f"a disable entry for {asset_id} carries no revision")


def _load_asset_rows(conn, asset_ids: Sequence[str]) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for asset_id in asset_ids:
        row = conn.execute(
            "SELECT * FROM server_assets WHERE id=?", (asset_id,)).fetchone()
        rows[asset_id] = dict(row) if row is not None else None
    return rows


class SkillsResolutionService:
    """The single consumer seam: preview AND per-commit plan both call
    :meth:`effective` — the ONE shared algorithm instance contracts.md
    requires. (The test proves it by counting calls into `effective` while
    both entry points run; neither path re-implements the walk.)

    Note the deliberate absence of any apply/project method: applying a
    plan is blocked on C0's harness-api (api-requests.md §G2) and faking a
    projection here would be exactly the "controlled tests must not fake
    green" failure (AGENTS.md rule 9)."""

    def __init__(self, deps: ResolverDeps) -> None:
        self.deps = deps

    def effective(self, target: ResolutionTarget) -> Resolution:
        return resolve_effective(self.deps, target)

    def preview_effective(self, target: ResolutionTarget) -> dict[str, Any]:
        """resolve/previewEffective: read-only, no writes."""
        return self.effective(target).view()

    def commit_plan(self, target: ResolutionTarget) -> dict[str, Any]:
        """The per-commit pure-decision plan (contracts.md §Harness 配置贡
        献 payload: assetId/revision/treeDigest bound to
        runtimeGeneration/projectId/profileRevision/assignment versions).
        Freezing uses the SAME :meth:`effective` result — see snapshot.py."""
        from . import snapshot as _snapshot  # late: snapshot imports resolver
        resolution = self.effective(target)
        frozen = _snapshot.build_snapshot(resolution)
        return {
            "snapshot": frozen.view(),
            "plan": [
                {
                    "assetId": item["assetId"],
                    "revision": item["revision"],
                    "treeDigest": item["treeDigest"],
                    "selectedBy": dict(item["selectedBy"]),
                }
                for item in resolution.included
            ],
            "runtimeGeneration": target.runtime_generation,
            "projectId": target.project_id,
            "profileRevision": (dict(resolution.profile_revision)
                                if resolution.profile_revision else None),
            "assignmentRevisions": dict(resolution.assignment_revisions),
        }


def resolve_effective(deps: ResolverDeps, target: ResolutionTarget) -> Resolution:
    """THE shared algorithm — :class:`SkillsResolutionService` is its only
    intended caller; direct use is allowed for tooling and tests.

    Steps, in order: authorize the target identities; read every layer's
    rows and asset rows in ONE transaction; run the six-layer walk plus
    the non-overridable policy layer; grade evidence and re-apply the
    approval gate to every final enable; return the resolution with the
    row versions used.
    """
    store = deps.assignments
    scope = store.scope

    if target.project_id is not None:
        deps.authorization.authorize_project(target.project_id)

    # ---- profile layer (injected port; a Profile's harness is fixed) ----
    profile_entries: dict[str, dict[str, Any]] = {}
    profile_revision: Mapping[str, Any] | None = None
    if target.profile_id is not None:
        if deps.profile is None:
            raise AssignmentError(
                "PROFILE_UNKNOWN",
                "a profile target needs the ProfileLayerPort injected "
                "(api-requests.md §G3)")
        profile_harness = deps.profile.harness_id(target.profile_id)
        if profile_harness is None:
            raise AssignmentError(
                "PROFILE_UNKNOWN", "the profile does not resolve",
                detail=target.profile_id)
        if target.harness_id is not None and profile_harness != target.harness_id:
            raise AssignmentError(
                "PROFILE_HARNESS_MISMATCH",
                f"profile {target.profile_id} belongs to harness "
                f"{profile_harness!r}, not {target.harness_id!r} "
                "(Profile 只属于自己的 Harness)", detail=target.profile_id)
        for entry in deps.profile.skill_entries(target.profile_id):
            _validate_override(entry.asset_id, entry.decision, entry.revision,
                               "ASSIGNMENT_INVALID")
            # an explicit `inherit` is kept: it never changes the state,
            # but it is the layer's own value for the 本层设置 display and
            # makes the asset appear with an "absent" diagnostic shape.
            profile_entries[entry.asset_id] = {
                "decision": entry.decision, "revision": entry.revision,
                "scopeKind": "profile", "scopeId": target.profile_id,
                "harnessId": profile_harness, "rowVersion": None,
            }
        profile_revision = deps.profile.revision_identity(target.profile_id)

    session_entries: dict[str, dict[str, Any]] = {}
    for override in target.session_overrides:
        _validate_override(override.asset_id, override.decision,
                           override.revision, "SESSION_OVERRIDE_INVALID")
        session_entries[override.asset_id] = {
            "decision": override.decision, "revision": override.revision,
            "scopeKind": "session", "scopeId": target.session_ref,
            "harnessId": target.harness_id, "rowVersion": None,
        }

    # ---- ONE transaction: assignment rows, asset rows, row versions ----
    with store.database.read() as conn:
        conn.execute("BEGIN")  # explicit read snapshot (no torn layer reads)
        try:
            rows = conn.execute(
                f"SELECT * FROM {ASSIGNMENTS_TABLE} "
                "WHERE server_scope=? AND principal=? "
                "ORDER BY scope_kind, scope_id, harness_key, asset_id",
                (scope.server_scope, scope.principal)).fetchall()
            layers: dict[str, dict[str, dict[str, Any]]] = {
                name: {} for name in LAYER_ORDER}
            assignment_revisions: dict[str, int] = {}
            other_harness: dict[str, set[str]] = {}
            for row in rows:
                layer = _db_layer(row["scope_kind"], row["scope_id"],
                                  row["harness_key"], target)
                assignment = SkillAssignment.from_row(row)
                if layer is None:
                    if (row["scope_kind"] == SCOPE_USER_GLOBAL
                            or row["scope_id"] == (target.project_id or "")):
                        other_harness.setdefault(assignment.asset_id, set()).add(
                            row["harness_key"])
                    continue
                layers[layer][assignment.asset_id] = {
                    "decision": assignment.decision,
                    "revision": assignment.revision,
                    "scopeKind": assignment.scope_kind,
                    "scopeId": assignment.scope_id,
                    "harnessId": assignment.harness_id,
                    "rowVersion": assignment.row_version,
                }
                assignment_revisions["|".join(
                    str(part) for part in assignment.layer_key)] = \
                    assignment.row_version
            seen_assets = sorted(
                {asset_id for layer_map in layers.values()
                 for asset_id in layer_map}
                | set(profile_entries) | set(session_entries))
            asset_rows = _load_asset_rows(conn, seen_assets)
        finally:
            conn.execute("COMMIT")

    # ---- mandatory policy layer (the non-overridable seventh layer) ----
    #: Layer-state facts that are not per-asset outcomes: they ride in the
    #: same diagnostics list so an unreadable layer is never read as "the
    #: administrator published nothing" (G06 反例 + 不可用不以静默过滤达成"成功").
    policy_diagnostics: list[dict[str, Any]] = []
    mandatory_rules: dict[str, MandatoryRule] = {}
    if deps.mandatory is not None:
        _reason = getattr(deps.mandatory, "unavailable_reason", None)
        if _reason:
            # NotConfiguredMandatoryPolicyPort: the layer contributed no rule
            # because it was never readable. Say so on every resolution.
            policy_diagnostics.append({
                "kind": "mandatory_policy_unavailable", "reason": str(_reason)})
        for rule in deps.mandatory.rules(principal=scope.principal,
                                         project_id=target.project_id,
                                         harness_id=target.harness_id):
            if rule.asset_id in mandatory_rules:
                raise AssignmentError(
                    "ASSIGNMENT_DUPLICATE",
                    "two mandatory policy rules name the same asset",
                    detail=rule.asset_id)
            if rule.asset_id not in seen_assets:
                with store.database.read() as conn:
                    asset_rows[rule.asset_id] = _load_asset_rows(
                        conn, [rule.asset_id])[rule.asset_id]
                seen_assets = sorted(set(seen_assets) | {rule.asset_id})
            mandatory_rules[rule.asset_id] = rule

        # The ceiling's approval-required face is reflected, never enforced
        # here: Skills does not own the execution gate (permissions-api's own
        # ruling type is PendingApproval), and turning an approval requirement
        # into a disable would be Skills inventing policy. It is recorded so
        # previewEffective shows the constraint the admin published.
        approval_required = getattr(deps.mandatory, "approval_required", None)
        if callable(approval_required):
            for item in approval_required(principal=scope.principal,
                                          project_id=target.project_id,
                                          harness_id=target.harness_id):
                row = {"kind": "mandatory_approval_required"}
                row.update(dict(item))
                policy_diagnostics.append(row)

    # ---- the deterministic walk ----
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = list(policy_diagnostics)

    for asset_id in seen_assets:
        state: dict[str, Any] | None = None      # None == inherit-so-far
        deciding_layer: str | None = None
        last_enable: tuple[int, str] | None = None  # (revision, layer) seen
        forced_in = False
        chain: list[dict[str, Any]] = []
        for layer in LAYER_ORDER:
            if layer == LAYER_PROFILE:
                entry = profile_entries.get(asset_id)
            elif layer == LAYER_SESSION_OVERRIDE:
                entry = session_entries.get(asset_id)
            else:
                entry = layers[layer].get(asset_id)
            if entry is None:
                chain.append({"layer": layer, "decision": "inherit",
                              "revision": None, "rowVersion": None})
                continue
            chain.append({
                "layer": layer, "decision": entry["decision"],
                "revision": entry["revision"],
                "scopeKind": entry["scopeKind"], "scopeId": entry["scopeId"],
                "harnessId": entry["harnessId"],
                "rowVersion": entry.get("rowVersion"),
            })
            if entry["decision"] == "inherit":
                # explicit inherit at this layer: recorded as the layer's
                # own value, and the state simply carries on (inherit is
                # never a disable — G06).
                continue
            # Every reference passes the ownership check at its own layer:
            # a foreign or unknown asset referenced ANYWHERE is a typed
            # refusal, never a filtered-out item (G07).
            deps.authorization.assert_usable(
                asset_id=asset_id, asset_row=asset_rows[asset_id],
                via_layer=layer, project_id=target.project_id,
                profile_id=target.profile_id)
            state = entry
            deciding_layer = layer
            if entry["decision"] == DECISION_ENABLE:
                last_enable = (int(entry["revision"]), layer)

        rule = mandatory_rules.get(asset_id)
        if rule is not None:
            prior = state["decision"] if state is not None else "inherit"
            deps.authorization.assert_usable(
                asset_id=asset_id, asset_row=asset_rows[asset_id],
                via_layer=LAYER_MANDATORY, project_id=target.project_id,
                profile_id=target.profile_id)
            if rule.decision == DECISION_ENABLE:
                # The policy forces INCLUSION. With a pinned revision it also
                # pins it; without one, the last revision an overridable
                # layer selected stands — and if nothing ever selected one,
                # that is a typed refusal, not a guess.
                revision = rule.revision
                if revision is None:
                    if last_enable is None:
                        raise AssignmentError(
                            "ASSIGNMENT_INVALID",
                            "a mandatory enable rule pins no revision and no "
                            "lower layer selected one", detail=asset_id)
                    revision = last_enable[0]
                    forced_in = True
                else:
                    forced_in = state is None or \
                        state["decision"] != DECISION_ENABLE
                state = {"decision": DECISION_ENABLE, "revision": revision,
                         "scopeKind": None, "scopeId": None,
                         "harnessId": None, "rowVersion": None}
                deciding_layer = LAYER_MANDATORY
            else:
                state = {"decision": DECISION_DISABLE, "revision": None,
                         "scopeKind": None, "scopeId": None,
                         "harnessId": None, "rowVersion": None}
                deciding_layer = LAYER_MANDATORY
            chain.append({"layer": LAYER_MANDATORY, "decision": rule.decision,
                          "revision": rule.revision, "rowVersion": None})
            if prior != rule.decision and prior != "inherit":
                diagnostics.append({
                    "kind": "mandatory_policy_applied", "assetId": asset_id,
                    "priorState": prior, "policyDecision": rule.decision})

        asset_row = asset_rows[asset_id]
        origin_scope, origin_owner = origin_of(
            asset_row["source"] if asset_row is not None else None)

        if state is not None and state["decision"] == DECISION_ENABLE:
            revision = int(state["revision"])
            # resolve-time approval gate: a revision that lost its approval
            # or drifted since the write is refused, never filtered (G06).
            deps.approvals.assert_usable_for_assignment(asset_id, revision)
            digest = deps.revisions.revision_digest(asset_id=asset_id,
                                                    revision=revision)
            selected_by = {
                "layer": deciding_layer,
                "scopeKind": state.get("scopeKind"),
                "scopeId": state.get("scopeId"),
                "harnessId": state.get("harnessId"),
                "rowVersion": state.get("rowVersion"),
            }
            if rule is not None and rule.decision == DECISION_ENABLE and forced_in:
                selected_by["forcedBy"] = LAYER_MANDATORY
                if rule.revision is None and last_enable is not None:
                    selected_by["revisionSourceLayer"] = last_enable[1]
            included.append({
                "assetId": asset_id,
                "revision": revision,
                "nativeName": asset_row["name"],
                "description": asset_row["description"],
                "treeDigest": digest,
                "originScope": origin_scope,
                "originOwner": origin_owner,
                "selectedBy": selected_by,
                "excludedBy": None,
                # 本层设置 vs 最终结果 (ux.md §Settings): every layer's own
                # value rides alongside the decided outcome.
                "layerDecisions": chain,
                "capabilityEvidence": _capability_evidence(deps, target),
            })
        elif state is not None:      # final state is a disable
            excluded.append({
                "assetId": asset_id,
                "excludedBy": {
                    "layer": deciding_layer,
                    "scopeKind": state.get("scopeKind"),
                    "scopeId": state.get("scopeId"),
                    "harnessId": state.get("harnessId"),
                    "rowVersion": state.get("rowVersion"),
                },
                "layerDecisions": chain,
            })
        else:
            # inherit at every layer: absent, with the reason on record —
            # the resolution keeps disable and never-enabled distinguishable
            # so inherit≠disable is visible (G06).
            excluded.append({"assetId": asset_id,
                            "excludedBy": None,
                            "absentReason": "not_enabled",
                            "layerDecisions": chain})

    for asset_id, harnesses in sorted(other_harness.items()):
        diagnostics.append({
            "kind": "other_harness_scope", "assetId": asset_id,
            "harnesses": sorted(harnesses),
            "note": "assignments exist for other harness scopes; the "
                    "target harness has none of its own at that layer"})

    included.sort(key=lambda item: item["assetId"])
    excluded.sort(key=lambda item: item["assetId"])
    return Resolution(
        included=tuple(included),
        excluded=tuple(excluded),
        diagnostics=tuple(diagnostics),
        assignment_revisions=dict(assignment_revisions),
        profile_revision=dict(profile_revision) if profile_revision else None,
        target=target,
        server_scope=scope.server_scope,
        principal=scope.principal,
    )


def _capability_evidence(deps: ResolverDeps,
                         target: ResolutionTarget) -> dict[str, Any]:
    """The effect level is what this resolution can prove (`selected` —
    proof: the assignment decision itself). Brand matrix cells come from
    the domain registry and stay `unknown` when no evidence was ever
    registered (G10, contracts.md 可用性最少区分; no silent upgrade)."""
    effect = attest(SELECTED, proofs=("assignment_decision",))
    lookup = deps.capability_lookup
    if lookup is None:
        from ..harness_adapters.capabilities import statement_for as lookup
    statement = None
    if target.harness_id is not None:
        try:
            statement = lookup(target.harness_id)
        except Exception:  # unregistered brand == unknown, never a crash
            statement = None
    value = getattr(statement, "value", None)
    return {
        "effect": effect,
        "discovery": value("discovery_mechanism") if callable(value) else "unknown",
        "isolation": value("isolation") if callable(value) else "unknown",
    }
