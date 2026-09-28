"""Skills-side compile INPUTS: managed content coordinates and the
generation binding, plus the host-path guard.

STATUS (after the harness-api checkpoint, publication `d3f026904e`): the
interim intent vocabulary this module used to carry — the Skills-side
`IntentSet`/`MountRevision`/`RemoveOwnedContent`/`ReloadSession`/
`RestartAndResume`/`LoadControl` dataclasses — is DELETED. The published
`ordessa_harness_api` vocabulary (MountContent, RemoveOwnedContent,
SetField, ResetField, BindSecret, InvokeAction, IntentSource, ContentRef,
TargetHandle, IntentSet) is the only intent vocabulary in this domain;
`contribution.py` builds those real types from the inputs defined here.
Keeping two vocabularies is exactly what docs/design/harness-v2/
contracts.md §C3 forbids, so nothing here names an intent any more.

What REMAINS and why it is not a second vocabulary:

* `ManagedContentRef` — the Skills-domain *input record* (one resolved
  revision's content coordinates {assetId, revision, treeDigest,
  nativeName, sizeBytes}) the compile step maps onto
  `ContentRef{reference, sha256, size}` + `MountContent.relative_name`.
  It is library data, not an operation on a target.
* `GenerationBounds` — the frozen snapshot face (data-model.md
  SkillSnapshot: runtimeGeneration/projectId/profileRevision/
  assignmentRevision) a one-shot compile is pinned to; on the published
  side this face lives in `ApplicationTarget` (runtime generation) and
  the plan's revision fences (`Plan.before_revision`,
  `DesiredFragment.source_revision`), so the bounds ride with the
  projection record, not inside an intent.
* `looks_like_absolute_host_path` and the recursive sweep — the design
  rule "由 Harness 从自身私有内容装载目标操作, 不信适配器给任意绝对
  路径" (contracts.md §Harness 配置贡献). The published `_relative_name`
  check admits shapes this rule forbids (a Windows drive with forward
  slashes like `C:/skills`, `~/x`, `file:///x` pass its segment test),
  so the adapter sweeps every string BEFORE constructing a published
  DTO, and the sweep refuses with the stable `SKILL_INTENT_HOST_PATH`
  code. Targets are named by logical slot labels ("skills",
  ".claude/skills") resolved by the Harness against its own private
  generation directory.
"""
from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from typing import Any, Mapping

from ..api.errors import AssetDomainError
from ..api.identity import ASSET_ID, SKILL_NAME

#: The one refusal code for a payload that tries to smuggle a host path.
HOST_PATH_CODE = "SKILL_INTENT_HOST_PATH"

_ID_MAX_CHARS = 128

#: Bounded, path-free tokens for the generation binding (data-model.md:
#: runtimeGeneration / projectId are opaque stable ids; profileRevision /
#: assignmentRevision are integers).
GENERATION_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_TREE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class SkillIntentError(AssetDomainError):
    """A compile input was refused before it could ever reach a Harness."""


def looks_like_absolute_host_path(value: str) -> bool:
    """POSIX-absolute, home-relative, Windows drive or UNC shapes — all of
    which an adapter has no business naming (contracts §Harness 配置贡献)."""
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if not stripped:
        return False
    return (
        stripped.startswith("/")
        or stripped.startswith("~/") or stripped == "~"
        or stripped.startswith("\\\\")
        or bool(re.match(r"^[A-Za-z]:[\\/]", stripped))
        or "://" in stripped
    )


def _check_host_path_free(value: Any, where: str) -> None:
    if isinstance(value, str):
        if looks_like_absolute_host_path(value):
            raise SkillIntentError(
                HOST_PATH_CODE,
                f"{where} must be a bounded relative label, not an absolute"
                f" host path: {value!r}")
        if len(value) > _ID_MAX_CHARS:
            raise SkillIntentError(
                "SKILL_INTENT_UNBOUNDED",
                f"{where} exceeds {_ID_MAX_CHARS} characters")
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _check_host_path_free(key, f"{where}.key")
            _check_host_path_free(item, f"{where}[{key!r}]")
    elif isinstance(value, (tuple, list, frozenset)):
        for index, item in enumerate(value):
            _check_host_path_free(item, f"{where}[{index}]")
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            _check_host_path_free(getattr(value, field.name),
                                  f"{type(value).__name__}.{field.name}")


