"""Runtime artifact target and digest-format contracts; no filesystem access."""
from __future__ import annotations
import re

RUNTIME_ARTIFACT_DOMAIN = b"agentbox-runtime-artifact-tree-v1\n"

#: Order-of-magnitude ceiling the work order allows for ordinary files.  The
#: same budget is charged for directories, so a directory bomb cannot grow the
#: entry count past it; this is the stricter of the two readings.
MAX_RUNTIME_ARTIFACT_ENTRIES = 32_768
#: Total file content bound (1 GiB), charged before a file is hashed.
MAX_RUNTIME_ARTIFACT_BYTES = 1024 * 1024 * 1024
MAX_RUNTIME_ARTIFACT_PATH_BYTES = 4096
#: Declarations one bootstrap may carry.
MAX_RUNTIME_ARTIFACT_TREES = 8

RUNTIME_ARTIFACT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
RUNTIME_ARTIFACT_TARGET = re.compile(
    r"/runtime/artifacts/[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z",
)
_TARGET_PREFIX = "/runtime/artifacts/"


class RuntimeArtifactRejected(RuntimeError):
    """A typed refusal of one runtime artifact declaration or directory.

    032: this moved with the kernel contract edge; the compat
    ``ProjectionRejected`` base used only this subclass, and consumers catch
    this concrete class. ``code`` names the exact rule.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def runtime_artifact_name(target: str) -> str:
    """Return the stable name of a restricted guest target."""
    validate_runtime_artifact_target(target)
    return target[len(_TARGET_PREFIX):]


def validate_runtime_artifact_target(target: object) -> str:
    """Accept only ``/runtime/artifacts/<stable-name>`` and nothing else."""
    if not isinstance(target, str) or RUNTIME_ARTIFACT_TARGET.match(target) is None:
        raise RuntimeArtifactRejected(
            "RUNTIME_ARTIFACT_TARGET_INVALID",
            "runtime artifact target must be /runtime/artifacts/<stable-name>",
        )
    return target
