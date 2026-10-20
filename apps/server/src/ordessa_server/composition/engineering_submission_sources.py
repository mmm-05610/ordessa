"""Fail-closed Engineering submission source binding.

The original Execution owners do not yet expose a synchronized producer for
checkout/file, test-process, and effect facts that is correlated to a Unit and
operation and can retain its source fence through Engineering COMMIT.  The
neutral process spawn and filesystem adapters are primitives only; neither
proves that relationship.  Consequently this composition must refuse normal
Submission sealing until that owner contract exists.

Do not replace this refusal with DTO comparison, a client supplied tree digest,
or an ACP ``completed`` response.  The Engineering ``SubmissionSourcePort``
requires actual provenance plus a live guard held by the caller through its
original UnitOfWork commit.
"""
from __future__ import annotations

import asyncio
from contextlib import AbstractContextManager
from dataclasses import dataclass
import hashlib
import os
from pathlib import PurePosixPath
import re
import stat
from typing import Mapping, Protocol

from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_infrastructure.encoding import canonical_bytes


_MAX_FILES = 4096
_MAX_FILE_BYTES = 8 * 1024 * 1024
_MAX_TOTAL_BYTES = 16 * 1024 * 1024
_MAX_OUTPUT_BYTES = 4 * 1024 * 1024
_MAX_OUTPUT_CHUNK = 65536
_SECRET_ENV = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API|MODEL|CODEX|OPENAI)", re.I)


@dataclass(frozen=True)
class CapturedFile:
    path: str
    before: BlobRef | None
    after: BlobRef | None


@dataclass(frozen=True)
class SubmissionCapture:
    """Immutable captured bytes and actual test-process outcome; never admission."""

    manager_unit_id: str
    environment_id: str
    use_id: str
    execution_operation_ref: str
    prompt_input_digest: str
    execution_observation_ref: BlobRef
    source_query_operation_ref: str
    source_query_input_digest: str
    process_id: str
    tool_version: str
    argv: tuple[str, ...]
    cwd: str
    exit_code: int
    stdout: BlobRef
    stderr: BlobRef
    files: tuple[CapturedFile, ...]
    before_tree_digest: str
    after_tree_digest: str


def _path(value: str) -> str:
    if (not isinstance(value, str) or not value or "\\" in value or "\x00" in value
            or value.startswith("/") or str(PurePosixPath(value)) != value
            or any(part in ("", ".", "..") for part in value.split("/"))):
        raise ApplicationError("SUBMISSION_CAPTURE_PATH_INVALID")
    return value


def _digest(data: bytes) -> Digest:
    return Digest("sha256", hashlib.sha256(data).hexdigest())


