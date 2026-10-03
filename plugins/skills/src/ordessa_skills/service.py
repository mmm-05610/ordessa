"""The one Skills domain service entity (docs/design/skills-v2/contracts.md).

Design pin: 生产实体只认一份 `SkillsService`. This object composes the three
owned areas — `library/` (records, revision store, approvals, import
transfer, catalog, diff), `assignments/` (store, authorization, resolution)
and `native_discovery/` — and is the single production entry the wire layer
(`plugin.py` / `wire.py`) and the provided `skills.service` port address.
No second service object, no test-only facade.

Scope facts are injected, never self-reported (contracts.md: 请求 principal/
serverScope 由鉴权注入，不接受自报 owner 或任意本地文件路径): the
constructor takes the server-side `server_scope` (this data root's instance
identity, api-requests.md §G5 独立路径) and the auth-derived `principal`
(the Server today has one data-root bearer → one local principal; the real
permissions-api arrival — §G6/Q5 — swaps the value, not the plumbing).

Read surfaces (`list/get/revisions/preview/diff/assignmentsList/resolve/
previewEffective/checkUpdate`) perform no writes — enforcement is
constructive (they only call read paths of the stores). Write surfaces
return at most ``effect: "stored"`` (the `api/evidence.py` ladder; nothing
here may claim `selected`→`projected`→`loaded`→`used` beyond its own proof).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from pacthold_runtime_compat.storage import Database

from .api import evidence
from .api.errors import AssetDomainError
from .assignments import (
    SCOPE_PROJECT,
    AssignmentError,
    AssignmentScope,
    AssetAuthorization,
    AssignmentStore,
    MandatoryPolicyPort,
    ProfileLayerPort,
    ResolverDeps,
    ResolutionTarget,
    SessionOverride,
    SkillsResolutionService,
)
from .assignments.model import DECISION_DISABLE, DECISION_ENABLE
from .assignments.ports import WorkspaceLookup
from .library import (
    AssetRecords,
    CatalogStore,
    ImportService,
    RevisionApprovalStore,
    SkillRevisionStore,
    asset_view,
    diff_revisions,
    preview_file,
    text_diff,
)
from .library.revisions import revision_view
from .mandatory_policy import (
    MANDATORY_POLICY_CONFLICT,
    NotConfiguredMandatoryPolicyPort,
)
from .profile_facet import NotConfiguredProfileLayerPort

#: The honest refusal codes this service raises for surfaces the platform
#: seams have not delivered yet (specs/011-q1-skills/api-requests.md).
NATIVE_TARGET_UNAVAILABLE = "NATIVE_TARGET_ROOT_UNAVAILABLE"
BRAND_MATRIX = "specs/011-q1-skills/research/brand-matrix.md"


class SkillsService:
    """One composition of library + assignments + native discovery.

    `assets_root` is a server-side directory under the injected data root;
    a client never names a path, only opaque ids (importId / assetId /
    workspaceId / sourceId).
    """

    def __init__(
        self, *,
        database: Database,
        assets_root: Path | str,
        server_scope: str,
        principal: str,
        workspace_lookup: WorkspaceLookup | None = None,
        profile_layer: ProfileLayerPort | None = None,
        mandatory_policy: MandatoryPolicyPort | None = None,
        profile_services: Any | None = None,
    ) -> None:
        if not server_scope or not principal:
            raise AssetDomainError(
                "SCOPE_INJECTION_MISSING",
                "server_scope and principal are injected by the auth layer, "
                "never derived from request params")
        self.database = database
        self.assets_root = Path(assets_root)
        self.server_scope = server_scope
        self.principal = principal

        self.store = SkillRevisionStore(self.assets_root)
        self.records = AssetRecords(database)
        self.approvals = RevisionApprovalStore(self.assets_root, store=self.store)
        self.imports = ImportService(self.assets_root, records=self.records,
                                     store=self.store)
        self.catalogs = CatalogStore(self.assets_root / "catalogs")
        self.assignments = AssignmentStore(
            database,
            scope=AssignmentScope(server_scope=server_scope, principal=principal),
            approvals=self.approvals,
        )
        self.authorization = AssetAuthorization(
            workspace_lookup=workspace_lookup, server_scope=server_scope)
        #: FR05's Profile wiring: when the composition hands us the real
        #: profile-api services (the `profile-api` checkpoint's
        #: `ProfilePluginServices`), the resolver's fifth layer reads the
        #: live `assets.skills` facet through `ProfileApiLayerPort`; an
        #: explicitly injected `profile_layer` wins over the derivation
        #: (test seams). With neither, the default port keeps §G3's openness
        #: a typed refusal instead of pretending the layer is empty-disabled
        #: (profile_facet module docstring owns the full note).
        if profile_layer is None and profile_services is not None:
            from .profile_contribution import ProfileApiLayerPort
            profile_layer = ProfileApiLayerPort(profile_services)
        self.profile_layer = profile_layer or NotConfiguredProfileLayerPort()
        #: FR05's twin for the non-overridable seventh layer: the composition
        #: supplies the permissions surface (`plugin.py` builds
        #: `PermissionsCeilingMandatoryPolicyPort` from the published
        #: `PolicyCeiling` read, or an explicit port wins); with neither, the
        #: layer is present but explicitly UNREADABLE, which is a typed status
        #: on every resolve view and every assignment write — never "no
        #: constraints apply" (mandatory_policy.py module docstring).
        self.mandatory_policy = mandatory_policy or \
            NotConfiguredMandatoryPolicyPort()
        self.resolution = SkillsResolutionService(ResolverDeps(
            assignments=self.assignments,
            revisions=self.store,
            approvals=self.approvals,
            authorization=self.authorization,
            profile=self.profile_layer,
            mandatory=self.mandatory_policy,
            capability_lookup=None,
        ))

    # -- lifecycle ------------------------------------------------------------

    def ensure_schema(self) -> None:
        """Host start hook: create the domain-owned assignment tables.

        Idempotent per store docstring; the shared `server_assets` rows come
        from the pacthold migration chain the host has already run.
        """
        self.assignments.ensure_schema()

    # -- read surfaces (no writes) -------------------------------------------

    def list_assets(self) -> dict[str, Any]:
        rows = self.records.list(kind="skill")
        return {"items": [asset_view(row) for row in rows], "nextCursor": None}

    def get_asset(self, asset_id: str) -> dict[str, Any]:
        row = self.records.get(asset_id)
        view = asset_view(row)
        revision = int(row["latest_revision"])
        view["latestRevisionDetail"] = revision_view(
            self.store, asset_id=asset_id, revision=revision,
            records=self.records, approvals=self.approvals)
        return view

    def list_revisions(self, asset_id: str) -> dict[str, Any]:
        """Every installed revision with its approval fact (the catalogue
        lists unapproved revisions honestly — visibility, not filtering)."""
        self.records.get(asset_id)  # typed refusal for an unknown asset
        items = []
        for row in self.store.list_revisions(asset_id):
            revision = int(row["revision"])
            items.append({
                "revision": revision,
                "treeDigest": row.get("tree_digest") or row.get("digest"),
                "approvalRecord": self.approvals.approval_for(asset_id, revision),
            })
        return {"assetId": asset_id, "items": items}

    def preview(self, asset_id: str, revision: int, path: str) -> dict[str, Any]:
        return preview_file(self.store, asset_id=asset_id, revision=revision,
                            path=path)

    def diff(self, asset_id: str, from_revision: int, to_revision: int,
             path: str | None = None) -> dict[str, Any]:
        result = diff_revisions(self.store, asset_id=asset_id,
                                from_revision=from_revision, to_revision=to_revision)
        if path is not None:
            result["textDiff"] = text_diff(
                self.store, asset_id=asset_id, from_revision=from_revision,
                to_revision=to_revision, path=path)
        return result

    def assignments_list(self, *, scope_kind: str | None = None,
                         scope_id: str | None = None,
                         harness_key: str | None = None,
                         asset_id: str | None = None) -> dict[str, Any]:
        return {"items": self.assignments.list(
            scope_kind=scope_kind, scope_id=scope_id,
            harness_key=harness_key, asset_id=asset_id)}

    # -- import transfer (commit is the only publish point) -------------------

    def import_begin(self, *, files: list[dict[str, Any]],
                     total_bytes: int) -> dict[str, Any]:
        result = self.imports.begin(request_id="wire", files=files,
                                    total_bytes=total_bytes)
        return {**result, "effect": evidence.STORED}

    def import_chunk(self, import_id: str, *, index: int, payload: bytes,
                     sha256: str) -> dict[str, Any]:
        return self.imports.chunk(import_id, index=index, payload=payload,
                                  sha256=sha256)

    def import_preview(self, import_id: str, source: Mapping[str, Any]) -> dict[str, Any]:
        return self.imports.prepare(import_id, source=dict(source))

    def import_commit(self, import_id: str, *, asset_id: str,
                      revision: int) -> dict[str, Any]:
        result = self.imports.commit(import_id, asset_id=asset_id, revision=revision)
        # commit stores content; the effect caps at `stored` (evidence.py —
        # installation never implies selected/projected/loaded/used).
        result.setdefault("effect", evidence.STORED)
        return result

    def import_cancel(self, import_id: str) -> dict[str, Any]:
        self.imports.abort(import_id)
        return {"cancelled": True, "importId": import_id}

    # -- sources / approvals ---------------------------------------------------

    def check_update(self, source_id: str) -> dict[str, Any]:
        """Fixed-source update check (更新先看变更): re-read the source the
        last sync recorded and compare digests.

        The path is the snapshot's own server-side `source_path` fact — the
        request carries only the opaque `sourceId` (no client path). Remote
        fetch of a fixed git source is not available in this build; the
        server-recorded local source stays the honest seam.
        """
        snapshot = self.catalogs.snapshot(source_id)
        if snapshot is None:
            raise AssetDomainError(
                "SOURCE_UNKNOWN", "no server snapshot for that source id",
                detail=source_id)
        fresh = self.catalogs.sync(source_id=source_id,
                                   source_path=snapshot["source_path"])
        installed = {
            f"skill:{row['name']}": row.get("digest")
            for row in self.records.list(kind="skill")
        }
        return {
            "sourceId": source_id,
            "changed": str(fresh.get("digest")) != str(snapshot.get("digest")),
            "previousDigest": snapshot.get("digest"),
            "digest": fresh.get("digest"),
            "entries": self.catalogs.annotate(fresh, installed=installed),
        }

    def approve_revision(self, *, asset_id: str, revision: int,
                         approved_by: str,
                         expected_digest: str | None) -> dict[str, Any]:
        """Approving adds a local approval fact; it moves no binding, no
        assignment and no session (README §内容修订与使用修订)."""
        record = self.approvals.approve(
            asset_id=asset_id, revision=revision, approved_by=approved_by,
            expected_digest=expected_digest)
        return {"approval": record, "effect": evidence.STORED}

    # -- assignments (CAS + idempotency, server-injected scope) -----------------

    def upsert_assignment(
        self, *, scope_kind: str, scope_id: str, harness_id: str | None,
        asset_id: str, decision: str, revision: int | None,
        expected_version: int | None, operation_key: str | None,
    ) -> dict[str, Any]:
        if scope_kind == SCOPE_PROJECT:
            # G07: a fabricated projectId is a typed refusal before any write,
            # answered by the injected workspace registry, never by the client.
            self.authorization.authorize_project(scope_id)
        mandatory_status = self._assert_mandatory_compatible(
            scope_kind=scope_kind, scope_id=scope_id, harness_id=harness_id,
            asset_id=asset_id, decision=decision)
        view = self.assignments.upsert(
            scope_kind=scope_kind, scope_id=scope_id, harness_id=harness_id,
            asset_id=asset_id, decision=decision, revision=revision,
            expected_version=expected_version, operation_key=operation_key)
        return {"assignment": view, "effect": evidence.STORED,
                "mandatoryPolicy": mandatory_status}

    def _assert_mandatory_compatible(
        self, *, scope_kind: str, scope_id: str, harness_id: str | None,
        asset_id: str, decision: str) -> dict[str, Any]:
        """The write-edge of the seventh layer (G06 管理员强制规则被覆盖).

        Skills still decides no policy: it asks the injected mandatory port
        what the administrator published for this target and refuses an
        `enable` the ceiling hard-denies, instead of storing a row the resolver
        would later contradict (a stored-then-never-applied row is the
        "fake green" contracts.md names). The returned dict is the layer's own
        `layer_status()` and always travels in the response, so an UNREADABLE
        layer is visible in the write answer too — the write is not thereby
        treated as safe, it is recorded as "not checked" (see
        `NotConfiguredMandatoryPolicyPort`: a composition without
        permissions-api is the documented state of this tree, not a proof of
        compliance).
        """
        port = self.mandatory_policy
        describe = getattr(port, "layer_status", None)
        status = dict(describe()) if callable(describe) else {
            # A port supplied without a status surface (an older injected
            # fake): say which port answered, never imply "no constraint".
            "status": "unknown",
            "reason": f"{type(port).__name__} supplies no layer_status()",
        }
        if getattr(port, "unavailable_reason", None):
            return {**status, "checked": False}
        project_id = scope_id if scope_kind == SCOPE_PROJECT else None
        supplied = port.rules(principal=self.principal, project_id=project_id,
                              harness_id=harness_id)
        covered: dict[str, Any] = {}
        for rule in supplied:
            if rule.asset_id in covered:
                # the same duplication the resolver refuses (ASSIGNMENT_DUPLICATE):
                # two mandatory rules for one asset is an unreadable policy set
                raise AssignmentError(
                    "ASSIGNMENT_DUPLICATE",
                    "two mandatory policy rules name the same asset",
                    detail=rule.asset_id)
            covered[rule.asset_id] = rule
        rule = covered.get(asset_id)
        if rule is not None and rule.decision == DECISION_DISABLE \
                and decision == DECISION_ENABLE:
            raise AssetDomainError(
                MANDATORY_POLICY_CONFLICT,
                f"the mandatory policy layer denies {asset_id} for this "
                "target; an enable assignment is refused rather than stored "
                "against a constraint the resolver cannot override",
                detail=asset_id)
        return {**status, "checked": True,
                "mandatoryDecisionForAsset": None if rule is None
                else rule.decision}

    def remove_assignment(
        self, *, scope_kind: str, scope_id: str, harness_id: str | None,
        asset_id: str, expected_version: int | None, operation_key: str | None,
    ) -> dict[str, Any]:
        if scope_kind == SCOPE_PROJECT:
            self.authorization.authorize_project(scope_id)
        view = self.assignments.remove(
            scope_kind=scope_kind, scope_id=scope_id, harness_id=harness_id,
            asset_id=asset_id, expected_version=expected_version,
            operation_key=operation_key)
        return {"removed": view, "effect": evidence.STORED}

    # -- resolution (read-only; ONE shared algorithm) ---------------------------

    def resolve(self, *, project_id: str | None, harness_id: str | None,
                profile_id: str | None, session_ref: str,
                runtime_generation: int,
                session_overrides: Sequence[SessionOverride]) -> dict[str, Any]:
        """resolve + previewEffective: identical call into the resolver, so
        the query answer and the per-commit plan can never disagree.

        The returned view carries provenance (`selectedBy` per item), the
        excluded set, absence diagnostics and the row versions read — the
        unknown layers stay visible instead of being filtered (G05/G10).
        """
        target = ResolutionTarget(
            project_id=project_id, harness_id=harness_id, profile_id=profile_id,
            session_ref=session_ref, session_overrides=tuple(session_overrides),
            runtime_generation=runtime_generation)
        return self.resolution.effective(target).view()

    # -- delivery (T14/G19: the producer side of agent-box.skill@1) ------------

    def freeze_snapshot(self, *, project_id: str | None, harness_id: str | None,
                        profile_id: str | None, session_ref: str,
                        runtime_generation: int,
                        session_overrides: Sequence[SessionOverride]):
        """Freeze the ONE shared resolution into the apply-side snapshot
        (FR08); the delivery preflight below pins exactly this face."""
        from .assignments.snapshot import build_snapshot
        target = ResolutionTarget(
            project_id=project_id, harness_id=harness_id, profile_id=profile_id,
            session_ref=session_ref, session_overrides=tuple(session_overrides),
            runtime_generation=runtime_generation)
        return build_snapshot(self.resolution.effective(target))

    def delivery_set(self, *, harness_id: str, project_id: str | None = None,
                     profile_id: str | None = None, session_ref: str = "",
                     runtime_generation: int = 0,
                     session_overrides: Sequence[SessionOverride] = (),
                     harness_definition: Any | None = None,
                     skill_input_maximum: int | None = None,
                     observed_native_version: str | None = None,
                     observed_native_names: Sequence[str] = ()):
        """The delivery operation on the frozen snapshot: freeze, preflight
        every fail-closed rule, and hand the Harness the verified
        ``agent-box.skill@1`` resolved-input set (producer.py; contracts.md
        §Harness 配置贡献). A refusal raises a typed error and yields zero
        partial delivery objects; a returned set grades at most
        `projected` once composed — never `loaded`/`used`."""
        from .harness_adapters.producer import build_skill_delivery
        snapshot = self.freeze_snapshot(
            project_id=project_id, harness_id=harness_id,
            profile_id=profile_id, session_ref=session_ref,
            runtime_generation=runtime_generation,
            session_overrides=session_overrides)
        return build_skill_delivery(
            snapshot=snapshot, store=self.store, approvals=self.approvals,
            harness_id=harness_id, harness_definition=harness_definition,
            skill_input_maximum=skill_input_maximum,
            observed_native_version=observed_native_version,
            observed_native_names=observed_native_names,
            resolution_service=self.resolution,
            target=ResolutionTarget(
                project_id=project_id, harness_id=harness_id,
                profile_id=profile_id, session_ref=session_ref,
                session_overrides=tuple(session_overrides),
                runtime_generation=runtime_generation))

    # -- native surfaces (honest unknowns, never silent success) ----------------

    def discover_native(self, harness_id: str) -> dict[str, Any]:
        """The observation itself (`native_discovery.observe_native_skills`)
        is real and bounded — but the *authorized guest/instance root* it
        may read has no plugin-queryable published seam: the merged
        harness-api (`ordessa_harness_api`, d3f026904e) hands target
        handles to the ADAPTER at apply time only, and exposes no read
        port for this composition (api-requests.md §G2's read half stays
        open; the wire availability predicate cites it). Refusing with a
        type is the honest answer; scanning `$HOME` or a client-supplied
        path would violate both G11 and FR09, and an empty list would be
        the silent-filter fake success contracts.md forbids
        (不可用不以静默过滤达成"成功")."""
        raise AssetDomainError(
            NATIVE_TARGET_UNAVAILABLE,
            "native discovery needs the harness-owned authorized instance "
            "root; that seam is api-requests.md §G2 and not composed yet",
            detail=harness_id)

    def invoke_descriptor(self, harness_id: str) -> dict[str, Any]:
        """No brand's explicit-invocation route is verified, so nothing is
        offered as invocable: browse-only, evidence `unknown`, citing the
        frozen brand matrix (research/brand-matrix.md §2 and §6)."""
        from .harness_adapters.capabilities import pin_for, statement_for

        statement = statement_for(harness_id)
        pin = pin_for(harness_id)
        return {
            "harnessId": harness_id,
            "invocation": "unknown",
            "browseOnly": True,
            "reason": "no verified explicit-invocation route for this brand",
            "citation": BRAND_MATRIX,
            "versionPin": None if pin is None else str(pin),
            "offeredCapabilityAxes": list(statement.offered_axes()),
        }


__all__ = ["SkillsService", "NATIVE_TARGET_UNAVAILABLE", "BRAND_MATRIX"]
