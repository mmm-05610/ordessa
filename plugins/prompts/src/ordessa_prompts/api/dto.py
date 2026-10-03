"""Pure DTOs and content rules for the Prompts domain (data-model.md).

Importing this module has no runtime effects: no database, no files, no
registration (G01). The rules here are the single validation truth shared
by backend, Server handlers and tests; the TypeScript DTOs under
``contracts/`` are checked against the same constants by the contract test.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .errors import InvalidContentError

# ---------------------------------------------------------------------------
# Frozen capacity rules (product defaults for the first release)
# ---------------------------------------------------------------------------

KINDS = ("instruction", "persona", "system-replacement")
SCOPES = ("library", "profile")

#: title: 1–160 Unicode characters (no normalisation, no trim)
TITLE_MAX_CODEPOINTS = 160
#: description: at most 2,000 characters
DESCRIPTION_MAX_CODEPOINTS = 2_000
#: one body: at most 128 KiB of final saved bytes
BODY_MAX_BYTES = 128 * 1024
#: at most 32 supplemental instructions in one selection
MAX_INSTRUCTIONS_PER_SELECTION = 32
#: one resolved snapshot: at most 1 MiB of total body bytes
SNAPSHOT_MAX_TOTAL_BODY_BYTES = 1024 * 1024
#: import payload hard bound (a single prompt body; same as BODY_MAX_BYTES)
IMPORT_MAX_BYTES = BODY_MAX_BYTES

#: opaque stable ids: "prompt_" + lowercase slug, matching the plugin-id style
_PROMPT_ID = re.compile(r"prompt_[a-z0-9][a-z0-9._-]{0,63}\Z")
_PROFILE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
#: operation keys are caller-supplied idempotency tokens; bounded, printable
_OPERATION_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


# ---------------------------------------------------------------------------
# Content validation (pure functions; raise InvalidContentError)
# ---------------------------------------------------------------------------

def validate_title(title: object) -> str:
    if not isinstance(title, str):
        raise InvalidContentError("title must be a string")
    if not 1 <= len(title) <= TITLE_MAX_CODEPOINTS:
        raise InvalidContentError(
            f"title must be 1-{TITLE_MAX_CODEPOINTS} characters",
            length=len(title) if isinstance(title, str) else None)
    return title


def validate_description(description: object) -> "Optional[str]":
    if description is None:
        return None
    if not isinstance(description, str):
        raise InvalidContentError("description must be a string")
    if len(description) > DESCRIPTION_MAX_CODEPOINTS:
        raise InvalidContentError(
            f"description exceeds {DESCRIPTION_MAX_CODEPOINTS} characters",
            length=len(description))
    return description


def validate_body_bytes(body: bytes) -> bytes:
    """Check raw saved bytes: valid strict UTF-8, no NUL, not all whitespace.

    No implicit newline/Unicode normalisation/trim is applied (data-model):
    the caller's bytes are the saved bytes.
    """
    if not isinstance(body, bytes):
        raise InvalidContentError("body must be bytes")
    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        # Never echo body fragments into the error (G05): only offsets.
        raise InvalidContentError(
            "body is not valid UTF-8", start=exc.start, end=exc.end) from exc
    if "\x00" in text:
        raise InvalidContentError("body contains NUL characters")
    if text and text[0] == "\ufeff":
        raise InvalidContentError(
            "body carries an unexpected leading BOM after import processing")
    if not text.strip():
        raise InvalidContentError("body is empty or only whitespace")
    if len(body) > BODY_MAX_BYTES:
        raise InvalidContentError(
            f"body exceeds {BODY_MAX_BYTES} bytes", size=len(body))
    return body


def validate_kind(kind: object) -> str:
    if kind not in KINDS:
        # The refusal never echoes the client-supplied value: an unknown kind
        # is arbitrary user text and error text is log-eligible (G05/FR14).
        raise InvalidContentError(
            "unknown prompt kind", allowed=KINDS,
            length=len(str(kind)) if isinstance(kind, str) else None)
    return str(kind)


def validate_prompt_id(prompt_id: object) -> str:
    if not isinstance(prompt_id, str) or not _PROMPT_ID.fullmatch(prompt_id):
        raise InvalidContentError("prompt id is malformed")
    return prompt_id


def validate_operation_key(key: object) -> str:
    if not isinstance(key, str) or not _OPERATION_KEY.fullmatch(key):
        raise InvalidContentError("operationKey is malformed")
    return key


def body_digest(body: bytes) -> str:
    """The content digest stored with every revision: sha256 of saved bytes."""
    return "sha256:" + hashlib.sha256(body).hexdigest()


# ---------------------------------------------------------------------------
# DTOs (data-model.md)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PromptScope:
    """library (public) or profile(profileId) (private to one Profile)."""

    kind: str
    profile_id: "Optional[str]" = None

    def __post_init__(self) -> None:
        if self.kind not in SCOPES:
            # no echo of the client-supplied value (G05)
            raise InvalidContentError("unknown scope kind", allowed=SCOPES)
        if self.kind == "profile":
            if not isinstance(self.profile_id, str) or not _PROFILE_ID.fullmatch(self.profile_id):
                raise InvalidContentError("profile scope needs a well-formed profileId")
        elif self.profile_id is not None:
            raise InvalidContentError("library scope must not carry a profileId")

    @property
    def is_profile_private(self) -> bool:
        return self.kind == "profile"

    def as_wire(self) -> dict:
        out: dict = {"kind": self.kind}
        if self.kind == "profile":
            out["profileId"] = self.profile_id
        return out

    @staticmethod
    def parse(raw: object) -> "PromptScope":
        if isinstance(raw, PromptScope):
            return raw
        if not isinstance(raw, dict) or raw.get("kind") not in SCOPES:
            raise InvalidContentError("scope must be {kind: library|profile[, profileId]}")
        return PromptScope(str(raw["kind"]), raw.get("profileId"))


@dataclass(frozen=True)
class PromptRecord:
    """Metadata head of one content record (kind is immutable)."""

    id: str
    kind: str
    scope: PromptScope
    title: str
    description: "Optional[str]"
    archived: bool
    metadata_version: int
    latest_revision: int
    created_at: str
    updated_at: str

    def as_wire(self, *, include_body: bool = False,
                body: "Optional[bytes]" = None) -> dict:
        """Wire view. Lists never pass include_body (G05/contract §1)."""
        out: dict = {
            "id": self.id,
            "kind": self.kind,
            "scope": self.scope.as_wire(),
            "title": self.title,
            "description": self.description,
            "archived": self.archived,
            "metadataVersion": self.metadata_version,
            "latestRevision": self.latest_revision,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }
        if include_body:
            out["bodyBase64"] = _b64(body or b"")
        return out


@dataclass(frozen=True)
class PromptRevision:
    prompt_id: str
    revision: int
    body: bytes
    sha256: str
    created_at: str

    def as_wire(self, *, include_body: bool = True) -> dict:
        out: dict = {
            "promptId": self.prompt_id,
            "revision": self.revision,
            "sha256": self.sha256,
            "createdAt": self.created_at,
            "byteSize": len(self.body),
        }
        if include_body:
            out["bodyBase64"] = _b64(self.body)
        return out


@dataclass(frozen=True)
class PromptRef:
    """A reference tracking the content's latest revision (first release:
    no user-facing pin option)."""

    prompt_id: str
    track: str = "latest"

    def __post_init__(self) -> None:
        validate_prompt_id(self.prompt_id)
        if self.track != "latest":
            raise InvalidContentError("first release only supports track=latest")

    @staticmethod
    def parse(raw: object) -> "PromptRef":
        if isinstance(raw, PromptRef):
            return raw
        if not isinstance(raw, dict) or "promptId" not in raw:
            raise InvalidContentError("ref must be {promptId[, track]}")
        return PromptRef(str(raw["promptId"]), str(raw.get("track", "latest")))


@dataclass(frozen=True)
class ResolvedPrompt:
    prompt_id: str
    kind: str
    revision: int
    sha256: str
    body: bytes
    title: str = ""

    def as_wire(self) -> dict:
        return {
            "promptId": self.prompt_id,
            "kind": self.kind,
            "revision": self.revision,
            "sha256": self.sha256,
            "title": self.title,
            "byteSize": len(self.body),
            "bodyBase64": _b64(self.body),
        }


@dataclass(frozen=True)
class PromptSelection:
    """A Profile's three items: ordered unique instructions, optional
    persona, optional systemReplacement (each a single item)."""

    instructions: Sequence[PromptRef] = ()
    persona: "Optional[PromptRef]" = None
    system_replacement: "Optional[PromptRef]" = None

    def __post_init__(self) -> None:
        ids = [ref.prompt_id for ref in self.instructions]
        if len(ids) != len(set(ids)):
            raise InvalidContentError("instructions list contains duplicate refs")
        if len(ids) > MAX_INSTRUCTIONS_PER_SELECTION:
            raise InvalidContentError(
                f"at most {MAX_INSTRUCTIONS_PER_SELECTION} instructions per selection",
                count=len(ids))
        for other in (self.persona, self.system_replacement):
            if other is not None and other.prompt_id in ids:
                raise InvalidContentError(
                    "a prompt referenced as persona/replacement must not also be an instruction")
        if (self.persona is not None and self.system_replacement is not None
                and self.persona.prompt_id == self.system_replacement.prompt_id):
            raise InvalidContentError("persona and systemReplacement must be different records")

    @staticmethod
    def parse(raw: object) -> "PromptSelection":
        if isinstance(raw, PromptSelection):
            return raw
        if not isinstance(raw, dict):
            raise InvalidContentError("selection must be an object")
        items = raw.get("instructions", [])
        if not isinstance(items, (list, tuple)):
            raise InvalidContentError("instructions must be a list")
        persona = raw.get("persona")
        replacement = raw.get("systemReplacement")
        return PromptSelection(
            instructions=tuple(PromptRef.parse(item) for item in items),
            persona=None if persona is None else PromptRef.parse(persona),
            system_replacement=(None if replacement is None
                                else PromptRef.parse(replacement)),
        )


@dataclass(frozen=True)
class PromptSnapshot:
    """An immutable resolution of one selection at one instant."""

    snapshot_id: str
    server_scope: str
    resolved: Sequence[ResolvedPrompt]
    instructions_order: "tuple[str, ...]"
    persona_id: "Optional[str]"
    system_replacement_id: "Optional[str]"
    source_metadata_versions: "field(default_factory=dict)"
    content_digest: str = ""
    composition_version: int = 1
    profile_revision: "Optional[int]" = None
    overlay_revision: "Optional[int]" = None

    def total_body_bytes(self) -> int:
        return sum(len(item.body) for item in self.resolved)

    def as_wire(self) -> dict:
        return {
            "snapshotId": self.snapshot_id,
            "serverScope": self.server_scope,
            "compositionVersion": self.composition_version,
            "contentDigest": self.content_digest,
            "profileRevision": self.profile_revision,
            "overlayRevision": self.overlay_revision,
            "totalBodyBytes": self.total_body_bytes(),
            "instructions": list(self.instructions_order),
            "persona": self.persona_id,
            "systemReplacement": self.system_replacement_id,
            "resolved": [item.as_wire() for item in self.resolved],
        }


def _b64(data: bytes) -> str:
    import base64
    return base64.b64encode(data).decode("ascii")
