"""Controlled structured/content materialization into an instance-private generation.

Only complete, immutable generation directories are published. TOML/YAML
date/time values are refused because the intent DTO carries JSON-shaped
values and a rewrite cannot safely preserve their native type. This is a
startup/restart input, never a hot multi-file update to a running process.
Native defaults, secrets and actions are intentionally refused.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
from typing import Mapping
from uuid import uuid4

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 runtime
    import tomli as tomllib
import tomli_w
import yaml

from .intent_merge import AuthorizedIntents, MergeAuthority, MergedIntent, merge_intents

MAX_FILES = 256
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
_NAME = re.compile(r"gen-[0-9a-f]{32}\Z")


class MaterializationError(ValueError):
    """Preflight or private publication refused."""


@dataclass
class PublishedGeneration:
    """Lease on the verified directory inode; never resolve the name as a path.

    The caller owns ``directory_fd`` and must close the lease. A process that
    needs this generation must inherit/use this fd, not reopen a path that a
    same-UID actor can replace after publication.
    """

    generation_name: str
    files: tuple[tuple[tuple[str, ...], str], ...]  # resource, sha256
    directory_fd: int

    def fileno(self) -> int:
        if self.directory_fd < 0:
            raise MaterializationError("generation lease is closed")
        return self.directory_fd

    def read_bytes(self, parts: tuple[str, ...]) -> bytes:
        parts = _path_key(parts)
        expected = dict(self.files).get(parts)
        if expected is None:
            raise MaterializationError("file is not in the published generation manifest")
        parentfd = os.dup(self.fileno())
        try:
            for part in parts[:-1]:
                childfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parentfd)
                os.close(parentfd)
                parentfd = childfd
            filefd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parentfd)
            try:
                with os.fdopen(filefd, "rb", closefd=False) as stream:
                    data = stream.read(MAX_FILE_BYTES + 1)
            finally:
                os.close(filefd)
            if len(data) > MAX_FILE_BYTES or hashlib.sha256(data).hexdigest() != expected:
                raise MaterializationError("published generation bytes changed")
            return data
        finally:
            os.close(parentfd)

    def close(self) -> None:
        if self.directory_fd >= 0:
            os.close(self.directory_fd)
            self.directory_fd = -1

    def __enter__(self) -> PublishedGeneration:
        return self

    def __exit__(self, *unused: object) -> None:
        self.close()


def _path_key(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not value or any(
        not isinstance(part, str) or not part or part in {".", ".."} or "/" in part or "\\" in part
        for part in value
    ):
        raise MaterializationError("invalid private resource path")
    return value


class _UniqueSafeLoader(yaml.SafeLoader):
    # PyYAML defaults to YAML 1.1: unquoted `on`, `off`, `yes`, `no` become
    # booleans, and `012` becomes octal. A rewrite must preserve the native
    # YAML 1.2 meaning of untouched scalars. Use a conservative 1.2 subset;
    # ambiguous numeric spellings remain strings instead of being guessed.
    yaml_implicit_resolvers = {
        first: [(tag, resolver) for tag, resolver in entries if tag not in {
            "tag:yaml.org,2002:bool", "tag:yaml.org,2002:int", "tag:yaml.org,2002:float"}]
        for first, entries in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise MaterializationError("YAML aliases are not supported")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in mapping:
                raise MaterializationError("YAML mapping keys must be unique strings")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


_UniqueSafeLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$", re.IGNORECASE), list("tTfF"))
_UniqueSafeLoader.add_implicit_resolver(
    "tag:yaml.org,2002:int",
    re.compile(r"^[+-]?(?:0|[1-9][0-9]*|0o[0-7]+|0x[0-9a-fA-F]+)$"),
    list("+-0123456789"))
_UniqueSafeLoader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(r"^[+-]?(?:(?:0|[1-9][0-9]*)\.[0-9]*(?:[eE][+-]?[0-9]+)?|"
               r"\.[0-9]+(?:[eE][+-]?[0-9]+)?|"
               r"(?:0|[1-9][0-9]*)[eE][+-]?[0-9]+|\.inf|\.nan)$", re.IGNORECASE),
    list("+-.0123456789"))


def _json_shape(value: object, seen: set[int], depth: int = 0) -> None:
    if depth > 64:
        raise MaterializationError("structured document is too deep")
    if value is None or type(value) in {bool, int, str}:
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, (dict, list)):
        identity = id(value)
        if identity in seen:
            raise MaterializationError("structured document contains an alias cycle")
        seen.add(identity)
        try:
            if isinstance(value, dict):
                if any(not isinstance(key, str) for key in value):
                    raise MaterializationError("structured document needs string keys")
                for child in value.values():
                    _json_shape(child, seen, depth + 1)
            else:
                for child in value:
                    _json_shape(child, seen, depth + 1)
        finally:
            seen.remove(identity)
        return
    raise MaterializationError("structured document contains unsupported value")


def _document(codec: str, data: bytes) -> dict:
    try:
        text = data.decode("utf-8")
        if codec == "json":
            value = json.loads(text)
        elif codec == "toml":
            value = tomllib.loads(text)
        elif codec == "yaml":
            value = yaml.load(text, Loader=_UniqueSafeLoader)
        else:
            raise MaterializationError("unsupported structured codec")
    except (UnicodeError, ValueError, yaml.YAMLError) as exc:
        raise MaterializationError(f"invalid {codec.upper()} snapshot") from exc
    if not isinstance(value, dict):
        raise MaterializationError("structured target must be an object")
    _json_shape(value, set())
    return value


def _encode_document(codec: str, value: dict) -> bytes:
    _json_shape(value, set())
    try:
        if codec == "json":
            text = json.dumps(value, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False, allow_nan=False)
        elif codec == "toml":
            text = tomli_w.dumps(value)
        elif codec == "yaml":
            text = yaml.safe_dump(value, sort_keys=True, allow_unicode=True)
        else:
            raise MaterializationError("unsupported structured codec")
    except (TypeError, ValueError, yaml.YAMLError) as exc:
        raise MaterializationError(f"value cannot be represented as {codec.upper()}") from exc
    return (text.rstrip("\n") + "\n").encode("utf-8")


def _field_parent(value: dict, field: tuple[str, ...], *, create: bool) -> dict | None:
    cursor = value
    for segment in field[:-1]:
        if segment not in cursor:
            if not create:
                return None
            child = {}
            cursor[segment] = child
        else:
            child = cursor[segment]
        if not isinstance(child, dict):
            raise MaterializationError("field parent is not an object")
        cursor = child
    return cursor


def _preflight(authority: MergeAuthority, intents: tuple[MergedIntent, ...],
               snapshot: Mapping[tuple[str, ...], bytes],
               content: Mapping[str, bytes]) -> dict[tuple[str, ...], bytes]:
    targets = {item.descriptor.handle.handle_id: item for item in authority.targets}
    owned = {(item.target.handle_id, item.resource, item.relative_name): item.owner
             for item in authority.owned_content}
    files: dict[tuple[str, ...], bytes] = {}
    allowed_files = {item.resource: item.descriptor.codec for item in authority.targets if item.descriptor.kind == "file"}
    allowed_dirs = {item.resource for item in authority.targets if item.descriptor.kind == "directory"}
    for key, value in snapshot.items():
        key = _path_key(key)
        if key not in allowed_files and not any(key[:len(root)] == root and len(key) > len(root) for root in allowed_dirs):
            raise MaterializationError("snapshot resource outside target authority")
        if not isinstance(value, bytes) or len(value) > MAX_FILE_BYTES:
            raise MaterializationError("invalid snapshot bytes or size")
        if key in allowed_files:
            if allowed_files[key] not in {"json", "toml", "yaml"}:
                raise MaterializationError("unsupported structured codec")
            _document(allowed_files[key], value)
        files[key] = value
    for entry in intents:
        if entry.kind in {"bind-secret", "invoke-action"}:
            raise MaterializationError("secret or action requires separate controlled executor")
        target = targets.get(entry.target_id)
        if target is None or target.descriptor.handle.generation != entry.generation or target.resource != entry.resource:
            raise MaterializationError("stale materialization target")
        resource = entry.resource
        if entry.kind in {"set-field", "reset-field"}:
            codec = target.descriptor.codec
            if target.descriptor.kind != "file" or codec not in {"json", "toml", "yaml"}:
                raise MaterializationError("unsupported structured codec")
            document = _document(codec, files.get(resource, b"" if codec == "toml" else b"{}"))
            parent = _field_parent(document, entry.field, create=entry.kind == "set-field")
            if entry.kind == "set-field":
                assert parent is not None
                parent[entry.field[-1]] = json.loads(entry.detail)
            elif entry.detail == "remove-key":
                if parent is not None:
                    parent.pop(entry.field[-1], None)
            else:
                raise MaterializationError("unsupported reset baseline rule")
            files[resource] = _encode_document(codec, document)
        elif entry.kind == "mount-content":
            if target.descriptor.kind != "directory" or target.descriptor.codec != "content":
                raise MaterializationError("content needs directory target")
            ref, digest, size, mode = json.loads(entry.detail)
            if mode != "read-only" or not isinstance(ref, str) or not isinstance(digest, str) or type(size) is not int:
                raise MaterializationError("unsupported content mode or reference")
            data = content.get(ref)
            if not isinstance(data, bytes) or len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                raise MaterializationError("content reference absent or digest mismatch")
            key = _path_key(resource + entry.field)
            if key in files and owned.get((entry.target_id, resource, "/".join(entry.field))) != entry.owner:
                raise MaterializationError("replace requires matching content ownership snapshot")
            files[key] = data
        elif entry.kind == "remove-owned-content":
            if target.descriptor.kind != "directory" or target.descriptor.codec != "content":
                raise MaterializationError("content needs directory target")
            name = "/".join(entry.field)
            if owned.get((entry.target_id, resource, name)) != entry.owner:
                raise MaterializationError("remove lacks ownership snapshot")
            key = _path_key(resource + entry.field)
            if key not in files:
                raise MaterializationError("owned content is absent from snapshot")
            del files[key]
        else:
            raise MaterializationError("unsupported intent kind")
    if len(files) > MAX_FILES or sum(len(data) for data in files.values()) > MAX_TOTAL_BYTES or any(len(data) > MAX_FILE_BYTES for data in files.values()):
        raise MaterializationError("private generation capacity exceeded")
    paths = sorted(files)
    if any(other[:len(path)] == path for index, path in enumerate(paths) for other in paths[index + 1:]):
        raise MaterializationError("file and directory resource overlap")
    return files


def _open_root(path: Path) -> int:
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise MaterializationError("private generation requires POSIX no-follow directory handles")
    if not path.is_absolute() or ".." in path.parts:
        raise MaterializationError("private root must be absolute and normalized")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for part in path.parts[1:]:
            following = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = following
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
            raise MaterializationError("private root must be owned and not group/world writable")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _same_root(path: Path, fd: int) -> bool:
    try:
        check = _open_root(path)
    except OSError:
        return False
    try:
        a, b = os.fstat(fd), os.fstat(check)
        return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)
    finally:
        os.close(check)


def _write_candidate(rootfd: int, candidate: str, files: Mapping[tuple[str, ...], bytes]) -> int:
    os.mkdir(candidate, 0o700, dir_fd=rootfd)
    os.fsync(rootfd)
    basefd = os.open(candidate, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=rootfd)
    try:
        for parts, data in sorted(files.items()):
            parentfd = os.dup(basefd)
            try:
                for part in parts[:-1]:
                    try:
                        os.mkdir(part, 0o700, dir_fd=parentfd)
                        os.fsync(parentfd)
                    except FileExistsError:
                        pass
                    childfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parentfd)
                    os.close(parentfd)
                    parentfd = childfd
                filefd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parentfd)
                try:
                    with os.fdopen(filefd, "wb", closefd=False) as stream:
                        stream.write(data)
                        stream.flush()
                    os.fsync(filefd)
                finally:
                    os.close(filefd)
                os.fsync(parentfd)
            finally:
                os.close(parentfd)
        os.fsync(basefd)
        return basefd  # caller holds inode identity until publish/readback
    except BaseException:
        os.close(basefd)
        raise


def _same_candidate(rootfd: int, name: str, candidatefd: int) -> bool:
    try:
        check = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=rootfd)
    except OSError:
        return False
    try:
        a, b = os.fstat(candidatefd), os.fstat(check)
        return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)
    finally:
        os.close(check)


def _verify_files(candidatefd: int, files: Mapping[tuple[str, ...], bytes]) -> None:
    observed: set[tuple[str, ...]] = set()
    for current, dirs, names, currentfd in os.fwalk(".", dir_fd=candidatefd, follow_symlinks=False):
        prefix = tuple(part for part in current.split(os.sep) if part not in {"", "."})
        for name in dirs:
            if not stat.S_ISDIR(os.stat(name, dir_fd=currentfd, follow_symlinks=False).st_mode):
                raise MaterializationError("candidate contains unsafe directory entry")
        for name in names:
            info = os.stat(name, dir_fd=currentfd, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                raise MaterializationError("candidate contains unsafe file entry")
            observed.add(prefix + (name,))
    if observed != set(files):
        raise MaterializationError("candidate file set changed before publication")
    for parts, expected in files.items():
        parentfd = os.dup(candidatefd)
        try:
            for part in parts[:-1]:
                nextfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parentfd)
                os.close(parentfd)
                parentfd = nextfd
            filefd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parentfd)
            try:
                with os.fdopen(filefd, "rb", closefd=False) as stream:
                    actual = stream.read(MAX_FILE_BYTES + 1)
            finally:
                os.close(filefd)
            if actual != expected:
                raise MaterializationError("candidate bytes changed before publication")
        finally:
            os.close(parentfd)


def _remove_our_entry(rootfd: int, name: str, candidatefd: int | None) -> None:
    try:
        info = os.stat(name, dir_fd=rootfd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if stat.S_ISDIR(info.st_mode):
        held = os.fstat(candidatefd) if candidatefd is not None else None
        if held is not None and (info.st_dev, info.st_ino) != (held.st_dev, held.st_ino):
            # Never recursively delete a replacement tree. Remove it from
            # the generation namespace and leave forensic bytes untouched.
            os.rename(name, f".rejected-{uuid4().hex}", src_dir_fd=rootfd, dst_dir_fd=rootfd)
        else:
            shutil.rmtree(name, dir_fd=rootfd)
    else:
        os.unlink(name, dir_fd=rootfd)


def preflight_generation(root: Path, authority: MergeAuthority,
                         submissions: tuple[AuthorizedIntents, ...], *,
                         snapshot: Mapping[tuple[str, ...], bytes],
                         content: Mapping[str, bytes] | None = None) -> None:
    """Validate deterministic inputs and the current private root without publishing.

    Publication repeats these checks after the operation is durably reserved;
    a concurrent change after this read-only preflight remains uncertain.
    """
    plan = merge_intents(authority, submissions)
    _preflight(authority, plan.intents, snapshot, content if content is not None else {})
    try:
        rootfd = _open_root(Path(root))
    except OSError as exc:
        raise MaterializationError("private root absent, symlinked or unsafe") from exc
    else:
        os.close(rootfd)


def materialize_generation(root: Path, authority: MergeAuthority,
                           submissions: tuple[AuthorizedIntents, ...], *,
                           snapshot: Mapping[tuple[str, ...], bytes],
                           content: Mapping[str, bytes] | None = None) -> PublishedGeneration:
    """Preflight all bytes, then publish one private generation directory.

    Callers may start a *new* instance through the returned directory lease
    only after success. The generation name is diagnostic, not a safe path.
    No running instance is switched here; there is no hot apply.
    """
    plan = merge_intents(authority, submissions)
    files = _preflight(authority, plan.intents, snapshot, content if content is not None else {})
    root = Path(root)
    try:
        rootfd = _open_root(root)
    except OSError as exc:
        raise MaterializationError("private root absent, symlinked or unsafe") from exc
    name = f"gen-{uuid4().hex}"
    candidate = f".candidate-{uuid4().hex}"
    published = False
    candidatefd: int | None = None
    try:
        candidatefd = _write_candidate(rootfd, candidate, files)
        if not _same_candidate(rootfd, candidate, candidatefd):
            raise MaterializationError("candidate replaced before publication")
        if not _same_root(root, rootfd):
            raise MaterializationError("private root replaced during publication")
        if not _NAME.fullmatch(name):
            raise MaterializationError("invalid generation name")
        os.rename(candidate, name, src_dir_fd=rootfd, dst_dir_fd=rootfd)
        published = True
        os.fsync(rootfd)
        if not _same_candidate(rootfd, name, candidatefd):
            raise MaterializationError("candidate replaced during publication")
        _verify_files(candidatefd, files)
        if not _same_candidate(rootfd, name, candidatefd):
            raise MaterializationError("candidate replaced after readback")
        if not _same_root(root, rootfd):
            raise MaterializationError("private root replaced during publication")
        return PublishedGeneration(name, tuple(
            (parts, hashlib.sha256(data).hexdigest()) for parts, data in sorted(files.items())),
            os.dup(candidatefd))
    except BaseException:
        _remove_our_entry(rootfd, name if published else candidate, candidatefd)
        raise
    finally:
        if candidatefd is not None:
            os.close(candidatefd)
        os.close(rootfd)
