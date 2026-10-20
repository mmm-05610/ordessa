"""C1 service subset for this slice: content, revisions, archive, clone, import.

Every mutation carries `principal`, `server_scope`, `expected_row_version` and
`operation_key`; the principal is checked against the injected authority
instead of taken at face value, and an idempotency receipt is scoped to
principal + target + operation with the payload digest deciding the outcome:

* same key, same payload  -> the recorded result, and no second write;
* same key, other payload -> `ASSIGNMENT_CONFLICT` (the choice documented in
  errors.py; `OPERATION_UNKNOWN` is reserved for an unknown key/preview);
* stale `expected_row_version` -> `REVISION_STALE` and nothing is written.

Reads carry a viewer (§C1 "读操作按公共、项目、Profile 专用归属过滤，不泄露他人存
在性"): `authorize_viewer` issues a `scopes.ViewerScope` from the same
attested principal + server scope + server-verified project/Profile/session
binding that mutations are authenticated against, and every read method takes
it as the keyword-only `viewer` argument. A foreign-principal or foreign-
project row, and a profile-origin row outside its own profile/sessions (G08),
reads back identical to an absent one — the single `scopes.scoped_read` /
`scopes.visible_definition_ids` rule, never a second copy. A viewer is only
ever valid at the service that issued it, and only after attestation.
Attribution comes from the service's own persisted ownership receipts and
fails closed for rows it cannot attribute. The legacy reads with
`viewer=None` (no viewer passed) are the pinned in-process seam `wire.py`
and this slice's older tests call today, unchanged; migrating them onto
issued viewers is the wire's own follow-up. The unfiltered administrative
read is a SEPARATE named surface — `authorize_admin_reader` plus
`admin_get_definition`/`admin_list_definitions` — that needs an
authority-attested admin context, and no viewer argument can reach it.

`operation_status` answers §C5 "未知结果必须可查询，不得回退为静默成功": the
idempotency receipt of one's own (action, principal-scoped target, operation
key) can be re-read after a lost response; nothing recorded answers
`OPERATION_UNKNOWN` and never a synthesised success. The receipt scope
already carries the principal, so another principal's receipt is
indistinguishable from a receipt that never existed.

The legacy dispatch mechanism (grant edges, roster, `run_subagent`, cycle or
turn limits) is deliberately absent: this service stores definitions and hands
them out, it never runs one (FR12).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from . import decoder, limits, scopes
from .digest import bytes_digest, canonical_digest, revision_digest
from .dto import (
    AgentDefinition,
    DefinitionRevision,
    ImportFile,
    ImportPlan,
    ImportPreview,
    SourceApproval,
    new_definition_id,
    new_preview_id,
)
from .errors import (
    ASSIGNMENT_CONFLICT,
    DEFINITION_INVALID,
    OPERATION_UNKNOWN,
    PERMISSION_EXCEEDS_CEILING,
    REVISION_STALE,
    DomainError,
)
from .store import DefinitionStore, read_source_bytes, walk_bounded

#: A recursive include and a remote fetch are refusals, never behaviour.
_RECURSIVE_RES = (
    re.compile(r"!\[\["),
    re.compile(r"@\[\["),
    re.compile(r"(?i)@import"),
    re.compile(r"(?i)\{\{[ \t]*include"),
    re.compile(r"(?im)^[ \t]*include[ \t]*[:=]"),
    re.compile(r"(?im)^[ \t]*source[ \t]*="),
)
_REMOTE_RES = (re.compile(r"(?i)\bhttps?://"), re.compile(r"(?i)\bftp://"))
_PLACEHOLDER = "sha256:" + "0" * 64


class Authority(Protocol):
    """The service's authentication context (C1: never self-reported).

    `verify_principal` and `permission_ceiling` are required. Three further
    capabilities are optional and only consulted when a read viewer claims a
    binding: `verify_project(principal, *, server_scope, project_id)`,
    `verify_profile(principal, *, server_scope, profile_id)` and
    `verify_session(principal, *, server_scope, session_id, profile_id,
    session_harness_id, harness_id)`. An authority that answers none of them
    can only issue public-identity viewers: a project or Profile claim the
    server cannot attest is refused before any lookup (G07/G08), never
    narrowed or honoured. A fourth optional capability,
    `admin_read_allowed(principal, *, server_scope)`, is consulted only by
    `authorize_admin_reader` — the unfiltered administrative read surface.
    """

    def verify_principal(self, principal: str, *, server_scope: str) -> bool:
        ...

    def permission_ceiling(self, principal: str, server_scope: str) -> frozenset[str]:
        ...

    def admin_read_allowed(self, principal: str, *, server_scope: str) -> bool:
        ...


class AdminReadContext:
    """An explicitly attested administrative read capability (§C1).

    Issued only by `DefinitionService.authorize_admin_reader`: the principal
    passes the same authentication a mutation passes *and* the authority
    grants it `admin_read_allowed`. It names the issuing service, so a
    context from one service (or one built by hand) is inert at another.
    """

    __slots__ = ("principal", "server_scope", "_issuer")

    def __init__(self, principal: scopes.Principal,
                 server_scope: scopes.ServerScope, issuer: object) -> None:
        self.principal = principal
        self.server_scope = server_scope
        self._issuer = issuer

    def __repr__(self) -> str:
        return (f"AdminReadContext(principal={self.principal.id!r}, "
                f"server_scope={self.server_scope.id!r})")


#: The actions whose idempotency receipt records a definition into its
#: principal's ownership (viewer-scoped reads consult exactly these; see
#: `_scan_owners`. `scopes.visible_to` requires `owner_principal ==
#: viewer.principal` in every branch, so ownership never needs to be read
#: *back* for a foreign principal).
OWNERSHIP_ACTIONS: frozenset[str] = frozenset({"create", "clone", "approve_import"})

#: The mutation actions `operation_status` may re-read a receipt for.
IDEMPOTENT_ACTIONS: frozenset[str] = frozenset(
    OWNERSHIP_ACTIONS | {"save_revision", "archive", "restore"}
)


@dataclass(frozen=True)
class OperationStatus:
    """The recorded outcome of one `operationKey`, or an honest unknown (§C5).

    `state` is `"recorded"` exactly when the principal-scoped receipt exists:
    then `result` carries the outcome the service recorded and
    `request_digest` is the payload digest that gates the replay. An absent
    receipt answers `state="unknown"` with `code=OPERATION_UNKNOWN` and no
    result — never a synthesised success. Because the receipt scope holds the
    principal, a lookup by another principal is byte-for-byte the shape of "no
    such receipt": one principal's receipt is never observable to another.
    """

    state: str
    action: str
    target: str
    operation_key: str
    request_digest: str | None = None
    result: Mapping[str, Any] | None = None
    code: str | None = None


class DefinitionService:
    def __init__(self, store: DefinitionStore, *, authority: Authority) -> None:
        self.store = store
        self.authority = authority
        self._previews: dict[str, ImportPreview] = {}
        self._import_roots: dict[str, Path] = {}
        #: definition_id -> principals proven to own it (this instance's own
        #: mutations plus one lazy receipt scan per viewer principal).
        self._owners: dict[str, set[str]] = {}
        self._owner_scans: set[str] = set()
        #: the private capability proving a ViewerScope came from *this*
        #: service's authorization path (§C1: a client names no viewer).
        self._viewer_token = object()

    # -- reads -------------------------------------------------------------

    def authorize_viewer(
        self,
        principal: str,
        server_scope: str,
        *,
        project_id: str | None = None,
        profile_id: str | None = None,
        session_id: str | None = None,
        session_profile_id: str | None = None,
        session_harness_id: str | None = None,
        harness_id: str = scopes.ANY_HARNESS,
    ) -> scopes.ViewerScope:
        """Issue the viewer context a scoped read demands (§C1).

        The principal is checked against the injected authority exactly as a
        mutation checks it, so a caller cannot name a viewer it is not
        attested as. A project claim goes through the same
        `scopes.AuthorizationContext.require_project` gate mutations use
        (G07); a Profile or session claim is honoured only when the composed
        authority attests that binding, and a binding the authority cannot
        attest fails closed (G08).
        """
        self._authenticate(principal, server_scope)
        verified_project = None
        if project_id is not None:
            claimed = scopes.ProjectId(project_id)
            if self._attests("verify_project", principal, server_scope=server_scope,
                             project_id=claimed.id):
                verified_project = claimed
        authorization = scopes.AuthorizationContext.issued_by_service(
            scopes.Principal(principal), scopes.ServerScope(server_scope),
            verified_project,
        )
        # the one gate for "may this context act on project P" (G07) —
        # reused, never forked into a second rule:
        authorization.require_project(project_id)
        profile = None
        if profile_id is not None:
            self._refuse_unattested(
                self._attests("verify_profile", principal, server_scope=server_scope,
                              profile_id=profile_id),
                item_id="profile_id",
                detail="profile assertion is not server-verified for this context",
            )
            profile = scopes.ProfileId(profile_id)
        session, session_profile = None, None
        if session_id is not None:
            session = scopes.SessionId(session_id)
            session_profile = (
                None if session_profile_id is None else scopes.ProfileId(session_profile_id)
            )
            self._refuse_unattested(
                self._attests("verify_session", principal, server_scope=server_scope,
                              session_id=session.id,
                              profile_id=None if session_profile is None
                              else session_profile.id,
                              session_harness_id=session_harness_id,
                              harness_id=harness_id),
                item_id="session_id",
                detail="session assertion is not server-verified for this context",
            )
        return scopes.issue_viewer(
            scopes.ViewerScope(
                principal=authorization.principal,
                server_scope=authorization.server_scope,
                project=authorization.verified_project,
                profile_id=profile,
                session_id=session,
                session_profile_id=session_profile,
                session_harness_id=session_harness_id,
                harness_id=harness_id,
            ),
            self._viewer_token,
        )

    def get_definition(
        self, definition_id: str, *, viewer: scopes.ViewerScope | None = None
    ) -> AgentDefinition:
        """`viewer=None` is the pinned legacy/admin seam (module docstring);
        a given viewer must come from `authorize_viewer` and sees only what
        §C1's ownership filter makes visible — a foreign row answers
        identical to an absent one."""
        if viewer is None:
            return self.store.get_definition(definition_id)
        self._require_issued(viewer)
        return self._visible_definition(definition_id, viewer)

    def list_definitions(
        self, *, include_archived: bool = False,
        viewer: scopes.ViewerScope | None = None,
    ) -> list[AgentDefinition]:
        rows = self.store.list_definitions()
        if viewer is not None:
            self._require_issued(viewer)
            viewable, _hidden = scopes.visible_definition_ids(
                {row.definition_id: self._ownership_of(row, viewer) for row in rows},
                viewer,
            )
            rows = [row for row in rows if row.definition_id in viewable]
        return rows if include_archived else [row for row in rows if not row.archived]

    def get_revision(
        self, definition_id: str, revision: int,
        *, viewer: scopes.ViewerScope | None = None,
    ) -> DefinitionRevision:
        """A frozen reference resolves whether or not the definition is archived."""
        if viewer is None:
            return self.store.get_revision(definition_id, revision)
        self._require_issued(viewer)
        if not self._definition_visible(definition_id, viewer):
            raise self._no_such_revision(definition_id, revision)
        return self.store.get_revision(definition_id, revision)

    def latest_revision(
        self, definition_id: str, *, viewer: scopes.ViewerScope | None = None
    ) -> DefinitionRevision:
        if viewer is None:
            row = self.store.get_definition(definition_id)
        else:
            self._require_issued(viewer)
            row = self._visible_definition(definition_id, viewer)
        if row.latest_revision < 1:
            raise DomainError(
                DEFINITION_INVALID, item_id=definition_id, detail="no revision is stored yet",
            )
        return self.store.get_revision(definition_id, row.latest_revision)

    def is_compilable(
        self, definition_id: str, revision: int,
        *, viewer: scopes.ViewerScope | None = None,
    ) -> bool:
        if viewer is None:
            return decoder.is_compilable(self.store.get_revision(definition_id, revision))
        self._require_issued(viewer)
        if not self._definition_visible(definition_id, viewer):
            raise self._no_such_revision(definition_id, revision)
        return decoder.is_compilable(self.store.get_revision(definition_id, revision))

    # -- explicit administrative reads (separate names, attested context) ----

    def authorize_admin_reader(
        self, principal: str, server_scope: str
    ) -> AdminReadContext:
        """Issue the only capability that widens a read past ownership.

        The principal clears the same authentication a mutation clears, and
        the composed authority must additionally grant `admin_read_allowed`;
        an authority that cannot answer that fails closed. Ordinary viewer
        reads never consult this surface, and no `viewer` argument can reach
        it: an unfiltered read has to be asked for by name, with a context
        this service issued to an attested admin principal.
        """
        self._authenticate(principal, server_scope)
        self._refuse_unattested(
            self._attests("admin_read_allowed", principal, server_scope=server_scope),
            item_id="admin",
            detail="administrative read is not attested for this principal",
        )
        return AdminReadContext(
            scopes.Principal(principal), scopes.ServerScope(server_scope), self
        )

    def admin_get_definition(
        self, definition_id: str, *, admin: AdminReadContext
    ) -> AgentDefinition:
        """The named unfiltered read (maintenance/migration tooling only)."""
        self._require_admin(admin)
        return self.store.get_definition(definition_id)

    def admin_list_definitions(
        self, *, include_archived: bool = False, admin: AdminReadContext
    ) -> list[AgentDefinition]:
        self._require_admin(admin)
        rows = self.store.list_definitions()
        return rows if include_archived else [row for row in rows if not row.archived]

    def _require_admin(self, admin: AdminReadContext) -> None:
        if not isinstance(admin, AdminReadContext) or admin._issuer is not self:
            raise DomainError(
                PERMISSION_EXCEEDS_CEILING, item_id="admin",
                detail="an unfiltered read needs an AdminReadContext issued by "
                       "this service's authorize_admin_reader path",
            )

    def operation_status(
        self,
        principal: str,
        action: str,
        target: str,
        *,
        server_scope: str,
        operation_key: str,
    ) -> OperationStatus:
        """§C5: the outcome of one's own `operationKey` stays queryable after
        a lost response. The caller is authenticated on the same path as a
        mutation; the receipt scope already holds the principal, so another
        principal's receipt is indistinguishable from no receipt, and nothing
        recorded is ever answered as a success."""
        self._authenticate(principal, server_scope)
        self._check_operation_key(operation_key)
        known_action = isinstance(action, str) and action in IDEMPOTENT_ACTIONS
        receipt = (
            self.store.read_receipt(self._scope(action, principal, target), operation_key)
            if known_action else None
        )
        if (receipt is None or not isinstance(receipt.get("result"), Mapping)
                or not isinstance(receipt.get("request_digest"), str)):
            return OperationStatus(
                state="unknown", action=action if isinstance(action, str) else "",
                target=target if isinstance(target, str) else "",
                operation_key=operation_key, code=OPERATION_UNKNOWN,
            )
        return OperationStatus(
            state="recorded", action=action, target=target,
            operation_key=operation_key,
            request_digest=receipt["request_digest"],
            result=dict(receipt["result"]),
        )

    # -- create / publish ----------------------------------------------------

    def create_definition(
        self,
        principal: str,
        *,
        server_scope: str,
        slug: str,
        display_name: str,
        description: str,
        origin_scope: str,
        origin_owner: str,
        operation_key: str,
        expected_row_version: int = 0,
        definition_id: str | None = None,
    ) -> AgentDefinition:
        self._authenticate(principal, server_scope)
        target = self._checked_id(definition_id or new_definition_id())
        candidate = AgentDefinition(
            server_scope=server_scope, definition_id=target, slug=slug,
            display_name=display_name, description=description,
            origin_scope=origin_scope, origin_owner=origin_owner,
            latest_revision=0, archived=False, row_version=1,
        )
        decoder.validate_definition(candidate)
        self._check_aggregate_budget(candidate)
        request = {
            "server_scope": server_scope, "slug": slug, "display_name": display_name,
            "description": description, "origin_scope": origin_scope,
            "origin_owner": origin_owner,
        }
        scope = self._scope("create", principal, f"{server_scope}/{slug}")
        replay = self._replay(scope, operation_key, request, expected_row_version)
        if replay is not None:
            replayed = decoder.decode_definition(replay)
            self._note_owner(replayed.definition_id, principal)
            return replayed
        self.store.create_definition(candidate)
        recorded = decoder.definition_mapping(candidate)
        self._record(scope, operation_key, request, expected_row_version, recorded)
        self._note_owner(candidate.definition_id, principal)
        return decoder.decode_definition(recorded)

    def save_revision(
        self,
        principal: str,
        revision: DefinitionRevision | Mapping[str, Any],
        *,
        server_scope: str,
        operation_key: str,
        expected_row_version: int,
    ) -> DefinitionRevision:
        self._authenticate(principal, server_scope)
        decoded = decoder.validate_revision(
            decoder.decode_revision(revision)
            if isinstance(revision, Mapping) else revision
        )
        row = self.store.get_definition(decoded.definition_id)
        if row.server_scope != server_scope:
            raise DomainError(
                DEFINITION_INVALID, item_id=row.definition_id,
                detail="that definition belongs to another server scope",
            )
        request = {"revision": decoder.revision_mapping(decoded)}
        scope = self._scope("save_revision", principal, row.definition_id)
        replay = self._replay(scope, operation_key, request, expected_row_version)
        if replay is not None:
            return decoder.decode_revision(replay)
        if row.archived:
            raise DomainError(
                ASSIGNMENT_CONFLICT, item_id=row.definition_id,
                detail="an archived definition takes no new revision; restore it first",
            )
        if row.row_version != expected_row_version:
            raise DomainError(
                REVISION_STALE, item_id=row.definition_id,
                detail=f"expected row_version {expected_row_version}, the row holds "
                       f"{row.row_version}",
            )
        if decoded.revision <= row.latest_revision:
            raise DomainError(
                REVISION_STALE, item_id=f"{row.definition_id}@{decoded.revision}",
                detail="a stored revision is never rewritten; publish the next number",
            )
        if decoded.revision != row.latest_revision + 1:
            raise DomainError(
                DEFINITION_INVALID, item_id="revision",
                detail=f"revisions append: expected {row.latest_revision + 1}",
            )
        self._check_source_is_witnessed(principal, decoded)
        self._check_permission_ceiling(principal, server_scope, decoded)
        updated = AgentDefinition(
            server_scope=row.server_scope, definition_id=row.definition_id, slug=row.slug,
            display_name=row.display_name, description=row.description,
            origin_scope=row.origin_scope, origin_owner=row.origin_owner,
            latest_revision=decoded.revision, archived=row.archived,
            row_version=row.row_version + 1,
        )
        self.store.write_revision(decoded)
        self.store.replace_definition(updated, expected_row_version=row.row_version)
        self._record(scope, operation_key, request, expected_row_version,
                     decoder.revision_mapping(decoded))
        return decoder.decode_revision(decoder.revision_mapping(decoded))

    # -- archive / restore / clone ------------------------------------------

    def archive(
        self,
        principal: str,
        definition_id: str,
        *,
        server_scope: str,
        operation_key: str,
        expected_row_version: int,
    ) -> AgentDefinition:
        return self._set_archived(
            "archive", principal, definition_id, server_scope=server_scope,
            operation_key=operation_key, expected_row_version=expected_row_version,
            archived=True,
        )

    def restore(
        self,
        principal: str,
        definition_id: str,
        *,
        server_scope: str,
        operation_key: str,
        expected_row_version: int,
    ) -> AgentDefinition:
        return self._set_archived(
            "restore", principal, definition_id, server_scope=server_scope,
            operation_key=operation_key, expected_row_version=expected_row_version,
            archived=False,
        )

    def _set_archived(
        self,
        action: str,
        principal: str,
        definition_id: str,
        *,
        server_scope: str,
        operation_key: str,
        expected_row_version: int,
        archived: bool,
    ) -> AgentDefinition:
        self._authenticate(principal, server_scope)
        row = self.store.get_definition(definition_id)
        request = {"definition_id": definition_id, "archived": archived}
        scope = self._scope(action, principal, definition_id)
        replay = self._replay(scope, operation_key, request, expected_row_version)
        if replay is not None:
            return decoder.decode_definition(replay)
        if row.server_scope != server_scope:
            raise DomainError(
                DEFINITION_INVALID, item_id=definition_id,
                detail="that definition belongs to another server scope",
            )
        if row.archived is archived:
            raise DomainError(
                ASSIGNMENT_CONFLICT, item_id=definition_id,
                detail=f"the definition is already {'archived' if archived else 'active'}",
            )
        if row.row_version != expected_row_version:
            raise DomainError(
                REVISION_STALE, item_id=definition_id,
                detail=f"expected row_version {expected_row_version}, the row holds "
                       f"{row.row_version}",
            )
        updated = AgentDefinition(
            server_scope=row.server_scope, definition_id=row.definition_id, slug=row.slug,
            display_name=row.display_name, description=row.description,
            origin_scope=row.origin_scope, origin_owner=row.origin_owner,
            latest_revision=row.latest_revision, archived=archived,
            row_version=row.row_version + 1,
        )
        if not archived:
            self._check_aggregate_budget(updated)
        self.store.replace_definition(updated, expected_row_version=expected_row_version)
        recorded = decoder.definition_mapping(updated)
        self._record(scope, operation_key, request, expected_row_version, recorded)
        return decoder.decode_definition(recorded)

    def clone(
        self,
        principal: str,
        definition_id: str,
        *,
        server_scope: str,
        operation_key: str,
        expected_row_version: int,
        slug: str | None = None,
        display_name: str | None = None,
    ) -> AgentDefinition:
        """A new definition id at revision 1, in storage of its own."""
        self._authenticate(principal, server_scope)
        row = self.store.get_definition(definition_id)
        source = self.latest_revision(definition_id)
        target_id = self._checked_id(new_definition_id())
        clone = AgentDefinition(
            server_scope=row.server_scope, definition_id=target_id,
            slug=slug or row.slug, display_name=display_name or row.display_name,
            description=row.description, origin_scope=row.origin_scope,
            origin_owner=row.origin_owner, latest_revision=1, archived=False, row_version=1,
        )
        copied = DefinitionRevision(
            definition_id=target_id, revision=1, content_digest=source.content_digest,
            role_body=source.role_body, declared_model_ref=source.declared_model_ref,
            tool_refs=source.tool_refs, mcp_refs=source.mcp_refs, skill_refs=source.skill_refs,
            requested_permission=source.requested_permission, isolation=source.isolation,
            limits=source.limits, source=source.source,
            retained_native_fields=source.retained_native_fields,
        )
        decoder.validate_definition(clone)
        decoder.validate_revision(copied)
        request = {"source": definition_id, "revision": source.revision,
                   "slug": clone.slug, "display_name": clone.display_name}
        scope = self._scope("clone", principal, definition_id)
        replay = self._replay(scope, operation_key, request, expected_row_version)
        if replay is not None:
            replayed = decoder.decode_definition(replay)
            self._note_owner(replayed.definition_id, principal)
            return replayed
        if row.row_version != expected_row_version:
            raise DomainError(
                REVISION_STALE, item_id=definition_id,
                detail=f"expected row_version {expected_row_version}, the row holds "
                       f"{row.row_version}",
            )
        self._check_aggregate_budget(clone)
        self.store.create_definition(clone)
        self.store.write_revision(copied)
        recorded = decoder.definition_mapping(clone)
        self._record(scope, operation_key, request, expected_row_version, recorded)
        self._note_owner(clone.definition_id, principal)
        return decoder.decode_definition(recorded)

    # -- import: a preview, then a separate explicit approval ----------------

    def import_preview(self, source_path: Path | str, *, import_root: Path | str) -> ImportPreview:
        """A read-only verdict: no write, no execution, no fetch, no HOME read."""
        root = _checked_root(import_root)
        target = _inside(root, source_path, label="import source")
        if self.store.holds_path(target):
            raise DomainError(
                DEFINITION_INVALID, item_id="import_source",
                detail="stored content is never an import source",
            )
        files = _collect(target)
        entries = tuple(_preview_file(name, path) for name, path in sorted(files.items()))
        if not entries:
            raise DomainError(
                DEFINITION_INVALID, item_id="import_source",
                detail="the import source holds no file to preview",
            )
        preview = ImportPreview(
            preview_id=new_preview_id(),
            source_name=target.name or str(target),
            source_path=str(target),
            source_digest=canonical_digest(
                {"source": target.name, "files": [entry.content_digest for entry in entries]}
            ),
            files=entries,
            diagnostics=tuple(dict.fromkeys(
                diagnostic
                for entry in entries
                for diagnostic in entry.diagnostics
            )),
        )
        self._previews[preview.preview_id] = preview
        self._import_roots[preview.preview_id] = root
        return preview

    def import_plan(
        self,
        principal: str,
        preview_id: str,
        *,
        server_scope: str,
        selects: Sequence[str],
        origin: str = "user-upload",
        origin_ref: str | None = None,
        origin_scope: str = "public",
        origin_owner: str = "local",
    ) -> tuple[ImportPlan, ...]:
        """Exactly what an approval would persist — computed, never written."""
        self._authenticate(principal, server_scope)
        preview = self._preview(preview_id)
        return tuple(
            self._plan_of(
                principal, preview, entry, server_scope=server_scope, origin=origin,
                origin_ref=origin_ref, origin_scope=origin_scope, origin_owner=origin_owner,
            )
            for entry in self._selected(preview, selects)
        )

    def approve_import(
        self,
        preview_id: str,
        *,
        principal: str,
        server_scope: str,
        selects: Sequence[str],
        operation_key: str,
        expected_row_version: int = 0,
        origin: str = "user-upload",
        origin_ref: str | None = None,
        origin_scope: str = "public",
        origin_owner: str = "local",
    ) -> tuple[AgentDefinition, ...]:
        """The second, explicit step: persist only the selected approved items."""
        self._authenticate(principal, server_scope)
        preview = self._preview(preview_id)
        chosen = self._selected(preview, selects)
        request = {
            "preview_id": preview_id, "source_digest": preview.source_digest,
            "selects": sorted(entry.relative_path for entry in chosen),
            "origin": origin, "origin_ref": origin_ref, "server_scope": server_scope,
            "origin_scope": origin_scope, "origin_owner": origin_owner,
        }
        scope = self._scope("approve_import", principal, preview_id)
        replay = self._replay(scope, operation_key, request, expected_row_version)
        if replay is not None:
            rows = tuple(
                decoder.decode_definition(item["definition"]) for item in replay["definitions"]
            )
            for row in rows:
                self._note_owner(row.definition_id, principal)
            return rows
        # Validate the whole selection first: a refused item persists nothing.
        plans = tuple(
            self._plan_of(
                principal, preview, entry, server_scope=server_scope, origin=origin,
                origin_ref=origin_ref, origin_scope=origin_scope, origin_owner=origin_owner,
            )
            for entry in chosen
        )
        recorded: list[dict[str, Any]] = []
        for plan in plans:
            self.store.create_definition(plan.definition)
            self.store.write_revision(plan.revision)
            self._note_owner(plan.definition.definition_id, principal)
            recorded.append({
                "definition": decoder.definition_mapping(plan.definition),
                "revision": decoder.revision_mapping(plan.revision),
            })
        result = {"definitions": recorded}
        self._record(scope, operation_key, request, expected_row_version, result)
        return tuple(decoder.decode_definition(item["definition"]) for item in recorded)

    # -- shared guards -----------------------------------------------------

    def _require_issued(self, viewer: scopes.ViewerScope) -> None:
        """Only a viewer from *this* service's `authorize_viewer` scopes a read."""
        if (not isinstance(viewer, scopes.ViewerScope)
                or scopes.viewer_issuance(viewer) is not self._viewer_token):
            raise DomainError(
                PERMISSION_EXCEEDS_CEILING, item_id="viewer",
                detail="a read viewer must be issued by this service's "
                       "authorize_viewer path; a client cannot name a viewer "
                       "it is not attested as (§C1)",
            )

    def _attests(self, capability: str, principal: str, **claims: Any) -> bool:
        """An optional authority attestation; absent or erroring fails closed."""
        check = getattr(self.authority, capability, None)
        if check is None:
            return False
        try:
            return bool(check(principal, **claims))
        except Exception:
            return False

    def _refuse_unattested(self, attested: bool, *, item_id: str, detail: str) -> None:
        if not attested:
            raise DomainError(PERMISSION_EXCEEDS_CEILING, item_id=item_id, detail=detail)

    def _visible_definition(
        self, definition_id: str, viewer: scopes.ViewerScope
    ) -> AgentDefinition:
        # an absent or malformed id raises exactly what a legacy read raises;
        # a hidden row below raises the identical shape (no "hidden exists"):
        row = self.store.get_definition(definition_id)
        ownership = self._ownership_of(row, viewer)
        if scopes.scoped_read(ownership, viewer) is scopes.NOT_FOUND:
            # hidden and absent answer identically (scopes.py: one sentinel):
            raise self._absent_definition(definition_id)
        return row

    def _definition_visible(self, definition_id: str, viewer: scopes.ViewerScope) -> bool:
        try:
            stored = self.store.read_definition(definition_id)
        except DomainError:
            return False  # a malformed id is not visible; the store refuses alike
        if stored is None:
            return False
        ownership = self._ownership_of(decoder.decode_definition(stored), viewer)
        return scopes.scoped_read(ownership, viewer) is not scopes.NOT_FOUND

    @staticmethod
    def _absent_definition(definition_id: str) -> DomainError:
        """The exact shape `DefinitionStore.get_definition` raises for absent."""
        return DomainError(
            DEFINITION_INVALID, item_id=definition_id, detail="no such definition",
        )

    @staticmethod
    def _no_such_revision(definition_id: str, revision: int) -> DomainError:
        """The exact shape `DefinitionStore.get_revision` raises for absent."""
        return DomainError(
            DEFINITION_INVALID, item_id=f"{definition_id}@{revision}",
            detail="no such revision",
        )

    def _ownership_of(
        self, row: AgentDefinition, viewer: scopes.ViewerScope
    ) -> "scopes.DefinitionOwnership | None":
        """The visibility facts for one row, or None when this viewer's
        ownership cannot be proven. `scopes.visible_to` requires
        `owner_principal == viewer.principal` in every branch, so proof is
        always relative to the asking viewer and a foreign owner never needs
        to be named — unproven ownership fails closed as NOT_FOUND, the same
        answer as absent."""
        if viewer.principal.id in self._owners.get(row.definition_id, set()):
            proven = viewer.principal.id
        elif viewer.principal.id not in self._owner_scans:
            self._scan_owners(viewer.principal.id)
            proven = (
                viewer.principal.id
                if viewer.principal.id in self._owners.get(row.definition_id, set())
                else ""
            )
        else:
            proven = ""
        if not proven:
            return None
        return scopes.DefinitionOwnership(
            definition_id=row.definition_id,
            server_scope=scopes.ServerScope(row.server_scope),
            owner_principal=scopes.Principal(proven),
            origin_scope=row.origin_scope,
            origin_owner=row.origin_owner,
        )

    def _note_owner(self, definition_id: str, principal: str) -> None:
        self._owners.setdefault(definition_id, set()).add(principal)

    def _scan_owners(self, principal: str) -> None:
        """Rebuild ownership from this service's own persisted receipts.

        A create/clone/approve-import receipt already records (in its scope)
        the attested principal and (in its result) the definition ids it
        wrote, so attribution survives a restart without a second store
        layout. The scope prefix is matched whole (`{action}:{principal}:`) and
        the remainder is then checked against the receipt's own fields, so a
        principal crafted to swallow another scope cannot claim its receipt.
        Rows that never came through this service (a directly-seeded store, an
        unmigrated legacy library) are unattributed: reads as a viewer fail
        closed on them, identical to absent.
        """
        self._owner_scans.add(principal)
        receipts_root = self.store.root / "receipts"
        if not receipts_root.is_dir():
            return
        for scope_dir in sorted(receipts_root.iterdir()):
            if not scope_dir.is_dir():
                continue
            for entry in sorted(scope_dir.glob("*.json")):
                try:
                    record = json.loads(entry.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(record, Mapping):
                    continue
                scope = record.get("scope")
                if not isinstance(scope, str):
                    continue
                for action in sorted(OWNERSHIP_ACTIONS):
                    prefix = f"{action}:{principal}:"
                    if not scope.startswith(prefix):
                        continue
                    remainder = scope[len(prefix):]
                    result = record.get("result")
                    for definition_id in _receipt_definition_ids(
                        action, remainder, result
                    ):
                        self._note_owner(definition_id, principal)
                    break

    def _preview(self, preview_id: str) -> ImportPreview:
        preview = self._previews.get(preview_id)
        if preview is None:
            raise DomainError(
                OPERATION_UNKNOWN, item_id="preview_id",
                detail="that preview was not produced by this service instance",
            )
        return preview

    def _selected(self, preview: ImportPreview, selects: Sequence[str]) -> tuple[ImportFile, ...]:
        if isinstance(selects, (str, bytes)) or not selects:
            raise DomainError(
                DEFINITION_INVALID, item_id="selects",
                detail="an approval names each selected file",
            )
        by_name = {entry.relative_path: entry for entry in preview.files}
        chosen: list[ImportFile] = []
        for name in selects:
            entry = by_name.get(name if isinstance(name, str) else str(name))
            if entry is None:
                raise DomainError(
                    PERMISSION_EXCEEDS_CEILING, item_id=str(name),
                    detail="only a previewed file may be approved",
                )
            if not entry.selectable:
                raise DomainError(
                    PERMISSION_EXCEEDS_CEILING, item_id=entry.relative_path,
                    detail=" or ".join(entry.diagnostics) or "the preview refused this file",
                )
            chosen.append(entry)
        return tuple(chosen)

    def _plan_of(
        self,
        principal: str,
        preview: ImportPreview,
        entry: ImportFile,
        *,
        server_scope: str,
        origin: str,
        origin_ref: str | None,
        origin_scope: str,
        origin_owner: str,
    ) -> ImportPlan:
        root = self._import_roots[preview.preview_id]
        target = _inside(root, preview.source_path, label="import source")
        mapping, digest = _read_candidate(target, entry.relative_path)
        if digest != entry.content_digest:
            raise DomainError(
                DEFINITION_INVALID, item_id=entry.relative_path,
                detail="the source drifted after the preview; preview it again",
            )
        definition_id = self._checked_id(new_definition_id())
        approval = SourceApproval(
            origin=origin,
            origin_ref=origin_ref or f"{preview.source_name}/{entry.relative_path}",
            content_digest=digest,
            approved_by_principal=principal,
            approved_at=_now(),
        )
        revision = decoder.validate_revision(
            _candidate_revision(definition_id, mapping, approval)
        )
        definition = decoder.validate_definition(AgentDefinition(
            server_scope=server_scope, definition_id=definition_id,
            slug=mapping["slug"], display_name=mapping.get("display_name") or mapping["slug"],
            description=mapping["description"], origin_scope=origin_scope,
            origin_owner=origin_owner, latest_revision=1, archived=False, row_version=1,
        ))
        self._check_aggregate_budget(definition)
        self._check_permission_ceiling(principal, server_scope, revision)
        return ImportPlan(preview_id=preview.preview_id, definition=definition,
                          revision=revision)

    def _authenticate(self, principal: str, server_scope: str) -> None:
        if not isinstance(principal, str) or not principal:
            raise DomainError(
                DEFINITION_INVALID, item_id="principal", detail="a principal is required",
            )
        if not self.authority.verify_principal(principal, server_scope=server_scope):
            raise DomainError(
                PERMISSION_EXCEEDS_CEILING, item_id="principal",
                detail="the caller is not a principal this server recognises",
            )

    def _checked_id(self, definition_id: str) -> str:
        if (not isinstance(definition_id, str)
                or limits._ID_RE.match(definition_id) is None
                or len(definition_id) > limits.MAX_DEFINITION_ID_CHARS):
            raise DomainError(
                DEFINITION_INVALID, item_id="definition_id",
                detail="an id is a bare opaque token",
            )
        if "/" in definition_id or "\\" in definition_id or ".." in definition_id:
            raise DomainError(
                DEFINITION_INVALID, item_id="definition_id",
                detail="an id never names a path",
            )
        return definition_id

    def _check_source_is_witnessed(
        self, principal: str, revision: DefinitionRevision
    ) -> None:
        """A hand-written revision is published by the principal that approved it.

        The approved artifact of an authored revision is its role body, so the
        source digest is checked against the body rather than against the
        revision record — a claim about other content is not an approval of
        this one. A `git-revision` source belongs to the import approval step,
        where the service reads the pinned revision itself.
        """
        source = revision.source
        if source is None:
            raise DomainError(
                DEFINITION_INVALID, item_id="source",
                detail="content without an approved source is never stored",
            )
        if source.approved_by_principal != principal:
            raise DomainError(
                PERMISSION_EXCEEDS_CEILING, item_id="source.approved_by_principal",
                detail="only the approving principal may publish this content",
            )
        if source.origin != "user-upload":
            raise DomainError(
                DEFINITION_INVALID, item_id="source.origin",
                detail="a git-revision source is stored only through an approved import",
            )
        if source.content_digest != bytes_digest(revision.role_body.encode("utf-8")):
            raise DomainError(
                DEFINITION_INVALID, item_id="source.content_digest",
                detail="the source approval covers other content than this revision's body",
            )

    def _check_permission_ceiling(
        self, principal: str, server_scope: str, revision: DefinitionRevision
    ) -> None:
        """A definition never raises the ceiling it declares (FR06)."""
        granted = set(self.authority.permission_ceiling(principal, server_scope))
        declared = {revision.requested_permission} - {None}
        if not declared <= granted:
            raise DomainError(
                PERMISSION_EXCEEDS_CEILING, item_id="requested_permission",
                detail="the definition requests a permission its principal does not hold",
            )

    def _check_aggregate_budget(self, incoming: AgentDefinition) -> None:
        total = self.store.enabled_description_bytes(exclude=incoming)
        total += len(incoming.description.encode("utf-8"))
        if total > limits.MAX_AGGREGATE_DESCRIPTION_BYTES:
            raise DomainError(
                DEFINITION_INVALID, item_id="aggregate_description",
                detail=f"the enabled library exceeds "
                       f"{limits.MAX_AGGREGATE_DESCRIPTION_BYTES} description bytes",
            )
        if len(self.store.enabled_definitions()) + 1 > limits.MAX_ENABLED_DEFINITIONS:
            raise DomainError(
                DEFINITION_INVALID, item_id="aggregate_count",
                detail=f"the enabled library exceeds "
                       f"{limits.MAX_ENABLED_DEFINITIONS} definitions",
            )

    def _scope(self, action: str, principal: str, target: str) -> str:
        return f"{action}:{principal}:{target}"

    def _replay(
        self,
        scope: str,
        operation_key: str,
        request: Mapping[str, Any],
        expected_row_version: int,
    ) -> dict[str, Any] | None:
        self._check_operation_key(operation_key)
        receipt = self.store.read_receipt(scope, operation_key)
        if receipt is None:
            return None
        if receipt["request_digest"] != self._request_digest(request, expected_row_version):
            raise DomainError(
                ASSIGNMENT_CONFLICT, item_id="operation_key",
                detail="that operation key was already used with a different payload",
            )
        return dict(receipt["result"])

    def _record(
        self,
        scope: str,
        operation_key: str,
        request: Mapping[str, Any],
        expected_row_version: int,
        result: Mapping[str, Any],
    ) -> None:
        self.store.write_receipt(
            scope=scope, operation_key=operation_key,
            request_digest=self._request_digest(request, expected_row_version),
            result=result,
        )

    @staticmethod
    def _request_digest(request: Mapping[str, Any], expected_row_version: int) -> str:
        return canonical_digest(dict(request, expected_row_version=expected_row_version))

    @staticmethod
    def _check_operation_key(operation_key: str) -> None:
        if not isinstance(operation_key, str) or not operation_key:
            raise DomainError(
                DEFINITION_INVALID, item_id="operation_key",
                detail="every mutation carries an operation key",
            )
        if len(operation_key) > limits.MAX_OPERATION_KEY_CHARS:
            raise DomainError(
                DEFINITION_INVALID, item_id="operation_key",
                detail=f"exceeds {limits.MAX_OPERATION_KEY_CHARS} characters",
            )

    # -- C1 surface this slice does not own --------------------------------

    def resolve_preview(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("assignment resolution and reference parsing are task T04")

    def approve_assignment_update(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("assignment approval is task T04")

    def inspect_native(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("native observation belongs to T02/T06")


# -- module-level helpers ---------------------------------------------------


def _receipt_definition_ids(
    action: str, scope_remainder: str, result: Any
) -> tuple[str, ...]:
    """The definition ids one ownership receipt wrote, cross-checked where the
    receipt's own payload allows it (`create` restates `{serverScope}/{slug}`
    in its scope, and the recorded row carries both fields)."""
    if not isinstance(result, Mapping):
        return ()
    if action == "create":
        server_scope = result.get("server_scope")
        slug = result.get("slug")
        definition_id = result.get("definition_id")
        if (not isinstance(server_scope, str) or not isinstance(slug, str)
                or not isinstance(definition_id, str)):
            return ()
        if scope_remainder != f"{server_scope}/{slug}":
            return ()
        return (definition_id,)
    if action == "clone":
        definition_id = result.get("definition_id")
        return (definition_id,) if isinstance(definition_id, str) else ()
    # approve_import: {"definitions": [{"definition": {...}, "revision": ...}]}
    items = result.get("definitions")
    if not isinstance(items, (list, tuple)):
        return ()
    found: list[str] = []
    for item in items:
        inner = item.get("definition") if isinstance(item, Mapping) else None
        if isinstance(inner, Mapping) and isinstance(inner.get("definition_id"), str):
            found.append(inner["definition_id"])
    return tuple(found)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _checked_root(import_root: Path | str) -> Path:
    root = Path(import_root)
    if root.is_symlink() or not root.is_dir():
        raise DomainError(
            DEFINITION_INVALID, item_id="import_root",
            detail="the approved import root must be a real directory",
        )
    resolved = root.resolve()
    home = Path.home().resolve()
    if resolved == home or _is_under(home, resolved):
        raise DomainError(
            DEFINITION_INVALID, item_id="import_root",
            detail="a user HOME tree is not an approved import root",
        )
    return resolved


def _is_under(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
    except ValueError:
        return False
    return True


def _inside(root: Path, target: Path | str, *, label: str) -> Path:
    """Reject an escaping path, a home-relative one and any symlink hop."""
    candidate = Path(target)
    raw = str(target)
    if raw.startswith("~") or "\x00" in raw:
        raise DomainError(
            DEFINITION_INVALID, item_id=label, detail="an import path is never home-relative",
        )
    absolute = candidate if candidate.is_absolute() else root / candidate
    for hop in _hops(root, absolute):
        if hop.is_symlink():
            raise DomainError(
                DEFINITION_INVALID, item_id=label,
                detail=f"a symlinked import path is never followed ({hop.name})",
            )
    resolved = absolute.resolve()
    if not _is_under(root, resolved):
        raise DomainError(
            DEFINITION_INVALID, item_id=label,
            detail="the import source escapes the approved import root",
        )
    if not resolved.exists():
        raise DomainError(
            DEFINITION_INVALID, item_id=label, detail="the import source does not exist",
        )
    return resolved


def _hops(root: Path, target: Path) -> list[Path]:
    try:
        relative = target.absolute().relative_to(root.absolute())
    except ValueError:
        return [target.absolute()]
    hops = [root]
    for part in relative.parts:
        hops.append(hops[-1] / part)
    return hops


def _collect(target: Path) -> dict[str, Path]:
    if target.is_file():
        return {target.name: target}
    found = walk_bounded(
        target,
        max_entries=limits.MAX_IMPORT_FILES,
        max_bytes=limits.MAX_IMPORT_TOTAL_BYTES,
        max_depth=limits.MAX_IMPORT_DEPTH,
    )
    return {str(path.relative_to(target)): path for path in found}


def _unsafe_directive(text: str) -> str | None:
    for pattern in _RECURSIVE_RES:
        if pattern.search(text):
            return "recursive-include"
    for pattern in _REMOTE_RES:
        if pattern.search(text):
            return "remote-reference"
    return None


def _read_candidate(target: Path, name: str) -> tuple[dict[str, Any], str]:
    """Re-read and re-check one previewed file when the approval arrives."""
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise DomainError(
            DEFINITION_INVALID, item_id=name,
            detail="a previewed name may not name a path",
        )
    root = target if target.is_dir() else target.parent
    candidate = target if target.is_file() else target / relative
    checked = _inside(root, candidate, label=name)
    data = read_source_bytes(checked)
    text = _decode_text(data, item=name)
    directive = _unsafe_directive(text)
    if directive is not None:
        raise DomainError(
            DEFINITION_INVALID, item_id=name,
            detail=f"a {directive} directive is never followed",
        )
    try:
        mapping = decoder.decode_import_document(text, item=name)
    except DomainError as exc:
        raise DomainError(exc.code, item_id=name, detail=exc.detail) from None
    return mapping, bytes_digest(data)


def _decode_text(data: bytes, *, item: str) -> str:
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise DomainError(
            DEFINITION_INVALID, item_id=item,
            detail=f"is not valid UTF-8 at byte {exc.start}",
        ) from None
    try:
        decoder.check_text(text, item=item, max_bytes=limits.MAX_IMPORT_FILE_BYTES)
    except DomainError as exc:
        raise DomainError(exc.code, item_id=item, detail=exc.detail) from None
    return text


def _preview_file(name: str, path: Path) -> ImportFile:
    """One file's preview verdict: a refusal is a diagnostic, never a write."""
    data = b""
    try:
        data = read_source_bytes(path)
    except DomainError as exc:
        return ImportFile(
            relative_path=name, size_bytes=0, content_digest=_PLACEHOLDER,
            diagnostics=(f"{exc.code}: {exc.detail}",), selectable=False,
        )
    digest = bytes_digest(data)
    try:
        text = _decode_text(data, item=name)
    except DomainError as exc:
        return ImportFile(
            relative_path=name, size_bytes=len(data), content_digest=digest,
            diagnostics=(f"{exc.code}: {exc.detail}",), selectable=False,
        )
    diagnostics: list[str] = []
    directive = _unsafe_directive(text)
    if directive is not None:
        diagnostics.append(
            f"DEFINITION_INVALID: a {directive} directive is never followed"
        )
    try:
        mapping = decoder.decode_import_document(text, item=name)
        revision = decoder.validate_revision(_candidate_revision(
            definition_id="def_previewplaceholder00000000",
            mapping=mapping,
            approval=SourceApproval(
                origin="user-upload", origin_ref=name, content_digest=digest,
                approved_by_principal="preview:anonymous", approved_at=_now(),
            ),
        ))
    except DomainError as exc:
        return ImportFile(
            relative_path=name, size_bytes=len(data), content_digest=digest,
            diagnostics=tuple(diagnostics + [f"{exc.code}: {exc.detail}"]),
            selectable=False,
        )
    if revision.retained_native_fields:
        diagnostics.append(
            "NATIVE_VERSION_UNKNOWN: retained native field(s) "
            + ", ".join(sorted(revision.retained_native_fields))
            + " are kept but never compiled into the effective view"
        )
    return ImportFile(
        relative_path=name, size_bytes=len(data), content_digest=digest,
        diagnostics=tuple(diagnostics), selectable=directive is None,
        declared_slug=str(mapping["slug"]), declared_description=str(mapping["description"]),
    )


def _candidate_revision(
    definition_id: str, mapping: Mapping[str, Any], approval: SourceApproval
) -> DefinitionRevision:
    """A revision DTO for the declared content, with its canonical digest filled in."""
    provisional = DefinitionRevision(
        definition_id=definition_id, revision=1, content_digest=_PLACEHOLDER,
        role_body=str(mapping.get("role_body", "")),
        declared_model_ref=mapping.get("declared_model_ref"),
        tool_refs=tuple(mapping.get("tool_refs", ())),
        mcp_refs=tuple(mapping.get("mcp_refs", ())),
        skill_refs=tuple(mapping.get("skill_refs", ())),
        requested_permission=mapping.get("requested_permission"),
        isolation=dict(mapping.get("isolation", {})),
        limits=dict(mapping.get("limits", {})),
        source=approval,
        retained_native_fields=dict(mapping.get("retained_native_fields", {})),
    )
    return DefinitionRevision(
        **{
            **decoder.revision_mapping(provisional),
            "content_digest": revision_digest(provisional),
        }
    )
