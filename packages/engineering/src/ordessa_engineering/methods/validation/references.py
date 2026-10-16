"""Path and reference checks shared by loading and validation."""
from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath
from urllib.parse import urldefrag, unquote, urljoin

from ..definitions.errors import MethodError, MethodFailure


def validate_logical_path(raw: str) -> str:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise MethodFailure(MethodError("RESOURCE_PATH_INVALID", "resource path is empty or contains NUL"))
    if "\\" in raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw) or "://" in raw:
        raise MethodFailure(MethodError("RESOURCE_PATH_INVALID", "resource path must be relative POSIX path", path=raw))
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in raw.split("/")):
        raise MethodFailure(MethodError("RESOURCE_ESCAPE", "resource path escapes the method root", path=raw))
    if unicodedata.normalize("NFC", raw) != raw:
        # Canonical paths prevent visually equivalent identities and make the
        # collision check stable across filesystems.
        raise MethodFailure(MethodError("RESOURCE_PATH_NOT_NORMALIZED", "resource path must use NFC Unicode", path=raw))
    return raw


def validate_resource_references(value: object, known: dict[str, dict], *, path: str) -> list[MethodError]:
    errors: list[MethodError] = []

    def walk(item: object, pointer: str) -> None:
        if isinstance(item, dict):
            resource_id = item.get("resource")
            if isinstance(resource_id, str):
                declaration = known.get(resource_id)
                if declaration is None:
                    errors.append(MethodError("UNKNOWN_RESOURCE", f"unknown resource reference: {resource_id}", path=path, pointer=pointer))
                elif "sha256" in item and item["sha256"] != declaration.get("sha256"):
                    errors.append(MethodError("RESOURCE_REFERENCE_DIGEST_MISMATCH", "resource reference digest does not match its declaration", resource_id=resource_id, path=path, pointer=pointer))
            resource_id = item.get("resource_id")
            if isinstance(resource_id, str) and resource_id not in known:
                errors.append(MethodError("UNKNOWN_RESOURCE", f"unknown resource reference: {resource_id}", path=path, pointer=pointer))
            for key, child in item.items():
                escaped = str(key).replace("~", "~0").replace("/", "~1")
                walk(child, f"{pointer}/{escaped}")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{pointer}/{index}")

    walk(value, "")
    return errors