def _under(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((os.path.realpath(root), os.path.realpath(path))) == os.path.realpath(root)
    except (OSError, ValueError):
        return False


class EngineeringSubmissionCapture:
    """Capture bounded real files and a real test process through original ports.

    The trusted Server root pins the actual Manager, current live EnvironmentUse,
    same-authority BlobStore and fixed test command when constructing this
    object. Capture uses only public Manager.find, Unit identity properties,
    EnvironmentUse identity/files/execution, ProcessHandle and FileArea APIs.
    The API does not assert isolation or authorize the process; the Environment
    contract explicitly says FileArea is not an authorization boundary.
    """

    def __init__(self, manager, use, source_snapshot, blobs, *, authority_id: str, argv: tuple[str, ...],
                 cwd: str, env: Mapping[str, str], allowed_paths: tuple[str, ...],
                 tool_version: str, timeout: float = 300.0):
        from ordessa_units.management import UnitManager
        from ordessa_environments.management import EnvironmentUse

        if type(manager) is not UnitManager or type(use) is not EnvironmentUse:
            raise ValueError("Original live UnitManager and EnvironmentUse required")
        local_directory = source_snapshot.get("localDirectory") if isinstance(source_snapshot, Mapping) else None
        if (not isinstance(local_directory, Mapping)
                or local_directory.get("environmentIdentity") != use.environment_id
                or local_directory.get("useIdentity") != use.identity
                or local_directory.get("cwdRelativePath") != cwd
                or local_directory.get("isolation") != "none"
                or source_snapshot.get("currentThroughCommit") is not False
                or source_snapshot.get("checkoutBaselineVerified") is not False
                or not isinstance(source_snapshot.get("unitRef"), Mapping)
                or not isinstance(source_snapshot.get("queryOperationRef"), str)
                or not source_snapshot.get("queryOperationRef")
                or not isinstance(source_snapshot.get("queryInputDigest"), str)
                or not source_snapshot.get("queryInputDigest")):
            raise ValueError("Matching original UnitServices live-source observation required")
        if not isinstance(authority_id, str) or not authority_id or getattr(blobs, "authority_id", None) != authority_id:
            raise ValueError("Same-authority original Engineering BlobStore required")
        if not isinstance(argv, tuple) or not argv or any(not isinstance(v, str) or not v for v in argv):
            raise ValueError("Fixed non-empty argv tuple required")
        if not isinstance(env, Mapping) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()):
            raise ValueError("Explicit process environment required; inherited environment is unavailable")
        if any(_SECRET_ENV.search(key) for key in env):
            raise ValueError("Credential/model environment variables are forbidden for capture")
        if not isinstance(tool_version, str) or not tool_version or len(tool_version) > 128:
            raise ValueError("Explicit bounded tool version required")
        if type(timeout) not in (int, float) or timeout <= 0 or timeout > 1800:
            raise ValueError("Capture timeout must be between 0 and 1800 seconds")
        normalized_paths = tuple(_path(value) for value in allowed_paths)
        if (not normalized_paths or len(set(normalized_paths)) != len(normalized_paths)
                or any(a.startswith(b + "/") or b.startswith(a + "/")
                       for i, a in enumerate(normalized_paths) for b in normalized_paths[i + 1:])):
            raise ValueError("Non-overlapping authorized file-area path prefixes required")

        self.manager, self.use, self.source_snapshot, self.blobs = manager, use, source_snapshot, blobs
        self.authority_id, self.argv, self.env = authority_id, argv, dict(env)
        self.cwd, self.allowed_paths = _path(cwd), normalized_paths
        if not any(self.cwd == prefix or self.cwd.startswith(prefix + "/") for prefix in normalized_paths):
            raise ValueError("Test cwd must be inside the captured authorized file-area paths")
        self.tool_version, self.timeout = tool_version, float(timeout)

    def _verify_unit_use(self, unit_ref):
        """Resolve through original Manager and cross-check public identities."""
        from ordessa_infrastructure.encoding.immutable_json import safe_json

        unit = self.manager.find(unit_ref)
        prepared = unit.prepared_unit
        canonical_unit_ref = prepared.get("unitRef") if isinstance(prepared, Mapping) else None
        if (not isinstance(canonical_unit_ref, Mapping)
                or safe_json(canonical_unit_ref) != safe_json(unit_ref)
                or unit.definition.environment_reference.get("environmentId") != self.use.environment_id
                or safe_json(self.source_snapshot.get("unitRef")) != safe_json(unit_ref)):
            raise ApplicationError("SUBMISSION_CAPTURE_UNIT_USE_MISMATCH")
        # The exact Use object is supplied by trusted root composition. Unit's
        # public API exposes Environment identity, but not a public Use identity;
        # this does not claim a stronger cross-owner correlation than exists.
        return unit

    def _snapshot(self):
        # Anchor every component to open directory descriptors. Checking a
        # string then opening it is insufficient against parent-symlink races.
        files = self.use.files
        root = files.root()
        if not isinstance(root,str) or not os.path.isabs(root):
            raise ApplicationError("SUBMISSION_CAPTURE_FILE_AREA_UNAVAILABLE")
        root_fd = None
        selected, total = {}, 0
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        def walk(directory_fd, relative):
            nonlocal total
            with os.scandir(directory_fd) as listing:
                names = sorted(entry.name for entry in listing)
            for name in names:
                path = _path(relative + "/" + name)
                info = os.stat(name,dir_fd=directory_fd,follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    raise ApplicationError("SUBMISSION_CAPTURE_SYMLINK_REFUSED")
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(name,flags,dir_fd=directory_fd)
                    try:walk(child,path)
                    finally:os.close(child)
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise ApplicationError("SUBMISSION_CAPTURE_SPECIAL_FILE_REFUSED")
                if len(selected) >= _MAX_FILES or info.st_size > _MAX_FILE_BYTES:
                    raise ApplicationError("SUBMISSION_CAPTURE_FILE_BOUND_EXCEEDED")
                fd = os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory_fd)
                try:
                    before = os.fstat(fd)
                    if not stat.S_ISREG(before.st_mode):
                        raise ApplicationError("SUBMISSION_CAPTURE_SPECIAL_FILE_REFUSED")
                    chunks, remaining = [], _MAX_FILE_BYTES + 1
                    while remaining:
                        block = os.read(fd,min(65536,remaining))
                        if not block:break
                        chunks.append(block);remaining -= len(block)
                    data = b"".join(chunks);after = os.fstat(fd)
                    if (len(data)>_MAX_FILE_BYTES or before.st_size!=len(data)
                            or (before.st_dev,before.st_ino,before.st_mtime_ns,before.st_size)
                            !=(after.st_dev,after.st_ino,after.st_mtime_ns,after.st_size)):
                        raise ApplicationError("SUBMISSION_CAPTURE_FILE_CHANGED")
                finally:os.close(fd)
                total += len(data)
                if total > _MAX_TOTAL_BYTES:
                    raise ApplicationError("SUBMISSION_CAPTURE_TOTAL_BOUND_EXCEEDED")
                selected[path] = data
        try:
            root_fd = os.open(root,flags)
            for prefix in self.allowed_paths:
                current = os.dup(root_fd)
                try:
                    for part in prefix.split("/"):
                        child = os.open(part,flags,dir_fd=current)
                        os.close(current);current=child
                    walk(current,prefix)
                except FileNotFoundError:
                    pass
                finally:os.close(current)
        except ApplicationError:raise
        except OSError as exc:
            raise ApplicationError("SUBMISSION_CAPTURE_PATH_OR_FILE_CHANGED") from exc
        finally:
            if root_fd is not None:os.close(root_fd)
        return selected

    def _put(self, data: bytes, media_type: str) -> BlobRef:
        if len(data) > 16 * 1024 * 1024:
            raise ApplicationError("SUBMISSION_CAPTURE_BLOB_BOUND_EXCEEDED")
        ref = self.blobs.put_verified(data, _digest(data), media_type)
        if (type(ref) is not BlobRef or ref.byte_length != len(data) or ref.media_type != media_type
                or ref.digest != _digest(data)):
            raise ApplicationError("SUBMISSION_CAPTURE_BLOB_BINDING_INVALID")
        return ref

    def _store_tree(self, snapshot):
        refs = {path: self._put(content, "application/octet-stream") for path, content in snapshot.items()}
        rows = tuple((path, refs[path].digest.hex, len(snapshot[path])) for path in sorted(snapshot))
        return refs, "sha256:" + hashlib.sha256(canonical_bytes(rows)).hexdigest()

    async def capture_test(self, unit_ref, *, operation_ref, prompt_input_digest, query_invocation) -> SubmissionCapture:
        """Take before/after snapshots around the pinned real argv in the Use."""
        from ordessa_environments import ProcessRequest

        unit = self._verify_unit_use(unit_ref)
        from ordessa_engineering.application.usecases.changes.execution_capture import capture_execution_observation
        execution_observation = capture_execution_observation(self.manager.records, self.blobs,
            authority_id=self.authority_id,unit_ref=unit_ref,operation_ref=operation_ref,
            expected_prompt_digest=prompt_input_digest,query_invocation=query_invocation)
        before_bytes = self._snapshot()
        before_refs, before_digest = self._store_tree(before_bytes)
        root = self.use.files.root()
        cwd = self.use.files.path(self.cwd)
        if not _under(cwd, root) or not os.path.isdir(cwd):
            raise ApplicationError("SUBMISSION_CAPTURE_CWD_INVALID")
        cwd_relative = self.cwd
        current = root
        for part in cwd_relative.split("/"):
            current = os.path.join(current, part)
            try:
                if stat.S_ISLNK(os.lstat(current).st_mode):
                    raise ApplicationError("SUBMISSION_CAPTURE_SYMLINK_REFUSED")
            except OSError as exc:
                raise ApplicationError("SUBMISSION_CAPTURE_CWD_INVALID") from exc
        # Use only the caller-supplied fixed environment. Never inherit os.environ.
        process_env = dict(self.env)
        for key in ("HOME", "TMPDIR", "TEMP", "TMP"):
            value = process_env.get(key)
            if value is not None and (not os.path.isabs(value) or not _under(value, root)):
                raise ApplicationError("SUBMISSION_CAPTURE_PROCESS_ENV_PATH_INVALID")
        if "PWD" in process_env and os.path.normpath(process_env["PWD"]) != os.path.normpath(cwd):
            raise ApplicationError("SUBMISSION_CAPTURE_PROCESS_ENV_PWD_INVALID")
        request = ProcessRequest.build(self.argv, cwd=cwd, env=process_env)
        process = self.use.execution.start(request)
        stdout = bytearray()
        stderr = bytearray()
        overflow = False

        async def drain(read, target):
            nonlocal overflow
            while True:
                block = await read(_MAX_OUTPUT_CHUNK, timeout=self.timeout)
                if type(block) is not bytes:
                    raise ApplicationError("SUBMISSION_CAPTURE_PROCESS_OUTPUT_INVALID")
                if not block:
                    return
                if len(target) + len(block) > _MAX_OUTPUT_BYTES:
                    overflow = True
                    raise ApplicationError("SUBMISSION_CAPTURE_OUTPUT_BOUND_EXCEEDED")
                target.extend(block)

        exit_code = None
        cleanup_error = None
        io_tasks = ()
        try:
            await process.close_stdin()
            io_tasks = (asyncio.create_task(drain(process.read_stdout, stdout)),
                        asyncio.create_task(drain(process.read_stderr, stderr)))
            await asyncio.wait_for(asyncio.gather(*io_tasks), timeout=self.timeout)
            observation = await process.wait_exit(timeout=self.timeout)
            if observation.state != "exited" or type(observation.exit_code) is not int:
                raise ApplicationError("SUBMISSION_CAPTURE_EXIT_UNKNOWN")
            exit_code = observation.exit_code
        except BaseException as error:
            for task in io_tasks:
                if not task.done():
                    task.cancel()
            if io_tasks:
                await asyncio.gather(*io_tasks, return_exceptions=True)
            try:
                observation = process.observe()
                if observation.state != "exited":
                    await process.cancel(force=True)
                    observation = await process.wait_exit(timeout=self.timeout)
                if observation.state != "exited":
                    cleanup_error = "SUBMISSION_CAPTURE_PROCESS_CLEANUP_UNKNOWN"
            except BaseException:
                cleanup_error = "SUBMISSION_CAPTURE_PROCESS_CLEANUP_UNKNOWN"
            if cleanup_error:
                raise ApplicationError(cleanup_error) from error
            if isinstance(error, ApplicationError):
                raise
            raise ApplicationError("SUBMISSION_CAPTURE_PROCESS_FAILED") from error
        finally:
            try:
                receipt = process.release()
                if receipt.get("transportReleased") is not True:
                    raise ApplicationError("SUBMISSION_CAPTURE_PROCESS_RELEASE_UNKNOWN")
            except BaseException:
                # A failed release is material uncertainty, even after exit.
                raise ApplicationError("SUBMISSION_CAPTURE_PROCESS_RELEASE_UNKNOWN")

        if overflow:
            raise ApplicationError("SUBMISSION_CAPTURE_OUTPUT_BOUND_EXCEEDED")
        after_bytes = self._snapshot()
        after_refs, after_digest = self._store_tree(after_bytes)
        changed = tuple(CapturedFile(path, before_refs.get(path), after_refs.get(path))
                        for path in sorted(set(before_refs) | set(after_refs))
                        if before_bytes.get(path) != after_bytes.get(path))
        return SubmissionCapture(
            manager_unit_id=str(unit_ref["unitId"]), environment_id=self.use.environment_id,
            use_id=self.use.identity,
            execution_operation_ref=operation_ref, prompt_input_digest=prompt_input_digest,
            execution_observation_ref=execution_observation.blob_ref,
            source_query_operation_ref=str(self.source_snapshot["queryOperationRef"]),
            source_query_input_digest=str(self.source_snapshot["queryInputDigest"]),
            process_id=process.identity, tool_version=self.tool_version,
            argv=self.argv, cwd=self.cwd,
            exit_code=exit_code, stdout=self._put(bytes(stdout), "application/octet-stream"),
            stderr=self._put(bytes(stderr), "application/octet-stream"), files=changed,
            before_tree_digest=before_digest, after_tree_digest=after_digest)


