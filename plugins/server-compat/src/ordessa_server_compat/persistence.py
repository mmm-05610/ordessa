"""Product record storage: aggregate repositories behind one runtime view.

Each aggregate module owns its transaction scopes; no repository commits
inside another aggregate's unit of work.
"""
from __future__ import annotations

from typing import Any

from ordessa_server.credentials import CredentialRecords
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server_compat.profiles import ProfileRecords
from ordessa_server_compat.sessions import SessionRecords
from pacthold_runtime_compat.storage import Database


class ProductRepositoryView:
    """Runtime-facing aggregate over the split product record stores."""

    def __init__(
        self, *, database: Database, idempotency: IdempotentRecords,
        credentials: CredentialRecords, workspaces: Any,
        profiles: ProfileRecords, sessions: SessionRecords,
    ) -> None:
        self.database = database
        self.idempotency = idempotency
        self.credentials = credentials
        self.workspaces = workspaces
        self.profiles = profiles
        self.sessions = sessions

    # -- runtime lifecycle hooks -------------------------------------------

    def mark_workspaces_unverified(self) -> None:
        self.workspaces.mark_all_unverified()

    def recover_interrupted_turns(self) -> int:
        return self.sessions.seal_interrupted_turns()

    # -- reads used by the transport and recovery -----------------------------

    def list_workspaces(self) -> list[dict[str, Any]]:
        return self.workspaces.list()

    def mark_workspace_verified(self, workspace_id: str) -> None:
        self.workspaces.mark_verified(workspace_id)

    def list_profiles(self) -> list[dict[str, Any]]:
        """Retained REST projection; the wire reads raw rows directly."""
        return [{
            "profile_id": row["id"], "name": row["name"],
            "harness_type": row["harness_type"],
            "config_revision": row["config_revision"],
            "native_generation": row["native_generation"],
            "credential_id": row["credential_id"], "run_state": row["run_state"],
                "account_id": row["account_id"] if "account_id" in row.keys() else None,
            "recovery_pending": bool(row["recovery_pending"]),
        } for row in self.profiles.list()]

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self.sessions.get_session(session_id)

    def list_events(self, session_id: str, after: int, *, limit: int = 500) -> list[dict[str, Any]]:
        return self.sessions.list_events(session_id, after, limit=limit)

    # -- legacy operation names kept for 37-era evidence tests -----------------

    def create_workspace(self, **kwargs):
        return self.workspaces.create(**kwargs)

    def create_profile(self, **kwargs):
        return self.profiles.create(**kwargs)

    def create_session(self, **kwargs):
        return self.sessions.create_session(**kwargs)

    def create_turn(self, **kwargs):
        return self.sessions.create_turn(**kwargs)

    def register_credential(self, credential_id: str, kind: str, secret_locator: str):
        return self.credentials.register(credential_id, kind, secret_locator)

    def get_credential(self, credential_id: str, *, kind: str | None = None):
        return self.credentials.get(credential_id, kind=kind)

    def get_turn_context(self, turn_id: str):
        return self.sessions.get_turn_context(turn_id)

    def set_turn_dispatch(self, turn_id: str, **kwargs):
        return self.sessions.set_turn_dispatch(turn_id, **kwargs)

    def append_turn_event(self, turn_id: str, kind: str, data):
        return self.sessions.append_turn_event(turn_id, kind, data)

    def complete_turn(self, turn_id: str, **kwargs):
        return self.sessions.complete_turn(turn_id, **kwargs)

    def mark_turn_cleanup(self, turn_id: str, state: str) -> None:
        self.sessions.mark_turn_cleanup(turn_id, state)

    def cancel_turn(self, turn_id: str):
        return self.sessions.record_cancel_request(turn_id)

    def finish_cancelled(self, turn_id: str):
        return self.sessions.finish_cancelled(turn_id)

    def fail_turn(self, turn_id: str, code: str, **kwargs):
        return self.sessions.fail_turn(turn_id, code, **kwargs)