def _validate_host_path_free(instance: Any) -> None:
    """Recursively sweep every string field of a compile input."""
    _check_host_path_free(instance, type(instance).__name__)


def sweep_host_path_free(value: Any, where: str) -> None:
    """Sweep an arbitrary (JSON-ish) compile payload, refusing any string
    that names an absolute host location. Public entry point used by
    `base`/`contribution` before any published DTO is constructed."""
    _check_host_path_free(value, where)


def _check_token(value: str, where: str) -> None:
    if GENERATION_TOKEN.fullmatch(value) is None:
        # Give the path smuggler its own dedicated, stable code.
        if looks_like_absolute_host_path(value):
            raise SkillIntentError(
                HOST_PATH_CODE,
                f"{where} must be a bounded token, not an absolute host path")
        raise SkillIntentError("SKILL_INTENT_INVALID",
                               f"{where} is not a bounded opaque token")


@dataclass(frozen=True)
class ManagedContentRef:
    """The only way Skills names a skill to a Harness: content coordinates.

    ``assetId``/``revision``/``treeDigest``/``nativeName`` (+``sizeBytes``,
    the byte count the published ``ContentRef`` demands) — exactly what
    contracts.md §Harness 配置贡献 allows in a payload. Never a file path,
    never a URL.
    """

    asset_id: str
    revision: int
    tree_digest: str
    native_name: str
    #: Required to build a published ContentRef (an honest byte count);
    #: kept optional so pre-API domain records still construct, but
    #: `content_ref_for` refuses to fabricate a size.
    size_bytes: int | None = None

    def __post_init__(self) -> None:
        _validate_host_path_free(self)
        if ASSET_ID.fullmatch(self.asset_id) is None:
            raise SkillIntentError(
                "SKILL_INTENT_INVALID",
                f"asset_id {self.asset_id!r} is not a valid assetId")
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) \
                or self.revision < 1:
            raise SkillIntentError(
                "SKILL_INTENT_INVALID", "revision must be a positive int")
        if _TREE_DIGEST.fullmatch(self.tree_digest) is None:
            raise SkillIntentError(
                "SKILL_INTENT_INVALID",
                "tree_digest must be a sha256:<64 hex> digest")
        if SKILL_NAME.fullmatch(self.native_name) is None:
            raise SkillIntentError(
                "SKILL_INTENT_INVALID",
                f"native_name {self.native_name!r} is not a lowercase slug")
        if self.size_bytes is not None and (
                isinstance(self.size_bytes, bool)
                or not isinstance(self.size_bytes, int)
                or self.size_bytes < 0):
            raise SkillIntentError(
                "SKILL_INTENT_INVALID",
                "size_bytes must be a non-negative int when given")

    def public_dict(self) -> dict[str, Any]:
        return {
            "assetId": self.asset_id,
            "revision": self.revision,
            "treeDigest": self.tree_digest,
            "nativeName": self.native_name,
            "sizeBytes": self.size_bytes,
        }


@dataclass(frozen=True)
class GenerationBounds:
    """The bound every one-shot compile must pin the set to (data-model.md
    SkillSnapshot): a frozen generation/project/profile/assignments face.

    On the published side this face is carried by `ApplicationTarget`
    (runtime generation) and the plan/fragment revision fences; here it
    rides on the projection record so a preview compile is honest about
    which frozen face it was computed against.
    """

    runtime_generation: str
    project_id: str
    profile_revision: int
    assignment_revision: int

    def __post_init__(self) -> None:
        _validate_host_path_free(self)
        _check_token(self.runtime_generation, "runtime_generation")
        _check_token(self.project_id, "project_id")
        for name in ("profile_revision", "assignment_revision"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise SkillIntentError(
                    "SKILL_INTENT_INVALID", f"{name} must be a non-negative int")
