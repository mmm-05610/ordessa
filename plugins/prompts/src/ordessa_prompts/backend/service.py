"""The Prompts public service (contracts.md §1, `prompts.service`).

Owns content and authorisation decisions; the Server plugin surface and
future Profile/Harness consumers call this and nothing else. Invariants
held here:

* identity comes from the service context (``subject_provider``), never
  from a client-declared owner in the request (G06);
* profile-scoped work requires the Profile authorisation port; with the
  port absent the public library is untouched and the dependent call
  refuses (G08);
* logs and error messages carry IDs, revisions, digests and diagnostic
  codes only — prompt bodies are user content and never enter the log
  stream (G05/FR14);
* resolveSnapshot reads all latests inside one transaction and freezes
  the exact revisions (G07).
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from typing import Any, Callable, Mapping, Optional

from ..api import (
    MAX_INSTRUCTIONS_PER_SELECTION,
    SNAPSHOT_MAX_TOTAL_BODY_BYTES,
    DependencyUnavailableError,
    InvalidRequestError,
    LimitExceededError,
    NotFoundError,
    PromptError,
    PromptRef,
    PromptScope,
    PromptSelection,
    PromptSnapshot,
    RefKindMismatchError,
    ResolvedPrompt,
    ScopeRefusedError,
    validate_kind,
    validate_prompt_id,
)
from .records import PromptRecords
from .textio import decode_import_bytes, export_filename

#: The logger this domain writes to. Only the structured facts below ever
#: reach it (G05 asserts the body never does).
logger = logging.getLogger("ordessa.prompts")


def _log_event(code: str, **facts: Any) -> None:
    """The single logging gate: diagnostic code plus IDs/revisions/digests.

    A fact whose value is bytes is recorded as its digest only — body
    text is structurally unable to reach the logger.
    """
    safe = {k: ("sha256:" + hashlib.sha256(v).hexdigest() if isinstance(v, bytes) else v)
            for k, v in facts.items()}
    logger.info("prompts.%s %s", code, safe)


class PromptsService:
    """The business service behind every `prompts.*` wire method."""

    def __init__(self, records: PromptRecords, *,
                 server_scope: str,
                 subject_provider: Callable[[], str],
                 profile_authorization: "Optional[Any]" = None) -> None:
        self._records = records
        self._server_scope = str(server_scope)
        self._subject_provider = subject_provider
        self._profile_auth = profile_authorization

    # -- context helpers -------------------------------------------------------

    @property
    def server_scope(self) -> str:
        return self._server_scope

    def _subject(self) -> str:
        subject = self._subject_provider()
        if not isinstance(subject, str) or not subject:
            raise DependencyUnavailableError(
                "the service context did not supply a caller subject")
        return subject

    def _require_profile_scope_allowed(self, scope: PromptScope) -> None:
        if not scope.is_profile_private:
            return
        if self._profile_auth is None:
            raise DependencyUnavailableError(
                "profile-scoped prompts need the Profile authorisation port,"
                " which this Server does not compose; the public library is"
                " unaffected")
        if not self._profile_auth.is_authorized(self._subject(), str(scope.profile_id)):
            raise ScopeRefusedError(
                f"this caller is not authorised for profile {scope.profile_id!r}")

    def _idempotency(self, operation: str, target: str,
                     key: Optional[str], payload: Mapping[str, Any]
                     ) -> "tuple[str, str, dict[str, Any]]":
        subject = self._subject()
        if key is None:
            # No caller key: still mint one for *this* request so the
            # receipt records the acceptance without claiming replay
            # safety the caller did not ask for.
            key = f"anon-{secrets.token_hex(8)}"
        return (f"{subject}|{operation}|{target}", str(key), dict(payload))

    # -- reads ---------------------------------------------------------------

    def list(self, *, scope: "Optional[Mapping[str, Any]]" = None, kind: Optional[str] = None,
             query: Optional[str] = None, include_archived: bool = False,
             limit: Optional[int] = None, offset: int = 0) -> dict[str, Any]:
        """A page of metadata; the result never carries bodies.

        An unscoped list means *the public library*: the Profile
        authorisation port can only answer "is this caller authorised for
        profile X", never "which profiles exist", so profile-private rows
        are simply not part of an unscoped answer. A caller reaches them
        only by naming their own authorised profile scope (G06).
        """
        parsed_scope = None if scope is None else PromptScope.parse(scope)
        if parsed_scope is None:
            effective_scope: PromptScope = PromptScope("library")
        else:
            self._require_profile_scope_allowed(parsed_scope)
            effective_scope = parsed_scope
        if kind is not None:
            validate_kind(kind)
        page = self._page_limits(limit)
        if offset < 0:
            raise InvalidRequestError("offset must not be negative")
        items, has_more = self._records.list_records(
            scope=effective_scope, kind=kind, query=query,
            include_archived=bool(include_archived), limit=page, offset=int(offset))
        return {"items": [item.as_wire() for item in items],
                "limit": page, "offset": int(offset),
                "nextOffset": (int(offset) + page) if has_more else None}

    @staticmethod
    def _page_limits(limit: Optional[int]) -> int:
        if limit is None:
            return 50
        limit = int(limit)
        if limit < 1 or limit > 100:
            raise LimitExceededError(
                "page limit must be between 1 and 100", requested=limit)
        return limit

    def get(self, prompt_id: str) -> dict[str, Any]:
        record = self._records.get_record(validate_prompt_id(prompt_id))
        self._require_profile_scope_allowed(record.scope)
        revision = self._records.get_revision(record.id)
        return record.as_wire(include_body=True, body=revision.body) \
            | {"sha256": revision.sha256, "bodyByteSize": len(revision.body)}

    def get_revision(self, prompt_id: str, revision: Optional[int] = None) -> dict[str, Any]:
        record = self._records.get_record(validate_prompt_id(prompt_id))
        self._require_profile_scope_allowed(record.scope)
        rev = self._records.get_revision(record.id, revision)
        return rev.as_wire()

    # -- writes --------------------------------------------------------------

    def create(self, *, kind: str, scope: "Mapping[str, Any]", title: str,
               description: Optional[str], body: bytes,
               operation_key: Optional[str] = None) -> dict[str, Any]:
        parsed_scope = PromptScope.parse(scope)
        self._require_profile_scope_allowed(parsed_scope)
        payload = {"kind": kind, "scope": parsed_scope.as_wire(), "title": title,
                   "description": description, "body": bytes(body)}
        outcome, response = self._records.create(
            kind=kind, scope=parsed_scope, title=title, description=description,
            body=bytes(body),
            idempotency=self._idempotency("create", parsed_scope.kind
                                          + (f":{parsed_scope.profile_id}"
                                             if parsed_scope.profile_id else ""),
                                          operation_key, payload))
        _log_event("created", replay=(outcome == "replay"), id=response["id"],
                   revision=response["latestRevision"], sha256=response["sha256"])
        return dict(response, replayed=outcome == "replay")

    def update(self, prompt_id: str, *, expected_metadata_version: int,
               expected_latest_revision: int, patch: Mapping[str, Any],
               operation_key: Optional[str] = None) -> dict[str, Any]:
        record = self._records.get_record(validate_prompt_id(prompt_id))
        self._require_profile_scope_allowed(record.scope)
        clean_patch = dict(patch)
        if "body" in clean_patch and isinstance(clean_patch["body"], str):
            clean_patch["body"] = clean_patch["body"].encode("utf-8")
        outcome, response = self._records.update(
            prompt_id=record.id,
            expected_metadata_version=int(expected_metadata_version),
            expected_latest_revision=int(expected_latest_revision),
            patch=clean_patch,
            idempotency=self._idempotency("update", record.id, operation_key,
                                          {"patch": {k: (v.hex() if isinstance(v, bytes) else v)
                                                     for k, v in clean_patch.items()},
                                           "expectedMetadataVersion": expected_metadata_version,
                                           "expectedLatestRevision": expected_latest_revision}))
        _log_event("updated", replay=(outcome == "replay"), id=response["id"],
                   revision=response["latestRevision"])
        return dict(response, replayed=outcome == "replay")

    def clone(self, source_id: str, *, target_scope: "Mapping[str, Any]", title: str,
              source_revision: Optional[int] = None,
              operation_key: Optional[str] = None) -> dict[str, Any]:
        source = self._records.get_record(validate_prompt_id(source_id))
        self._require_profile_scope_allowed(source.scope)
        parsed_target = PromptScope.parse(target_scope)
        self._require_profile_scope_allowed(parsed_target)
        if source.scope.is_profile_private and not parsed_target.is_profile_private:
            # An explicit "copy into the library" is allowed only when the
            # caller is *also* authorised for the source profile (checked
            # above); nothing is silently promoted without that consent.
            pass
        outcome, response = self._records.clone(
            source_id=source.id, source_revision=source_revision,
            target_scope=parsed_target, title=title,
            idempotency=self._idempotency("clone", source.id, operation_key,
                                          {"targetScope": parsed_target.as_wire(),
                                           "title": title,
                                           "sourceRevision": source_revision}))
        _log_event("cloned", replay=(outcome == "replay"), id=response["id"],
                   sourceId=source.id, sha256=response["sha256"])
        return dict(response, replayed=outcome == "replay")

    def archive(self, prompt_id: str, *, expected_metadata_version: int,
                operation_key: Optional[str] = None) -> dict[str, Any]:
        return self._set_archived(prompt_id, archived=True,
                                  expected_metadata_version=expected_metadata_version,
                                  operation_key=operation_key)

    def restore(self, prompt_id: str, *, expected_metadata_version: int,
                operation_key: Optional[str] = None) -> dict[str, Any]:
        return self._set_archived(prompt_id, archived=False,
                                  expected_metadata_version=expected_metadata_version,
                                  operation_key=operation_key)

    def _set_archived(self, prompt_id: str, *, archived: bool,
                      expected_metadata_version: int,
                      operation_key: Optional[str]) -> dict[str, Any]:
        record = self._records.get_record(validate_prompt_id(prompt_id))
        self._require_profile_scope_allowed(record.scope)
        outcome, response = self._records.set_archived(
            prompt_id=record.id, expected_metadata_version=expected_metadata_version,
            archived=archived,
            idempotency=self._idempotency("archive" if archived else "restore",
                                          record.id, operation_key,
                                          {"expectedMetadataVersion": expected_metadata_version}))
        _log_event("archived" if archived else "restored",
                   replay=(outcome == "replay"), id=record.id,
                   metadataVersion=response["metadataVersion"])
        return dict(response, replayed=outcome == "replay")

    # -- import/export ----------------------------------------------------------

    def import_text(self, content: bytes, *, filename_hint: Optional[str] = None,
                    kind: str = "instruction", scope: "Mapping[str, Any]" = None,
                    title: Optional[str] = None,
                    operation_key: Optional[str] = None) -> dict[str, Any]:
        """Upload-selected UTF-8 text becomes an ordinary create.

        No path is dereferenced here: the bytes arrived from the client's
        own picker (G04/FR15).
        """
        if scope is None:
            scope = {"kind": "library"}
        imported = decode_import_bytes(content, filename_hint=filename_hint)
        created = self.create(
            kind=kind, scope=scope,
            title=title or imported.suggested_title,
            description=None, body=imported.body,
            operation_key=operation_key)
        return dict(created, bomStripped=imported.bom_stripped,
                    sourceKind="uploaded-content")

    def export_text(self, prompt_id: str, revision: Optional[int] = None) -> dict[str, Any]:
        record = self._records.get_record(validate_prompt_id(prompt_id))
        self._require_profile_scope_allowed(record.scope)
        rev = self._records.get_revision(record.id, revision)
        return {"promptId": record.id, "revision": rev.revision,
                "kind": record.kind, "title": record.title,
                "sha256": rev.sha256, "bodyBase64": _b64(rev.body),
                "suggestedFilename": export_filename(record.kind, record.title, rev.revision)}

    # -- snapshot / preview -------------------------------------------------------

    def resolve_snapshot(self, selection: "Mapping[str, Any]", *,
                         profile_revision: Optional[int] = None,
                         overlay_revision: Optional[int] = None) -> PromptSnapshot:
        """Freeze one selection's contents at one instant (G07).

        Returns bytes to authorised callers only; performs no native
        side effect (contracts.md §1).
        """
        parsed = PromptSelection.parse(selection)
        order, persona, replacement = self._validated_selection(parsed)
        rows = self._records.resolve_latest([
            *order,
            *[ref for ref in (persona, replacement) if ref is not None]])
        by_id = {str(row["prompt_id"]): row for row in rows}
        # every slot checks the record's purpose: an instruction slot takes
        # only instruction content, persona only persona, and the
        # replacement only a replacement (contracts.md §2 "用途").
        resolved = [self._resolved_from(by_id, ref, "instruction")
                    for ref in order]
        persona_resolved = (None if persona is None
                            else self._resolved_from(by_id, persona, "persona"))
        replacement_resolved = (None if replacement is None
                                else self._resolved_from(by_id, replacement,
                                                         "system-replacement"))
        total = sum(len(item.body) for item in resolved)
        for extra in (persona_resolved, replacement_resolved):
            if extra is not None:
                total += len(extra.body)
        if total > SNAPSHOT_MAX_TOTAL_BODY_BYTES:
            # Refuse before application; a snapshot is never silently cut.
            raise LimitExceededError(
                f"a resolved snapshot may hold at most {SNAPSHOT_MAX_TOTAL_BODY_BYTES}"
                " bytes of body total", totalBytes=total)
        ordered_items = list(resolved)
        if persona_resolved is not None:
            ordered_items.append(persona_resolved)
        if replacement_resolved is not None:
            ordered_items.append(replacement_resolved)
        digest_payload = "|".join(f"{item.prompt_id}:{item.revision}:{item.sha256}"
                                  for item in ordered_items)
        snapshot = PromptSnapshot(
            snapshot_id=f"snapshot_{secrets.token_hex(8)}",
            server_scope=self._server_scope,
            resolved=tuple(ordered_items),
            instructions_order=tuple(item.prompt_id for item in resolved),
            persona_id=None if persona_resolved is None else persona_resolved.prompt_id,
            system_replacement_id=(None if replacement_resolved is None
                                   else replacement_resolved.prompt_id),
            source_metadata_versions={
                str(row["prompt_id"]): int(row["metadata_version"]) for row in rows},
            content_digest="sha256:" + hashlib.sha256(
                digest_payload.encode("utf-8")).hexdigest(),
            profile_revision=profile_revision,
            overlay_revision=overlay_revision,
        )
        _log_event("snapshot_resolved", snapshotId=snapshot.snapshot_id,
                   items=len(ordered_items), contentDigest=snapshot.content_digest)
        return snapshot

    def preview(self, selection: "Mapping[str, Any]") -> dict[str, Any]:
        """The same source as resolve_snapshot; labels exactly what is
        known and never claims to be the native full system prompt."""
        snapshot = self.resolve_snapshot(selection)
        return {
            "basis": "same-transaction snapshot as resolve_snapshot",
            "compositionOrder": (
                ["system-replacement"] if snapshot.system_replacement_id else [])
            + (["persona"] if snapshot.persona_id else [])
            + [f"instruction:{pid}" for pid in snapshot.instructions_order],
            "revisions": {item.prompt_id: item.revision for item in snapshot.resolved},
            "totalBodyBytes": snapshot.total_body_bytes(),
            "contentDigest": snapshot.content_digest,
            "diagnostics": ["ORDINA_COMPOSITION_ORDER_NOTE",
                            "NOT_NATIVE_FULL_SYSTEM_PROMPT"],
            "claim": ("This is the Ordessa-configured content only; it is not a"
                      " claim about the native full system prompt."),
        }

    # -- selection validation ------------------------------------------------------

    def _validated_selection(self, parsed: PromptSelection):
        order = [ref.prompt_id for ref in parsed.instructions]
        if len(order) > MAX_INSTRUCTIONS_PER_SELECTION:
            raise InvalidRequestError("too many instructions in the selection")
        candidates = list(order) + [ref.prompt_id for ref in
                                    (parsed.persona, parsed.system_replacement)
                                    if ref is not None]
        for prompt_id in candidates:
            record = self._records.get_record(validate_prompt_id(prompt_id))
            # Profile-private content resolves only for its own profile and
            # only when the caller is authorised (G06): A's content can
            # never be read through B's selection.
            if record.scope.is_profile_private:
                if self._profile_auth is None:
                    raise DependencyUnavailableError(
                        "resolving profile-private content needs the Profile"
                        " authorisation port")
                if not self._profile_auth.is_authorized(self._subject(),
                                                        str(record.scope.profile_id)):
                    raise ScopeRefusedError(
                        f"prompt {record.id!r} is private to another profile")
        return (tuple(order),
                None if parsed.persona is None else parsed.persona.prompt_id,
                None if parsed.system_replacement is None
                else parsed.system_replacement.prompt_id)

    @staticmethod
    def _resolved_from(by_id: Mapping[str, Mapping[str, Any]], prompt_id: str,
                       expected_kind: Optional[str]) -> ResolvedPrompt:
        row = by_id.get(prompt_id)
        if row is None:
            raise NotFoundError(f"no prompt {prompt_id!r} to resolve")
        if expected_kind is not None and row["kind"] != expected_kind:
            raise RefKindMismatchError(
                f"prompt {prompt_id!r} has kind {row['kind']!r},"
                f" the slot needs {expected_kind!r}")
        return ResolvedPrompt(
            prompt_id=prompt_id, kind=str(row["kind"]), revision=int(row["revision"]),
            sha256=str(row["sha256"]), body=bytes(row["body"]), title=str(row["title"]))


def _b64(data: bytes) -> str:
    import base64
    return base64.b64encode(data).decode("ascii")
