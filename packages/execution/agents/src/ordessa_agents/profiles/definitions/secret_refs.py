"""Opaque Profile secret references; values and secret material stay external."""
from dataclasses import dataclass
import re


_NAMESPACE = re.compile(r"^[a-z][a-z0-9._-]{0,95}$")
_SECRET_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
_SECRET_REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}$")


@dataclass(frozen=True)
class SecretRef:
    """Opaque secret reference; possession of the reference grants no read."""

    ref: str
    revision: str
    owner_namespace: str
    access_purpose: str

    def __post_init__(self) -> None:
        if not isinstance(self.ref, str) or not _SECRET_REF.match(self.ref):
            raise ValueError("SecretRef.ref is malformed")
        if not isinstance(self.revision, str) or not _SECRET_REVISION.match(self.revision):
            raise ValueError("SecretRef.revision is malformed")
        for name in ("owner_namespace", "access_purpose"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _NAMESPACE.match(value):
                raise ValueError(f"SecretRef.{name} is malformed")
