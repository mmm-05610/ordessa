"""The domain service: content, revisions, assignments, expansion, import.

A pure orchestration over :class:`TemplateStore`, the closed renderer and the
receipt ledger. It performs no spawn, no model call, no recursive project scan
and no HOME read; principal is a required argument the caller's authenticated
context supplies, and every read/write enforces ownership or scope so a body is
never handed cross-owner (FR-11). It runs with Profile, Chat and Harness all
absent — that is the point of keeping storage, parsing and rendering in-domain.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Optional, Sequence

from . import importer
from .receipts import ReceiptLedger
from .store import TemplateStore
from ..api.dto import (
    Assignment,
    ExpansionReceipt,
    ParameterSpec,
    Target,
    Template,
    TemplateRevision,
)
from ..api.errors import (
    ContentMissingError,
    ContributorGoneError,
    RevisionUnapprovedError,
    StalePreviewError,
    UnauthorizedTargetError,
)
from ..assignments.resolver import OrgPolicy, Resolution, resolve_effective
from ..expansion.digest import arguments_digest, revision_digest
from ..expansion.parser import parse
from ..expansion.renderer import ProjectResolver, RenderResult, render

#: Optional opaque context a target carries into a preview so a later insert can
#: prove the target has not moved (FR-12 "旧结果不得写入新目标").
def _target_fingerprint(target: Target, draft_id: Optional[str], draft_revision: Optional[int],
                        context_revision: Optional[int]) -> str:
    canonical = "|".join(str(v) for v in (
        target.principal, target.server_identity, target.project_id, target.harness_id,
        target.profile_id, target.profile_revision, draft_id, draft_revision, context_revision))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CommandTemplateService:
    def __init__(self, store: TemplateStore, *, receipts: Optional[ReceiptLedger] = None,
                 project_resolver: Optional[ProjectResolver] = None) -> None:
        self._store = store
        self._receipts = receipts if receipts is not None else ReceiptLedger()
        self._project_resolver = project_resolver

    @property
    def store(self) -> TemplateStore:
        return self._store

    @property
    def receipts(self) -> ReceiptLedger:
        return self._receipts

    # -- content CRUD -------------------------------------------------------

    def create(self, *, principal: str, template_id: str, display_name: str, slug: str,
               description: str = "", operation_key: str) -> Template:
        return self._store.create_template(
            template_id=template_id, owner_principal=principal, display_name=display_name,
            slug=slug, description=description, operation_key=operation_key)

    def get(self, *, principal: str, template_id: str) -> Template:
        template = self._store.get_template(template_id)
        self._assert_owner(principal, template.owner_principal, template_id)
        return template

    def list(self, *, principal: str, include_archived: bool = False) -> "list[Template]":
        """Metadata for the caller's own templates only; no body ever appears."""
        return self._store.list_templates(owner_principal=principal,
                                          include_archived=include_archived)

    def revisions(self, *, principal: str, template_id: str) -> "list[TemplateRevision]":
        self.get(principal=principal, template_id=template_id)
        return self._store.revisions(template_id)

    def save_revision(self, *, principal: str, template_id: str, body: str,
                      parameters: Sequence[ParameterSpec] = (), expected_version: int,
                      operation_key: str) -> TemplateRevision:
        self.get(principal=principal, template_id=template_id)
        return self._store.save_revision(
            template_id, body=body, parameters=parameters, expected_version=expected_version,
            operation_key=operation_key)

    def approve(self, *, principal: str, template_id: str, revision: int,
                expected_version: int, operation_key: str) -> TemplateRevision:
        self.get(principal=principal, template_id=template_id)
        return self._store.approve_revision(
            template_id, revision, expected_version=expected_version, operation_key=operation_key)

    def archive(self, *, principal: str, template_id: str, expected_version: int,
                operation_key: str) -> Template:
        self.get(principal=principal, template_id=template_id)
        return self._store.archive_template(
            template_id, expected_version=expected_version, operation_key=operation_key)

    # -- assignments --------------------------------------------------------

    def set_assignment(self, *, principal: str, assignment: Assignment,
                       expected_version: Optional[int], operation_key: str) -> Assignment:
        self._assert_scope_authority(principal, assignment)
        self._store.get_template(assignment.template_id)  # must exist
        return self._store.upsert_assignment(assignment, expected_version=expected_version,
                                             operation_key=operation_key)

    def resolve(self, *, target: Target, org_policy: Optional[OrgPolicy] = None) -> Resolution:
        assignments = self._applicable_assignments(target)
        return resolve_effective(self._store, target, assignments, org_policy=org_policy)

    # -- expansion ----------------------------------------------------------

    def render_preview(self, *, target: Target, template_id: str, revision: int,
                       arguments: "dict[str, object]", draft_id: Optional[str] = None,
                       draft_revision: Optional[int] = None,
                       context_revision: Optional[int] = None) -> RenderResult:
        """Validate + render for ``target`` without touching any draft (zero-send)."""
        stored = self._load_approved_for_target(target, template_id, revision)
        parsed = parse(stored.body)
        return render(parsed, stored.parameters, arguments, principal=target.principal,
                      resolver=self._project_resolver)

    def prepare_insert(self, *, target: Target, template_id: str, revision: int,
                       arguments: "dict[str, object]", rendered: RenderResult,
                       draft_id: Optional[str] = None, draft_revision: Optional[int] = None,
                       context_revision: Optional[int] = None,
                       operation_id: str) -> ExpansionReceipt:
        """Mint a single-use receipt binding the render to the current target/draft."""
        fingerprint = _target_fingerprint(target, draft_id, draft_revision, context_revision)
        from ..expansion.digest import arguments_digest as _ad
        import time
        now = time.time()
        receipt = ExpansionReceipt(
            operation_id=operation_id, principal=target.principal,
            target_fingerprint=fingerprint, template_id=template_id, revision=revision,
            argument_digest=_ad(arguments), rendered_digest=rendered.digest,
            rendered_size=rendered.rendered_bytes, draft_id=draft_id,
            draft_revision=draft_revision, created_at=str(now),
            expires_at=str(now + self._receipts.ttl))
        return self._receipts.issue(receipt)

    def validate_insert(self, *, operation_id: str, target: Target,
                        draft_id: Optional[str] = None, draft_revision: Optional[int] = None,
                        context_revision: Optional[int] = None) -> "tuple[ExpansionReceipt, RenderResult | None]":
        """Return the receipt whose bytes the caller may insert, or refuse (FR-12).

        This never re-expands against the latest template and never mutates the
        draft: it confirms the pinned revision still matches the current target
        and hands back the digest the caller already previewed.
        """
        receipt = self._receipts.consume(operation_id)
        current_fp = _target_fingerprint(target, draft_id, draft_revision, context_revision)
        if receipt.principal != target.principal:
            raise UnauthorizedTargetError("the receipt belongs to a different principal")
        if receipt.target_fingerprint != current_fp:
            raise StalePreviewError(
                "the target or draft changed since the preview; refresh before inserting")
        return receipt, None

    # -- import -------------------------------------------------------------

    def import_preview(self, *, raw: bytes, source_label: str) -> importer.ImportPreview:
        return importer.preview_import(raw=raw, source_label=source_label)

    def import_commit(self, *, principal: str, preview: importer.ImportPreview, template_id: str,
                      operation_key: str) -> TemplateRevision:
        plan = importer.commit_from_preview(preview)
        self._store.create_template(
            template_id=template_id, owner_principal=principal,
            display_name=str(plan["display_name"]), slug=str(plan["slug"]),
            origin="imported", operation_key=operation_key + ":create")
        template = self._store.get_template(template_id)
        return self._store.save_revision(
            template_id, body=str(plan["body"]), parameters=plan["parameters"],
            expected_version=template.entity_version, operation_key=operation_key + ":rev")

    # -- authority helpers --------------------------------------------------

    def _assert_owner(self, principal: str, owner: str, template_id: str) -> None:
        if principal != owner:
            # A cross-owner read is refused, not filtered to a false absence.
            raise UnauthorizedTargetError(
                f"principal {principal!r} may not read template {template_id!r}")

    def _assert_scope_authority(self, principal: str, assignment: Assignment) -> None:
        if assignment.scope in ("user-global", "user-harness"):
            if assignment.scope_identity != principal:
                raise UnauthorizedTargetError("a user scope must be the caller's own principal")
            return
        if assignment.scope in ("project", "project-harness"):
            # Project scopes require an authorized project port; without one wired
            # the write is refused rather than trusted (gap: api-requests.md).
            if self._project_resolver is None:
                raise UnauthorizedTargetError(
                    "project-scoped assignment needs an authorized project port (absent)")
            return
        if assignment.scope == "profile":
            raise UnauthorizedTargetError(
                "profile assignments are applied through the Profile facet seam, not here")

    def _applicable_assignments(self, target: Target) -> "list[Assignment]":
        rows = self._store.assignments()
        return [row for row in rows if row.scope_identity in (
            target.principal, target.project_id, target.profile_id)]

    def _load_approved_for_target(self, target: Target, template_id: str,
                                  revision: int) -> TemplateRevision:
        stored = self._store.get_revision(template_id, revision)
        template = self._store.get_template(template_id)
        if template.is_archived:
            raise ContentMissingError(f"template {template_id!r} is archived")
        if not stored.is_approved:
            raise RevisionUnapprovedError(
                f"revision {revision} must be approved before it can be rendered")
        # Availability for this target: an enable assignment (or policy) must make
        # it reachable; the caller resolves the catalogue separately for menus.
        return replace(stored)
