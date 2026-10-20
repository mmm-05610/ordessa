"""Harness activation identity, owned by the Harness domain."""
from dataclasses import dataclass
import re


_LOCAL_NAMESPACE = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")


def validate_namespace(value: object) -> str:
    """Validate the frozen Harness namespace spelling without a shared ID type."""
    if not isinstance(value, str) or not _LOCAL_NAMESPACE.match(value):
        raise ValueError("Harness environment namespace is malformed")
    return value


@dataclass(frozen=True)
class HarnessActivationRef:
    environment: str
    plugin_id: str
    generation: int

    def __post_init__(self) -> None:
        validate_namespace(self.environment)
        validate_namespace(self.plugin_id)
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("HarnessActivationRef.generation must be a non-negative int")
