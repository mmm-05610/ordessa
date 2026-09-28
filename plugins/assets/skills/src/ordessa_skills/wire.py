"""The `skills.*` wire family: param shapes, value validation, handlers.

Split from `plugin.py` so the descriptor table stays reviewable. The host's
dispatch wall (`WireService.dispatch`) already enforces the declared
required/unknown-param shape (`ServerMethodDescriptor.required_params` /
`optional_params`); this module adds the value-level bounds the domain
identity rules require (`api/identity.py`, `assignments/model.py`).

Refusal vocabulary: validators raise the domain's `AssetDomainError` with
code ``INVALID_REQUEST``; the wire boundary converts every domain refusal
into the published internal error (`server_plugin_api.ServerError`, see
`error_families.to_server_error`) and the host's dispatch projects it onto
the wire family through THIS composition's `wire.error-families`
contribution (`error_families.SKILLS_ERROR_FAMILIES`, carried by the
registration's `ContributionBatch` in `plugin.py`). The original
`AssetDomainError` stays the exception's documented `__cause__` chain —
callers and tests still read the domain type and its `.code`. The old note
("no plugin-visible typed-refusal error type exists") recorded the api-
requests.md §G1 gap; foundation's T014-S2a/S2c seam closed it, and this
package consumes it instead of leaning on the generic
``UNAVAILABLE/internalCode=<class name>`` fall-through.

Nothing in this module accepts an owner, a principal, a server scope or a
filesystem path from the request (contracts.md: 不接受自报 owner 或任意本地
文件路径). Import content moves exclusively through the bounded chunk
protocol (`importBegin/importChunk`), never a `sourcePath` param — an
unknown param name is refused by the host's own shape wall.
"""
from __future__ import annotations

import base64
import binascii
import re
from typing import Any, Callable, Mapping

from server_plugin_api import ServerMethodDescriptor

from .api.errors import AssetDomainError
from .api.identity import ASSET_ID
from .assignments import SCOPE_KINDS
from .assignments.model import DECISIONS
from .error_families import to_server_error
from .library.import_transfer import MAX_CHUNK_BYTES
from .profile_facet import session_overrides_from
from .service import SkillsService

#: Wire-visible caps (bounded declarations, requirement 2).
MAX_FILES_PER_IMPORT = 512
MAX_SESSION_OVERRIDES = 64
_HARNESS_ID = re.compile(r"[a-z][a-z0-9._-]{0,63}\Z")
_HEX64 = re.compile(r"\Asha256:[0-9a-f]{64}\Z|[0-9a-f]{64}\Z")
_SOURCE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")

_INVALID = "INVALID_REQUEST"


def _refusal(message: str, detail: str | None = None) -> AssetDomainError:
    return AssetDomainError(_INVALID, message, detail=detail)


