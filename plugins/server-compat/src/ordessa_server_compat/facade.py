"""Neutral product use-case facade consumed by the HTTP transport.

Every capability answer here derives from what bootstrap actually
registered; nothing is claimed because a brand name is known.
"""
from __future__ import annotations

from typing import Any

from ordessa_server.credentials import CredentialRecords
from ordessa_server.errors import unavailable
from ordessa_server_compat.execution import HarnessRegistry
from pacthold.execution.contracts import TurnExecutionPort
from ordessa_server.events import EventNotifier
from ordessa_server_compat.profiles import ProfileService
from ordessa_server_compat.sessions import SessionService
from ordessa_workspace import WorkspaceService


class ProductService:
    def __init__(
        self, workspaces: WorkspaceService, profiles: ProfileService,
        sessions: SessionService, *,
        harnesses: HarnessRegistry, credentials: CredentialRecords,
        execution: TurnExecutionPort | None, notifier: EventNotifier,
    ) -> None:
        self.workspaces = workspaces
        self.profiles = profiles
        self.sessions = sessions
        self.harnesses = harnesses
        self.credentials = credentials
        self.execution = execution
        self.notifier = notifier

    # -- credentials --------------------------------------------------------

    def import_credential(self, *, kind: str, source: str, key: str):
        """The running Server's credential import (see SessionService)."""
        return self.sessions.import_credential(kind=kind, source=source, key=key)

    def list_credentials(self) -> list[dict[str, Any]]:
        """Ids and kinds this Server can resolve; never the locator."""
        return self.sessions.list_credentials()

    # -- capability discovery ---------------------------------------------

    def readiness(self) -> dict[str, Any]:
        blockers = list(self.workspaces.readiness_blockers())
        if self.execution is None:
            blockers.append({"code": "EXECUTION_CAPABILITY_UNAVAILABLE", "retryable": True})
        harnesses: dict[str, Any] = {}
        for harness_type in self.harnesses.registered():
            descriptor = self.harnesses.get(harness_type)
            credential_registered = (
                descriptor.credential_kind is None
                or self.credentials.has(kind=descriptor.credential_kind)
            )
            entry: dict[str, Any] = {
                "available": self.execution is not None and credential_registered,
                "capability_claims": dict(descriptor.capability_claims),
                "credential_registered": credential_registered,
            }
            if self.execution is None:
                entry["unavailable_reason"] = "EXECUTION_CAPABILITY_UNAVAILABLE"
            elif not credential_registered:
                entry["unavailable_reason"] = "CREDENTIAL_SOURCE_NOT_AUTHORIZED"
            harnesses[harness_type] = entry
        return {
            "service": "ready", "api_version": "v1", "storage": "ready",
            "worker_protocol": "1",
            "capabilities": {
                "product_records": True,
                "wsl": self.workspaces.connector is not None,
                "execution": self.execution is not None,
                "harnesses": harnesses,
            },
            "blockers": blockers,
        }

    # -- workspace/connection use cases -------------------------------------

    def distributions(self):
        return self.workspaces.distributions()

    def probe(self, key: str, distribution: str, user: str | None):
        return self.workspaces.probe(key, distribution, user)

    def browse(self, key: str, probe_id: str, path: str):
        return self.workspaces.browse(key, probe_id, path)

    def create_workspace(self, key: str, body: dict[str, Any]):
        return self.workspaces.create(key, body)

    # -- profile use cases ----------------------------------------------------

    def create_profile(self, key: str, body: dict[str, Any]):
        return self.profiles.create(key, body)

    # -- session use cases ------------------------------------------------------

    def create_session(self, key: str, body: dict[str, Any]):
        return self.sessions.create_session(key, body)

    def create_turn(self, session_id: str, key: str, body: dict[str, Any]):
        if self.execution is None:
            raise unavailable("EXECUTION_CAPABILITY_UNAVAILABLE", "Turn execution is not configured")
        return self.sessions.create_turn(session_id, key, body)

    def cancel_turn(self, turn_id: str, key: str):
        return self.sessions.cancel_turn(turn_id, key)
