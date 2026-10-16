"""Pure Pi installation and private-root validation; no process/lifecycle owner."""
import os
import stat
from typing import Any, Mapping
from ordessa_execution_api.environment.operations import sealed_mapping

UNIT_PRIVATE_ROOT_FIELDS = frozenset({"cwd", "home", "profile", "tmp"})

class PiChannelRefused(RuntimeError):
    code = "PI_CHANNEL_REFUSED"


def verified_unit_private_roots(private_root_facts: Any) -> Mapping[str, str]:
    """Validate the exact four-root Unit ABI used by Pi.

    All paths are normalized absolute siblings under one private parent. The
    resolved paths must be identical to their supplied paths, rejecting
    symlinked ancestors and escapes. Nothing is created here.
    """
    if (not isinstance(private_root_facts, Mapping)
            or set(private_root_facts) != UNIT_PRIVATE_ROOT_FIELDS):
        raise PiChannelRefused(
            "Pi Unit roots require exactly cwd, home, profile and tmp")
    values: dict[str, str] = {}
    for key in sorted(UNIT_PRIVATE_ROOT_FIELDS):
        value = private_root_facts[key]
        if (not isinstance(value, str) or not value or not os.path.isabs(value)
                or os.path.normpath(value) != value or "\x00" in value
                or value == "/" or value.startswith("//")
                or any(ord(c) < 32 for c in value)):
            raise PiChannelRefused("private root path must be a normalized absolute directory")
        values[key] = value
    real = {key: os.path.realpath(value) for key, value in values.items()}
    if any(real[key] != value for key, value in values.items()):
        raise PiChannelRefused("Pi Unit roots must not traverse symlinks")
    if len(set(real.values())) != len(real):
        raise PiChannelRefused("private root directories must be distinct")
    parent = os.path.dirname(real["cwd"])
    if (not parent or parent == os.path.sep
            or any(os.path.dirname(path) != parent for path in real.values())):
        raise PiChannelRefused("private root directories must share one common root parent")
    values = {key: values[key] for key in ("home", "cwd", "profile", "tmp")}
    try:
        return sealed_mapping(values)
    except (TypeError, ValueError) as error:
        raise PiChannelRefused("private root facts are not JSON-encodable") from error


def verified_executable(executable: Any) -> str:
    if not isinstance(executable, str) or not executable or not os.path.isabs(executable):
        raise PiChannelRefused("pinned native executable must be an absolute path")
    try:
        info = os.stat(executable)
    except OSError as error:
        raise PiChannelRefused("pinned native executable is missing") from error
    if not stat.S_ISREG(info.st_mode) or not os.access(executable, os.X_OK):
        raise PiChannelRefused("pinned native executable is not a runnable regular file")
    return executable