def _text(value: Any, name: str, limit: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise _refusal(f"{name} must be a bounded non-empty string")
    return value


def _maybe_text(value: Any, name: str, limit: int = 4096) -> str | None:
    if value is None:
        return None
    return _text(value, name, limit)


def _asset_id(value: Any, name: str = "assetId") -> str:
    if not isinstance(value, str) or ASSET_ID.fullmatch(value) is None:
        raise _refusal(f"{name} must be a lowercase asset slug")
    return value


def _harness_id(value: Any, name: str = "harnessId") -> str:
    if not isinstance(value, str) or _HARNESS_ID.fullmatch(value) is None:
        raise _refusal(f"{name} must be a lowercase harness token")
    return value


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _refusal(f"{name} must be a positive integer")
    return value


def _non_negative_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _refusal(f"{name} must be a non-negative integer")
    return value


def _decision(value: Any) -> str:
    if value not in DECISIONS:
        raise _refusal("decision must be one of enable|disable")
    return str(value)


def _scope_kind(value: Any) -> str:
    if value not in SCOPE_KINDS:
        raise _refusal("scopeKind must be one of user_global|project")
    return str(value)


def _digest_hex(value: Any, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise _refusal(f"{name} must be a sha256 digest (hex, optional sha256: prefix)")
    return value


def _source_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise _refusal("source must be a non-empty object")
    if any(not isinstance(key, str) for key in value):
        raise _refusal("source keys must be strings")
    if len(str(value)) > 2048:
        raise _refusal("source exceeds the bound")
    kind = value.get("kind")
    if kind not in ("local", "git", "catalog"):
        raise _refusal("source.kind must be one of local|git|catalog")
    return {str(key): item for key, item in value.items()}


def _declared_files(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value \
            or len(value) > MAX_FILES_PER_IMPORT:
        raise _refusal("files must be a non-empty bounded list")
    declared: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping) or not {"path", "bytes", "sha256"} <= set(item):
            raise _refusal("each file needs path, bytes and sha256")
        path = _text(item["path"], "file path", 512)
        size = _non_negative_int(item["bytes"], "file bytes")
        digest = str(item["sha256"])
        if not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", digest):
            raise _refusal("file sha256 must be a lowercase hex digest")
        declared.append({"path": path, "bytes": size, "sha264": None,
                         "sha256": digest})
    for item in declared:
        item.pop("sha264")
    return declared


def _overrides(value: Any) -> tuple:
    if not isinstance(value, list) or len(value) > MAX_SESSION_OVERRIDES:
        raise _refusal("sessionOverrides must be a bounded list")
    for item in value:
        if not isinstance(item, Mapping) or "assetId" not in item \
                or "decision" not in item:
            raise _refusal("each session override needs assetId and decision")
        _asset_id(item["assetId"], "override assetId")
    return session_overrides_from(value)


# -- availability predicates (the hello answer only, never a dispatch gate) ---

def _supported() -> "tuple[bool, str | None]":
    return True, None


def _native_unknown() -> "tuple[bool, str | None]":
    #: Re-evaluated against the merged harness-api (`ordessa_harness_api`,
    #: publication `d3f026904e`): the API publishes the APPLY side
    #: (adapter compile/verify, ConfigurationService, target handles handed
    #: to the adapter at apply time) but NO plugin-queryable read handle or
    #: observation port for the authorized guest/instance root — a Server
    #: plugin still cannot obtain the root the bounded observer may read.
    #: api-requests.md §G2 (read half) therefore stays open, and no
    #: truthful `supported` answer is possible (contracts.md
    #: 不可用不以静默过滤达成"成功").
    return False, ("NATIVE_TARGET_ROOT_UNAVAILABLE: the authorized guest/"
                   "instance root still has no published read seam — "
                   "harness-api merged at d3f026904e exposes apply-time "
                   "targets only (api-requests.md §G2 read half open)")


def _invoke_unknown() -> "tuple[bool, str | None]":
    #: Re-evaluated against the merged API: it publishes no invocation
    #: route either, and the frozen evidence is unchanged — all three
    #: controlled brands answer `unknown` for the explicit-invocation axis
    #: (specs/011-q1-skills/research/brand-matrix.md §2 and §6 rows: no
    #: brand-verified in-session explicit invocation route).
    return False, ("INVOKE_DESCRIPTOR_UNKNOWN: every brand (claude, codex, "
                   "pi) is browse-only; no verified invocation route "
                   "(research/brand-matrix.md)")


def build_methods(service: SkillsService, *, owner: str) -> tuple[ServerMethodDescriptor, ...]:
    """The whole `skills.*` surface, declared atomically (one table)."""

    # -- handlers -------------------------------------------------------------

    def skills_list(params: Mapping[str, Any]) -> Any:
        kind = params.get("kind")
        if kind is not None and kind != "skill":
            raise _refusal("this domain serves the skill kind only")
        return service.list_assets()

    def skills_get(params: Mapping[str, Any]) -> Any:
        return service.get_asset(_asset_id(params["assetId"]))

    def skills_revisions(params: Mapping[str, Any]) -> Any:
        return service.list_revisions(_asset_id(params["assetId"]))

    def skills_preview(params: Mapping[str, Any]) -> Any:
        return service.preview(_asset_id(params["assetId"]),
                               _positive_int(params["revision"], "revision"),
                               _text(params["path"], "path", 512))

    def skills_diff(params: Mapping[str, Any]) -> Any:
        return service.diff(
            _asset_id(params["assetId"]),
            _positive_int(params["fromRevision"], "fromRevision"),
            _positive_int(params["toRevision"], "toRevision"),
            path=_maybe_text(params.get("path"), "path", 512))

    def skills_import_begin(params: Mapping[str, Any]) -> Any:
        return service.import_begin(
            files=_declared_files(params["files"]),
            total_bytes=_non_negative_int(params["totalBytes"], "totalBytes"))

    def skills_import_chunk(params: Mapping[str, Any]) -> Any:
        encoded = _text(params["payloadBase64"], "payloadBase64",
                        4 * ((MAX_CHUNK_BYTES + 2) // 3) + 8)
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise _refusal("payloadBase64 is not valid base64") from exc
        return service.import_chunk(
            _text(params["importId"], "importId", 128),
            index=_non_negative_int(params["chunkIndex"], "chunkIndex"),
            payload=payload,
            sha256=_digest_hex(params["sha256"], "sha256"))

    def skills_import_preview(params: Mapping[str, Any]) -> Any:
        return service.import_preview(
            _text(params["importId"], "importId", 128),
            _source_mapping(params["source"]))

    def skills_import_commit(params: Mapping[str, Any]) -> Any:
        return service.import_commit(
            _text(params["importId"], "importId", 128),
            asset_id=_asset_id(params["assetId"]),
            revision=_positive_int(params["revision"], "revision"))

    def skills_import_cancel(params: Mapping[str, Any]) -> Any:
        return service.import_cancel(_text(params["importId"], "importId", 128))

    def skills_sources_check_update(params: Mapping[str, Any]) -> Any:
        source_id = params["sourceId"]
        if not isinstance(source_id, str) or _SOURCE_ID.fullmatch(source_id) is None:
            raise _refusal("sourceId must be a lowercase slug")
        return service.check_update(source_id)

    def skills_approve_revision(params: Mapping[str, Any]) -> Any:
        return service.approve_revision(
            asset_id=_asset_id(params["assetId"]),
            revision=_positive_int(params["revision"], "revision"),
            approved_by=_maybe_text(params.get("approvedBy"), "approvedBy", 128)
            or "user",
            expected_digest=(None if params.get("expectedDigest") is None
                             else _digest_hex(params["expectedDigest"],
                                              "expectedDigest")))

    def skills_assignments_list(params: Mapping[str, Any]) -> Any:
        scope_kind = params.get("scopeKind")
        harness_id = params.get("harnessId")
        return service.assignments_list(
            scope_kind=None if scope_kind is None else _scope_kind(scope_kind),
            scope_id=_maybe_text(params.get("scopeId"), "scopeId", 128),
            harness_key=None if harness_id is None else _harness_id(harness_id),
            asset_id=(None if params.get("assetId") is None
                      else _asset_id(params["assetId"])))

    def skills_assignments_upsert(params: Mapping[str, Any]) -> Any:
        scope_kind = _scope_kind(params["scopeKind"])
        scope_id = _maybe_text(params.get("scopeId"), "scopeId", 128)
        if scope_kind == "project" and scope_id is None:
            raise _refusal("a project assignment needs scopeId (the authorized "
                           "workspace id)")
        decision = _decision(params["decision"])
        revision = params.get("revision")
        if decision == "enable" and revision is None:
            raise _refusal("an enable assignment must pin a revision")
        expected = params.get("expectedVersion")
        operation = params.get("operationKey")
        return service.upsert_assignment(
            scope_kind=scope_kind, scope_id=scope_id or "",
            harness_id=(None if params.get("harnessId") is None
                        else _harness_id(params["harnessId"])),
            asset_id=_asset_id(params["assetId"]), decision=decision,
            revision=None if revision is None
            else _positive_int(revision, "revision"),
            expected_version=None if expected is None
            else _non_negative_int(expected, "expectedVersion"),
            operation_key=None if operation is None
            else _text(operation, "operationKey", 128))

    def skills_assignments_remove(params: Mapping[str, Any]) -> Any:
        scope_kind = _scope_kind(params["scopeKind"])
        scope_id = _maybe_text(params.get("scopeId"), "scopeId", 128)
        if scope_kind == "project" and scope_id is None:
            raise _refusal("a project removal needs scopeId")
        expected = params.get("expectedVersion")
        operation = params.get("operationKey")
        return service.remove_assignment(
            scope_kind=scope_kind, scope_id=scope_id or "",
            harness_id=(None if params.get("harnessId") is None
                        else _harness_id(params["harnessId"])),
            asset_id=_asset_id(params["assetId"]),
            expected_version=None if expected is None
            else _non_negative_int(expected, "expectedVersion"),
            operation_key=None if operation is None
            else _text(operation, "operationKey", 128))

    def _resolve_params(params: Mapping[str, Any]) -> Any:
        return service.resolve(
            project_id=_maybe_text(params.get("projectId"), "projectId", 128),
            harness_id=(None if params.get("harnessId") is None
                        else _harness_id(params["harnessId"])),
            profile_id=_maybe_text(params.get("profileId"), "profileId", 128),
            session_ref=_maybe_text(params.get("sessionRef"), "sessionRef", 128) or "",
            runtime_generation=_non_negative_int(
                params.get("runtimeGeneration", 0), "runtimeGeneration"),
            session_overrides=_overrides(params.get("sessionOverrides", [])))

    def skills_resolve(params: Mapping[str, Any]) -> Any:
        return _resolve_params(params)

    def skills_preview_effective(params: Mapping[str, Any]) -> Any:
        return _resolve_params(params)

    def skills_discover_native(params: Mapping[str, Any]) -> Any:
        return service.discover_native(_harness_id(params["harnessId"]))

    def skills_invoke_descriptor(params: Mapping[str, Any]) -> Any:
        return service.invoke_descriptor(_harness_id(params["harnessId"]))

    # -- the table -------------------------------------------------------------

    def typed(handler: Callable[[Mapping[str, Any]], Any]
              ) -> Callable[[Mapping[str, Any]], Any]:
        """The published-refusal boundary of one `skills.*` handler.

        The domain keeps raising `AssetDomainError` (its stores and the
        resolver refuse in their own vocabulary); at the wire edge the
        refusal is projected onto `server_plugin_api.ServerError`, so the
        host dispatch resolves its family through this composition's
        contributed `wire.error-families` rows instead of flattening the
        exception into the generic class-name fall-through. The original
        domain error stays on the cause chain (`raise ... from exc`), so
        callers outside the wire — and the refusal tests reading
        `__cause__.code` — still see the domain type verbatim.
        """
        def guarded(params: Mapping[str, Any]) -> Any:
            try:
                return handler(params)
            except AssetDomainError as exc:
                raise to_server_error(exc) from exc
        return guarded

    def row(method_id: str, required: "set[str]", optional: "set[str]",
            handler: Callable[[Mapping[str, Any]], Any],
            availability: Callable[[], "tuple[bool, str | None]"] = _supported
            ) -> ServerMethodDescriptor:
        return ServerMethodDescriptor(
            method_id=method_id,
            required_params=frozenset(required | {"requestId"}),
            optional_params=frozenset(optional),
            handler=typed(handler), owner=owner, availability=availability,
        )

    return (
        row("skills.list", set(), {"kind"}, skills_list),
        row("skills.get", {"assetId"}, set(), skills_get),
        row("skills.revisions", {"assetId"}, set(), skills_revisions),
        row("skills.preview", {"assetId", "revision", "path"}, set(), skills_preview),
        row("skills.diff", {"assetId", "fromRevision", "toRevision"}, {"path"},
            skills_diff),
        row("skills.importBegin", {"files", "totalBytes"}, set(), skills_import_begin),
        row("skills.importChunk",
            {"importId", "chunkIndex", "payloadBase64", "sha256"}, set(),
            skills_import_chunk),
        row("skills.importPreview", {"importId", "source"}, set(),
            skills_import_preview),
        row("skills.importCommit", {"importId", "assetId", "revision"}, set(),
            skills_import_commit),
        row("skills.importCancel", {"importId"}, set(), skills_import_cancel),
        row("skills.sourcesCheckUpdate", {"sourceId"}, set(),
            skills_sources_check_update),
        row("skills.approveRevision", {"assetId", "revision"},
            {"approvedBy", "expectedDigest"}, skills_approve_revision),
        row("skills.assignmentsList", set(),
            {"scopeKind", "scopeId", "harnessId", "assetId"},
            skills_assignments_list),
        row("skills.assignmentsUpsert",
            {"scopeKind", "assetId", "decision"},
            {"scopeId", "harnessId", "revision", "expectedVersion",
             "operationKey"}, skills_assignments_upsert),
        row("skills.assignmentsRemove", {"scopeKind", "assetId"},
            {"scopeId", "harnessId", "expectedVersion", "operationKey"},
            skills_assignments_remove),
        row("skills.resolve", set(),
            {"projectId", "harnessId", "profileId", "sessionRef",
             "runtimeGeneration", "sessionOverrides"}, skills_resolve),
        row("skills.previewEffective", set(),
            {"projectId", "harnessId", "profileId", "sessionRef",
             "runtimeGeneration", "sessionOverrides"}, skills_preview_effective),
        row("skills.discoverNative", {"harnessId"}, set(), skills_discover_native,
            availability=_native_unknown),
        row("skills.invokeDescriptor", {"harnessId"}, set(),
            skills_invoke_descriptor, availability=_invoke_unknown),
    )


#: The declared method ids in one place: the tests and the §G1 product
#: registration read this instead of re-listing the table.
SKILLS_METHOD_IDS = (
    "skills.list", "skills.get", "skills.revisions", "skills.preview",
    "skills.diff", "skills.importBegin", "skills.importChunk",
    "skills.importPreview", "skills.importCommit", "skills.importCancel",
    "skills.sourcesCheckUpdate", "skills.approveRevision",
    "skills.assignmentsList", "skills.assignmentsUpsert",
    "skills.assignmentsRemove", "skills.resolve", "skills.previewEffective",
    "skills.discoverNative", "skills.invokeDescriptor",
)
