"""Explicit action-only admission and execution seam; no default authority."""
from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Protocol

from ordessa_harness_api import ApplicationTarget, InvokeAction
from .operation_journal import NativeActivationReceipt


@dataclass(frozen=True)
class ActionGrant:
    target: ApplicationTarget
    publication_owner: str
    publication_token: str
    facet_id: str
    item_id: str
    contribution_version: str
    action_id: str
    schema_version: str
    scope: str = "session"

    def __post_init__(self):
        if not isinstance(self.target, ApplicationTarget) or self.scope != "session":
            raise ValueError("action grant requires exact session target/scope")
        for name in ("publication_owner", "publication_token", "facet_id", "item_id",
                     "contribution_version", "action_id", "schema_version"):
            value = getattr(self, name)
            if type(value) is not str or not value or value.strip() != value:
                raise ValueError("action grant identity incomplete")

    def allows(self, target, owner, token, intent, scope):
        return (target == self.target and scope == self.scope
                and owner == self.publication_owner and token == self.publication_token
                and intent.source.facet_id == self.facet_id and intent.source.item_id == self.item_id
                and intent.source.contribution_version == self.contribution_version
                and intent.action_id == self.action_id and intent.schema_version == self.schema_version)


@dataclass(frozen=True)
class ActionInvocation:
    publication_owner: str
    publication_token: str
    intent: InvokeAction


@dataclass(frozen=True)
class ActionBatch:
    target: ApplicationTarget
    invocations: tuple[ActionInvocation, ...]

    @property
    def manifest_json(self):
        entries = [{"publicationOwner": item.publication_owner,
                    "publicationToken": item.publication_token,
                    "source": asdict(item.intent.source), "actionId": item.intent.action_id,
                    "schemaVersion": item.intent.schema_version,
                    "input": item.intent.typed_payload,
                    "expectedObservation": item.intent.expected_observation}
                   for item in self.invocations]
        entries.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
        return json.dumps({"target": asdict(self.target), "scope": "session", "actions": entries},
                          sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

    @property
    def manifest_digest(self):
        return hashlib.sha256(self.manifest_json.encode("utf-8")).hexdigest()


class ActionExecutor(Protocol):
    """Trusted native owner seam. Preflight must have no external effects.

    Execute is called once after a durable reservation and manifest binding.
    A wire acknowledgement alone cannot stand in for an owner-issued receipt.
    Runtime.observe must independently query native state, not replay execute.
    """
    def preflight(self, batch: ActionBatch) -> None: ...
    def execute(self, operation_id: str, batch: ActionBatch) -> NativeActivationReceipt: ...
