"""Content revisions and their explicit approval (T04).

Authoritative text: docs/design/skills-v2/README.md §内容修订与使用修订 and
data-model.md §内容与版本:

* 内容存放、默认分配、会话有效集合是三件事 — installing content never enables
  it; :func:`publish_revision` moves only `latestInstalledRevision`.
* 「安装新版不会自动更新分配；用户批准更新某范围绑定时，该绑定才指向新版」 —
  a revision may only be *referenced by an assignment* once an approval record
  exists for it (:class:`RevisionApprovalStore`), and writing an approval
  record never repoints an existing binding.
* 分配引用版本必须为已经安装、校验并批准的 revision —
  :meth:`RevisionApprovalStore.assert_usable_for_assignment` is that gate.
* 运行实例持有旧 revision 时不清理该目录 — :class:`RevisionRetention` refuses
  removal while an injected in-use predicate says a runtime instance still
  references the revision, and likewise while it is pinned or approved.

Durability choice (documented deliberately): approval records are a JSON file
tree under the assets root — `<assets root>/approvals/<assetId>.json` — one
file per asset, written staging + `os.replace` like the catalog snapshot.
Adding an `approval` column to the shared `server_assets` table is **not**
allowed here: that schema belongs to pacthold and needs a migration review
(AGENTS.md rule 5, legacy tasks.md blocker 5 "共享 schema 变更需迁移评审"), so
it is registered as a follow-up instead. `server_assets`/`server_profile_assets`
rows and columns keep their legacy meaning untouched.

No execution, no network: like the rest of the library this module only
copies, digests and records bytes (verification.md G02).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from ..api.errors import SkillAssetError
from ..api.evidence import STORED
from ..api.identity import ASSET_ID, SkillRevisionFacts
from ..formats.agent_skills.validator import validate_skill_directory
from .store import SkillRevisionStore

#: Directory of the approval record tree, under the injected assets root.
APPROVALS_DIRECTORY = "approvals"

#: The default provenance when a caller states no source at all.
LOCAL_SOURCE = "local:import"

_SLUG = ASSET_ID
_GIT_SOURCE = re.compile(r"\Agit:(?P<url>.+)@(?P<commit>[^@]+)\?ref=(?P<ref>.*)\Z")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# -- source provenance -------------------------------------------------------

def local_source(origin: str = "import") -> str:
    """One canonical spelling for locally supplied content."""
    return f"local:{origin}"


def git_source(url: str, *, ref: str, commit: str) -> str:
    """A *fixed* git reference: url + commit, with the ref kept as annotation.

    data-model.md §存储升级: 远端源的 URL/commit 保存作来源. The commit — not
    the mutable ref — is the identity, which is why G04's 「远端 tag 改动影响
    运行」 counter-example cannot happen from a stored ref alone.
    """
    if not url or not commit:
        raise SkillAssetError("SKILL_ASSET_INVALID",
                              "a git source needs its url and commit")
    return f"git:{url}@{commit}?ref={ref or ''}"


def parse_source(source: str | None) -> dict[str, Any]:
    """The typed provenance view of one stored source string."""
    text = source or LOCAL_SOURCE
    match = _GIT_SOURCE.match(text)
    if match is not None:
        return {"type": "git", "url": match.group("url"),
                "commit": match.group("commit"), "ref": match.group("ref") or None}
    if text.startswith("local:"):
        return {"type": "local", "origin": text[len("local:"):] or None}
    return {"type": "other", "origin": text}


# -- publishing a content revision -------------------------------------------

def publish_revision(*, store: SkillRevisionStore, source: Path | str,
                     asset_id: str, revision: int,
                     records: Any | None = None,
                     directory_name: str | None = None,
                     source_ref: str = LOCAL_SOURCE) -> dict[str, Any]:
    """Install one content revision and register it; nothing else moves.

    This is the whole "install a new version" act: the store gains an
    immutable revision, the catalogue row's `latest_revision` advances, and
    **no binding, assignment or session is repointed** (spec US1/FR07,
    verification.md G04). The returned effect is `stored` and nothing stronger
    (contracts.md 可用性最少区分).
    """
    facts = store.install(source, asset_id=asset_id, revision=revision,
                          directory_name=directory_name, source_ref=source_ref)
    asset: dict[str, Any] | None = None
    if records is not None:
        from .records import asset_view

        published = records.publish(
            kind="skill", name=facts["name"], revision=revision,
            digest=facts["tree_digest"], description=facts["description"],
            source=source_ref, asset_id=asset_id)[1]
        # the same bridge the legacy commit path used: `publish` answers with
        # its snake_case row, `asset_view` reads the wire spelling.
        asset = asset_view({**published, "id": published["asset_id"]})
    return {
        "effect": STORED,
        "facts": facts,
        "asset": asset,
        "latestInstalledRevision": revision,
        "approvalRecord": None,  # installed ≠ approved; see RevisionApprovalStore
    }


def revision_view(store: SkillRevisionStore, *, asset_id: str, revision: int,
                  records: Any | None = None,
                  approvals: "RevisionApprovalStore | None" = None
                  ) -> dict[str, Any]:
    """One stored revision's facts, extended with its approval and lineage.

    The camelCase keys of :class:`SkillRevisionFacts` are kept verbatim (that
    shape is fidelity-pinned by tests/test_g01_legacy_fidelity.py and owned by
    `api/`); the two v2 fields ride alongside them:

    * `approvalRecord` — the approval fact, or None while unapproved.
    * `latestInstalledRevision` — the newest *installed* revision, which a
      binding is never moved to by itself.
    """
    directory = store.revision_dir(asset_id, revision)
    if not directory.is_dir():
        raise SkillAssetError("SKILL_ASSET_MISSING", "the skill revision is not installed")
    validated = validate_skill_directory(directory)
    row: dict[str, Any] = {}
    if records is not None:
        try:
            row = dict(records.get(asset_id))
        except SkillAssetError:
            row = {}
    facts = SkillRevisionFacts(
        asset_id=asset_id, revision=revision,
        tree_digest=store.revision_digest(asset_id=asset_id, revision=revision),
        name=validated.facts.name, description=validated.facts.description,
        metadata=dict(validated.facts.metadata),
        retained_fields=dict(validated.facts.retained),
        file_count=len(validated.entries), total_bytes=validated.total_bytes,
        scripts=tuple(validated.scripts),
        source=str(row.get("source") or LOCAL_SOURCE))
    view = dict(facts.public_dict())
    approval = (approvals.approval_for(asset_id, revision)
                if approvals is not None else None)
    view["approvalRecord"] = approval
    view["latestInstalledRevision"] = (
        int(row["latest_revision"]) if row.get("latest_revision") is not None
        else max((item["revision"] for item in store.list_revisions(asset_id)),
                 default=revision))
    view["provenance"] = parse_source(facts.source)
    return view


# -- approval records --------------------------------------------------------

class RevisionApprovalStore:
    """Durable approval records: a revision is usable by assignments only here.

    Storage: `<assets root>/approvals/<assetId>.json`, one JSON document per
    asset, replaced atomically (staging + `os.replace`). Chosen so this slice
    adds no shared-schema column; the file tree is content-addressed-adjacent
    and readable without the database.
    """

    def __init__(self, root: Path | str, *,
                 store: SkillRevisionStore | None = None) -> None:
        self.root = Path(root)
        self.store = store if store is not None else SkillRevisionStore(self.root)

    def approval_file(self, asset_id: str) -> Path:
        if _SLUG.fullmatch(asset_id) is None:
            raise SkillAssetError("SKILL_ASSET_INVALID",
                                  "asset_id must be a lowercase slug", detail=asset_id)
        directory = self.root / APPROVALS_DIRECTORY
        target = (directory / f"{asset_id}.json").resolve()
        if not target.is_relative_to(directory.resolve()):
            raise SkillAssetError("SKILL_ASSET_INVALID",
                                  "the approval file escapes its tree", detail=asset_id)
        return target

    def approvals(self, asset_id: str) -> list[dict[str, Any]]:
        """Every approval record of one asset, oldest revision first."""
        path = self.approval_file(asset_id)
        if not path.is_file():
            return []
        document = json.loads(path.read_text(encoding="utf-8"))
        records = document.get("approvals") if isinstance(document, dict) else None
        return sorted((list(records or [])), key=lambda item: int(item["revision"]))

    def approval_for(self, asset_id: str, revision: int) -> dict[str, Any] | None:
        for record in self.approvals(asset_id):
            if int(record["revision"]) == int(revision):
                return record
        return None

    def is_approved(self, asset_id: str, revision: int) -> bool:
        return self.approval_for(asset_id, revision) is not None

    def latest_approved(self, asset_id: str) -> dict[str, Any] | None:
        approved = self.approvals(asset_id)
        return approved[-1] if approved else None

    def approve(self, *, asset_id: str, revision: int,
                approved_by: str = "user", source: str | None = None,
                expected_digest: str | None = None) -> dict[str, Any]:
        """Approve one installed, digest-verified revision for use.

        An approval is additive: it never moves a binding, an assignment or a
        session (README.md §内容修订与使用修订), and re-approving the same
        revision is idempotent — the original record stands.
        """
        if not isinstance(revision, int) or revision < 1:
            raise SkillAssetError("SKILL_ASSET_INVALID", "revision must be >= 1")
        existing = self.approval_for(asset_id, revision)
        if existing is not None:
            return existing
        digest = self.store.revision_digest(asset_id=asset_id, revision=revision)
        if expected_digest is not None and expected_digest != digest:
            raise SkillAssetError(
                "SKILL_APPROVAL_DIGEST_MISMATCH",
                "the installed tree no longer matches what was reviewed",
                detail=f"expected {expected_digest} got {digest}")
        record = {
            "assetId": asset_id,
            "revision": revision,
            "treeDigest": digest,
            "approvedAt": now(),
            "approvedBy": approved_by,
            "source": source or LOCAL_SOURCE,
            "provenance": parse_source(source),
        }
        self._write(asset_id, self.approvals(asset_id) + [record])
        return record

    def assert_usable_for_assignment(self, asset_id: str,
                                     revision: int) -> dict[str, Any]:
        """Gate for assignment writes (data-model.md: 已安装、校验并批准).

        Not an error to *see* an unapproved revision — the catalogue lists it —
        but a `enable(revision)` that names it is a typed refusal
        (verification.md G06 「启用未批准版」).
        """
        directory = self.store.revision_dir(asset_id, revision)
        if not directory.is_dir():
            raise SkillAssetError("SKILL_ASSET_MISSING", "the skill revision is not installed")
        record = self.approval_for(asset_id, revision)
        if record is None:
            raise SkillAssetError(
                "SKILL_APPROVAL_MISSING",
                f"revision {revision} of {asset_id} is not approved for use",
                detail=asset_id)
        if record["treeDigest"] != self.store.revision_digest(
                asset_id=asset_id, revision=revision):
            raise SkillAssetError(
                "SKILL_APPROVAL_DIGEST_MISMATCH",
                "the approved tree no longer matches what is installed",
                detail=asset_id)
        return record

    def _write(self, asset_id: str, records: Iterable[dict[str, Any]]) -> None:
        path = self.approval_file(asset_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps({"assetId": asset_id,
                           "approvals": sorted(records,
                                               key=lambda item: int(item["revision"]))},
                          sort_keys=True, indent=1).encode("utf-8")
        staging = tempfile.NamedTemporaryFile(
            dir=str(path.parent), prefix=f".{asset_id}-", suffix=".tmp", delete=False)
        try:
            with staging as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(staging.name, path)
        except BaseException:
            try:
                os.unlink(staging.name)
            except OSError:
                pass
            raise


# -- retention / premature GC -----------------------------------------------

#: A runtime reference: does a live session/instance still use this revision?
#: Supplied by the Harness side; the library never inspects a running session.
InUsePredicate = Callable[[str, int], bool]
#: Revisions of one asset still pinned by a binding or a frozen snapshot.
PinnedProvider = Callable[[str], Iterable[int]]


class RevisionRetention:
    """Who may delete a revision directory, and who must refuse (G04).

    verification.md G04 counter-example 「旧版提早 GC」 and data-model.md
    §存储升级: 实体不因取消分配、卸载前端或归档 Profile 而删除；运行实例持有旧
    revision 时不清理该目录. Every reference check is an *injected* predicate —
    the runtime reference belongs to Harness, the pins belong to the records
    layer — so this module stays free of host imports (AGENTS.md rule 3).
    """

    def __init__(self, *, store: SkillRevisionStore,
                 approvals: RevisionApprovalStore | None = None,
                 in_use: InUsePredicate | None = None,
                 pinned: PinnedProvider | None = None) -> None:
        self.store = store
        self.approvals = approvals
        self._in_use = in_use
        self._pinned = pinned

    def in_use(self, asset_id: str, revision: int) -> bool:
        return bool(self._in_use(asset_id, revision)) if self._in_use else False

    def pinned(self, asset_id: str, revision: int) -> bool:
        if self._pinned is None:
            return False
        return int(revision) in {int(item) for item in self._pinned(asset_id)}

    def refusal_reason(self, asset_id: str, revision: int) -> str | None:
        if self.in_use(asset_id, revision):
            return "in-use"
        if self.pinned(asset_id, revision):
            return "pinned"
        if self.approvals is not None and self.approvals.is_approved(asset_id, revision):
            return "approved"
        return None

    def removable(self, asset_id: str, revision: int) -> bool:
        return self.refusal_reason(asset_id, revision) is None

    def remove(self, asset_id: str, revision: int) -> Mapping[str, Any]:
        """Delete one revision directory — only when nothing references it."""
        reason = self.refusal_reason(asset_id, revision)
        if reason is not None:
            raise SkillAssetError(
                {"in-use": "SKILL_IN_USE", "pinned": "SKILL_PINNED",
                 "approved": "SKILL_APPROVED"}[reason],
                f"revision {revision} of {asset_id} is still {reason}",
                detail=f"{asset_id}/{revision}")
        directory = self.store.revision_dir(asset_id, revision)
        if not directory.is_dir():
            raise SkillAssetError("SKILL_ASSET_MISSING", "the skill revision is not installed")
        shutil.rmtree(directory)
        return {"assetId": asset_id, "revision": revision, "removed": True}
