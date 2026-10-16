"""Opaque, complete directory binding identity; Workspace owns its facts."""
from dataclasses import dataclass
import re
from ordessa_execution_api.environment import EnvironmentId


@dataclass(frozen=True)
class DirectoryBindingRef:
    environment_namespace: str
    binding_id: str
    binding_revision: int
    content_digest: str

    def __post_init__(self):
        EnvironmentId(self.environment_namespace)
        if not isinstance(self.binding_id, str) or not re.fullmatch(r"[a-z][a-z0-9._-]{0,63}", self.binding_id):
            raise ValueError("invalid directory binding id")
        if type(self.binding_revision) is not int or self.binding_revision < 1:
            raise ValueError("invalid directory binding revision")
        if not isinstance(self.content_digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.content_digest):
            raise ValueError("invalid directory binding digest")

    def to_dict(self):
        return {"environmentNamespace": self.environment_namespace, "bindingId": self.binding_id,
                "bindingRevision": self.binding_revision, "contentDigest": self.content_digest}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {"environmentNamespace", "bindingId", "bindingRevision", "contentDigest"}:
            raise ValueError("invalid DirectoryBindingRef fields")
        return cls(value["environmentNamespace"], value["bindingId"], value["bindingRevision"], value["contentDigest"])