def validate_schema_refs(schema: object, *, resource_id: str, path: str,
                         schemas: dict[str, tuple[str, object]] | None = None) -> list[MethodError]:
    """Resolve bundled JSON Schema references without retrieval.

    ``schemas`` maps another bundle resource ID to its logical path and parsed
    schema. References may resolve within this document or to another supplied
    schema resource. No URI is fetched; an unresolved URI is always rejected.
    Nested ``$id`` values establish nested resources, and both anchors and
    JSON Pointer fragments are checked before validation proceeds.
    """
    errors: list[MethodError] = []
    supplied = schemas or {}
    # A private, deterministic URI namespace gives relative refs meaningful
    # semantics while preventing accidental resolution through the network.
    roots: dict[str, object] = {}
    anchors: dict[tuple[str, str], object] = {}
    identifiers: dict[int, str] = {}
    locations = {resource_id: (path, schema), **supplied}

    def register_tree(item: object, inherited_base: str, owner_id: str,
                      owner_path: str, pointer: str = "", *, root: bool = False) -> None:
        if isinstance(item, dict):
            base = inherited_base
            identifier = item.get("$id")
            if isinstance(identifier, str):
                absolute = urljoin(inherited_base, identifier)
                absolute, fragment = urldefrag(absolute)
                if fragment:
                    return
                base = absolute
                previous = roots.get(base)
                if previous is not None and previous is not item:
                    errors.append(MethodError(
                        "SCHEMA_ID_DUPLICATE", "schema resource identifier is duplicated",
                        resource_id=owner_id, path=owner_path,
                        pointer=f"{pointer}/$id",
                    ))
                    return
                roots[base] = item
                identifiers[id(item)] = base
            if root:
                roots[inherited_base] = item
                base = identifiers.get(id(item), inherited_base)
            for key_name in ("$anchor", "$dynamicAnchor"):
                anchor = item.get(key_name)
                if isinstance(anchor, str):
                    anchors[(base, anchor)] = item
            for key, child in item.items():
                if isinstance(child, (dict, list)):
                    escaped = str(key).replace("~", "~0").replace("/", "~1")
                    register_tree(child, base, owner_id, owner_path, f"{pointer}/{escaped}")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                register_tree(child, inherited_base, owner_id, owner_path, f"{pointer}/{index}")

    bases: dict[str, str] = {}
    for schema_id, (schema_path, schema_value) in locations.items():
        location = "https://ordessa.invalid/method/" + schema_path
        # Root $id takes precedence as the JSON Schema base; retain the bundle
        # location as an alias so a sibling can explicitly reference it.
        roots[location] = schema_value
        declared_id = schema_value.get("$id") if isinstance(schema_value, dict) else None
        base = urljoin(location, declared_id) if isinstance(declared_id, str) else location
        base, fragment = urldefrag(base)
        if fragment:
            errors.append(MethodError("SCHEMA_ID_INVALID", "schema $id must not contain a fragment", resource_id=schema_id, path=schema_path, pointer="/$id"))
            base = location
        previous = roots.get(base)
        if previous is not None and previous is not schema_value:
            errors.append(MethodError(
                "SCHEMA_ID_DUPLICATE", "schema resource identifier is duplicated",
                resource_id=schema_id, path=schema_path, pointer="/$id",
            ))
        else:
            roots[base] = schema_value
        bases[schema_id] = base
        # Walk from the bundle location so a relative root $id is resolved
        # exactly once, as required by URI-reference semantics.
        register_tree(schema_value, location, schema_id, schema_path, root=True)

    def pointer_target(root_value: object, fragment: str) -> object | None:
        if fragment == "":
            return root_value
        if not fragment.startswith("/"):
            return None
        current = root_value
        # URI-fragment decoding already occurred in resolves. A second pass
        # would turn a literal percent sequence into a different pointer.
        for raw_token in fragment[1:].split("/"):
            if re.search(r"~(?:[^01]|$)", raw_token):
                return None
            token = raw_token.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict) and token in current:
                current = current[token]
            elif (isinstance(current, list) and re.fullmatch(r"0|[1-9][0-9]*", token)
                  and int(token) < len(current)):
                current = current[int(token)]
            else:
                return None
        return current

    def resolves(reference: str, base: str) -> bool:
        # urllib's relative URL joining drops non-hierarchical URN bases for
        # fragment-only references. Fragments keep the resource identity.
        absolute = urldefrag(base)[0] + reference if reference.startswith("#") else (base if reference == "" else urljoin(base, reference))
        document_uri, fragment = urldefrag(absolute)
        root_value = roots.get(document_uri)
        if root_value is None:
            return False
        if not fragment:
            return True
        decoded = unquote(fragment)
        if decoded.startswith("/"):
            return pointer_target(root_value, decoded) is not None
        return (document_uri, decoded) in anchors

    def walk(item: object, pointer: str, base: str, schema_id: str, schema_path: str) -> None:
        if isinstance(item, dict):
            node_base = identifiers.get(id(item), base)
            for ref_key in ("$ref", "$dynamicRef"):
                ref = item.get(ref_key)
                if ref is not None and (not isinstance(ref, str) or not resolves(ref, node_base)):
                    errors.append(MethodError(
                        "REMOTE_SCHEMA_REF",
                        "schema reference is unresolved in the supplied offline bundle",
                        resource_id=schema_id, path=schema_path,
                        pointer=f"{pointer}/{ref_key}",
                    ))
            for key, child in item.items():
                escaped = str(key).replace("~", "~0").replace("/", "~1")
                walk(child, f"{pointer}/{escaped}", node_base, schema_id, schema_path)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{pointer}/{index}", base, schema_id, schema_path)

    for schema_id, (schema_path, schema_value) in locations.items():
        walk(schema_value, "", bases[schema_id], schema_id, schema_path)
    return errors
