"""Resolver for the official Codex native executable layout.

The npm launcher is deliberately not projected.  This resolver recognizes it
only as an identity hint and emits an execution-local, bounded set of exact
native members.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import stat
import struct
from typing import Mapping

from pacthold_runtime_compat.runtime_composition import RuntimeSourceDeclaration


class CodexExecutableResolutionError(ValueError):
    pass


def classify_login_status_failure(stderr: str, returncode: int) -> str:
    """Return a bounded, non-secret status class for preflight receipts."""
    text = (stderr or "").lower()
    if returncode == 0:
        return "logged-in"
    if "proc/self/exe" in text and "proc" in text:
        return "required-system-root-missing"
    if "auth.json" in text and any(word in text for word in ("permission", "read-only", "denied", "not readable")):
        return "credential-not-readable"
    if "auth" in text and any(word in text for word in ("format", "parse", "invalid")):
        return "native-auth-format-error"
    if "config" in text and any(word in text for word in ("read-only", "permission", "writ")):
        return "credential-write-required"
    if "config" in text and any(word in text for word in ("missing", "does not exist", "not found")):
        return "config-missing"
    if "home" in text and any(word in text for word in ("writ", "permission")):
        return "home-not-writable"
    if any(word in text for word in ("ssl", "certificate", "tls")):
        return "tls-roots-missing"
    if any(word in text for word in ("network", "connect", "dns")):
        return "network-unavailable"
    return "process-error"


@dataclass(frozen=True)
class CodexExecutableMember:
    kind: str
    guest_target: str
    digest: str
    mode: int
    purpose: str
    source_path: Path = field(repr=False, compare=False)
    tree: bool = False


@dataclass(frozen=True)
class CodexExecutableBundle:
    identity: str
    version: str
    target: str
    purpose: str
    members: tuple[CodexExecutableMember, ...]
    capabilities: Mapping[str, str]
    warnings: tuple[str, ...] = ()

    @property
    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(json.dumps({
            "identity": self.identity, "version": self.version,
            "target": self.target, "purpose": self.purpose,
            "members": [(m.kind, m.guest_target, m.digest, m.mode, m.tree) for m in self.members],
        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def runtime_sources(self) -> tuple[RuntimeSourceDeclaration, ...]:
        """Create dispatch-local declarations; source paths never leave this seam."""
        return tuple(RuntimeSourceDeclaration(m.kind, str(m.source_path), m.guest_target,
                                              "ro", m.digest) for m in self.members)


def _digest(path: Path, *, tree: bool = False) -> str:
    if path.is_symlink() or not path.exists():
        raise CodexExecutableResolutionError("CODEX_EXECUTABLE_SOURCE_UNAVAILABLE")
    mode = path.stat().st_mode
    if tree or path.is_dir():
        if not path.is_dir():
            raise CodexExecutableResolutionError("CODEX_EXECUTABLE_TREE_INVALID")
        rows = []
        for item in sorted(path.rglob("*")):
            rel = item.relative_to(path).as_posix()
            if item.is_symlink() or not (item.is_file() or item.is_dir()):
                raise CodexExecutableResolutionError("CODEX_EXECUTABLE_TREE_UNSAFE")
            rows.append((rel, "dir" if item.is_dir() else "file",
                         "" if item.is_dir() else hashlib.sha256(item.read_bytes()).hexdigest()))
        return "sha256:" + hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if not path.is_file() or not stat.S_ISREG(mode):
        raise CodexExecutableResolutionError("CODEX_EXECUTABLE_NOT_REGULAR")
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _native_x86_64(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            header = handle.read(20)
        return (header[:4] == b"\x7fELF" and header[4] == 2 and header[5] == 1
                and struct.unpack_from("<H", header, 18)[0] == 62)
    except OSError:
        return False


class CodexExecutableResolver:
    """Resolve only a direct native binary or the known official npm layout."""

    _target = "x86_64-unknown-linux-musl"

    def __init__(self, launcher: str | Path):
        self.launcher = Path(launcher).expanduser()

    def resolve(self, purpose: str = "login-status") -> CodexExecutableBundle:
        if purpose not in {"login-status", "app-server", "interactive"}:
            raise CodexExecutableResolutionError("CODEX_EXECUTABLE_PURPOSE_UNSUPPORTED")
        lexical = self.launcher
        try:
            canonical = lexical.resolve(strict=True)
        except OSError as exc:
            raise CodexExecutableResolutionError("CODEX_EXECUTABLE_SOURCE_UNAVAILABLE") from exc
        if lexical.is_symlink() and not self._official_bin_link(lexical, canonical):
            raise CodexExecutableResolutionError("CODEX_EXECUTABLE_SYMLINK_UNAUTHORIZED")
        if not canonical.is_file() or not os_access_executable(canonical):
            raise CodexExecutableResolutionError("CODEX_EXECUTABLE_NOT_EXECUTABLE")
        if _native_x86_64(canonical):
            member = CodexExecutableMember("executable", "/runtime/bin/codex", _digest(canonical), canonical.stat().st_mode & 0o777, "native Codex executable", canonical)
            return CodexExecutableBundle("direct-native:" + member.digest, "unknown", self._target, purpose, (member,), {"login-status": "supported"})
        if canonical.name != "codex.js" or canonical.parent.name != "bin":
            raise CodexExecutableResolutionError("CODEX_EXECUTABLE_LAYOUT_UNRECOGNIZED")
        package_root = canonical.parent.parent
        if package_root.name != "codex" or package_root.parent.name != "@openai":
            raise CodexExecutableResolutionError("CODEX_EXECUTABLE_LAYOUT_UNRECOGNIZED")
        metadata_path = package_root / "node_modules/@openai/codex-linux-x64/vendor" / self._target / "codex-package.json"
        native = metadata_path.parent / "bin/codex"
        if not metadata_path.is_file() or not native.is_file() or not _native_x86_64(native) or not os_access_executable(native):
            raise CodexExecutableResolutionError("CODEX_EXECUTABLE_NATIVE_MISSING_OR_WRONG_ARCH")
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CodexExecutableResolutionError("CODEX_EXECUTABLE_METADATA_INVALID") from exc
        if metadata.get("layoutVersion") != 1 or metadata.get("target") != self._target or metadata.get("entrypoint") != "bin/codex":
            raise CodexExecutableResolutionError("CODEX_EXECUTABLE_METADATA_DRIFT")
        members = [CodexExecutableMember("executable", "/runtime/bin/codex", _digest(native), native.stat().st_mode & 0o777, "native Codex executable", native)]
        if purpose != "login-status":
            resources = metadata_path.parent / "codex-resources"
            path_tools = metadata_path.parent / "codex-path"
            for kind, source, target, tree in (
                ("codex-code-mode-host", metadata_path.parent / "bin/codex-code-mode-host", "/runtime/bin/codex-code-mode-host", False),
                ("codex-path", path_tools, "/runtime/codex-path", True),
                ("codex-resources", resources, "/runtime/codex-resources", True),
            ):
                purpose_text = {"codex-code-mode-host": "Codex execution helper", "codex-path": "bounded bundled tools", "codex-resources": "Codex runtime resources"}[kind]
                members.append(CodexExecutableMember(kind, target, _digest(source, tree=tree), source.stat().st_mode & 0o777, purpose_text, source, tree))
        return CodexExecutableBundle("official-npm-native:" + metadata["target"], str(metadata["version"]), metadata["target"], purpose, tuple(members), {"login-status": "supported", "app-server": "supported", "interactive": "supported"})

    @staticmethod
    def _official_bin_link(lexical: Path, canonical: Path) -> bool:
        # The user-facing npm bin link canonicalizes to codex.js, while the
        # launcher itself subsequently selects the bounded native package.
        # Accept only that exact official package shape; arbitrary symlinks
        # remain rejected by the caller.
        parts = canonical.parts
        official_js = (canonical.name == "codex.js" and canonical.parent.name == "bin"
                       and canonical.parent.parent.name == "codex"
                       and canonical.parent.parent.parent.name == "@openai"
                       and canonical.parent.parent.parent.parent.name == "node_modules"
                       and "@openai" in parts)
        official_native = (canonical.name == "codex" and "@openai" in parts
                           and "codex-linux-x64" in parts and "vendor" in parts)
        return lexical.name == "codex" and lexical.parent.name == "bin" and (official_js or official_native)


def os_access_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & 0o111) and stat.S_ISREG(path.stat().st_mode)
