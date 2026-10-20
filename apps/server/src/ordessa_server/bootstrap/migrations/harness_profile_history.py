"""Explicit read-only decoder of historical harness-profile envelope bytes.

No runtime provider, file writer, default discovery or modern Profile authority.
Historical digest encoding is the original envelope algorithm, not modern content.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

PROVIDER_ID = "harness-profile"
CONTRACT_ID = "agent-box.profile@1"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
MAX_CAPTURE_BYTES = 262144


def _digest(payload):
    body={k:v for k,v in payload.items() if k not in {"digest","revision"}}
    return "sha256:"+hashlib.sha256(json.dumps(body,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class CapturedHarnessProfile:
    harness_type: str
    profile_id: str
    revision: int
    digest: str
    raw_bytes: bytes


def validated_capture(capture: CapturedHarnessProfile) -> dict:
    """Rebuild from immutable captured bytes; caller-created carriers are untrusted."""
    if type(capture) is not CapturedHarnessProfile or type(capture.raw_bytes) is not bytes:
        raise TypeError("historical captured profile bytes required")
    if not _ID.fullmatch(capture.harness_type) or not _ID.fullmatch(capture.profile_id):
        raise ValueError("INVALID_PROFILE_ID")
    if type(capture.revision) is not int or capture.revision < 1:
        raise ValueError("PROFILE_IDENTITY_MISMATCH")
    if len(capture.raw_bytes) > MAX_CAPTURE_BYTES:
        raise ValueError("PROFILE_TOO_LARGE")
    return _decode_historical(capture.raw_bytes.decode("utf-8"), capture.harness_type,
                              capture.profile_id, capture.revision, capture.digest)


def _decode_historical(text, h, p, r, expected_digest=None):
    value = json.loads(text)
    if value.get("digest") != _digest(value): raise ValueError("PROFILE_DIGEST_DRIFT")
    if value.get("harness_type")!=h or value.get("profile_id")!=p or int(value.get("revision",0))!=int(r) or value.get("provider_id")!=PROVIDER_ID: raise ValueError("PROFILE_IDENTITY_MISMATCH")
    if expected_digest is not None and value["digest"] != expected_digest:
        raise ValueError("PROFILE_DIGEST_DRIFT")
    return value



class HarnessProfileHistoryReader:
    """Caller-selected historical root. Construction never creates it."""
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _dir(self,h,p):
        if not _ID.fullmatch(str(h)) or not _ID.fullmatch(str(p)): raise ValueError("INVALID_PROFILE_ID")
        d=(self.root/str(h)/str(p)).resolve()
        if d.parent.parent != self.root: raise ValueError("PROFILE_PATH_ESCAPE")
        return d

    def _historical_path(self, harness_type, profile_id, revision):
        directory = self._dir(harness_type, profile_id)
        revisions = directory / "revisions"
        selected = revisions / str(int(revision))
        target = selected / "envelope.json"
        # A symlink at an ancestor is as capable of escaping the selected root
        # as a symlink at the JSON file. Reject before any source bytes are read.
        if any(part.is_symlink() for part in (revisions, selected, target)):
            raise ValueError("PROFILE_SYMLINK_FORBIDDEN")
        return target

    def _read(self,h,p,r):
        path = self._historical_path(h, p, r)
        try: text=path.read_text(encoding="utf-8")
        except FileNotFoundError: raise KeyError("PROFILE_NOT_FOUND")
        return _decode_historical(text, h, p, r)


    def list(self,harness_type=None):
        if harness_type is not None and (not isinstance(harness_type, str) or not _ID.fullmatch(harness_type)):
            raise ValueError("INVALID_PROFILE_ID")
        roots=[self.root/harness_type] if harness_type else sorted(self.root.iterdir() if self.root.exists() else [],key=lambda x:x.name)
        result=[]
        for hroot in roots:
            if not hroot.is_dir() or hroot.is_symlink(): continue
            for p in sorted(hroot.iterdir(),key=lambda x:x.name):
                if not p.is_dir() or p.is_symlink(): continue
                revisions = p / "revisions"
                if revisions.is_symlink():
                    raise ValueError("PROFILE_SYMLINK_FORBIDDEN")
                revs=sorted(revisions.iterdir(),key=lambda x:int(x.name)) if revisions.is_dir() else []
                if revs: result.append(self._read(hroot.name,p.name,revs[-1].name))
        return tuple(result)

    def get(self,harness_type,profile_id,revision=None):
        if revision is None:
            rows=self.list(harness_type); matches=[x for x in rows if x["profile_id"]==profile_id]
            if not matches: raise KeyError("PROFILE_NOT_FOUND")
            revision=matches[0]["revision"]
        return self._read(harness_type,profile_id,revision)

    def capture(self, harness_type: str, profile_id: str, revision: int, *, expected_digest: str) -> CapturedHarnessProfile:
        path = self._historical_path(harness_type, profile_id, revision)
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_CAPTURE_BYTES + 1)
        except FileNotFoundError:
            raise KeyError("PROFILE_NOT_FOUND") from None
        capture = CapturedHarnessProfile(harness_type, profile_id, revision, expected_digest, raw)
        validated_capture(capture)
        return capture