class SubmissionProvenanceOwner(Protocol):
    """Required future original-owner contract; no current implementation exists.

    A conforming owner must resolve the exact original dispatch, package,
    authorization, Unit, operation and checkout; observe bounded before/after
    file bytes and paths within the authorized root; provide real test argv,
    cwd, tool version, exit status and complete bounded stdout/stderr; observe
    effects from the original write owner; and return a guard that pins current
    source/capability facts until the caller's original Engineering COMMIT.

    The owner must also capture evidence into the same-authority Engineering
    BlobStore.  Implementations belong with the Execution owner, not here.
    """

    def guard_submission(
        self, context: object, submission: object, package: object
    ) -> AbstractContextManager[None]: ...


class EngineeringSubmissionSource:
    """SubmissionSourcePort adapter that refuses while the source owner is absent.

    This class intentionally has no permissive callback injection point: an
    arbitrary callback or structurally similar DTO is not evidence that it is
    the original Execution owner.  Product composition may use this explicit
    refusal until it can select and qualify that owner.
    """

    def guard_submission(self, context: object, submission: object, package: object):
        raise ApplicationError("SUBMISSION_SOURCE_PROVENANCE_UNAVAILABLE")


__all__ = ["CapturedFile", "EngineeringSubmissionCapture", "EngineeringSubmissionSource",
           "SubmissionCapture", "SubmissionProvenanceOwner"]
