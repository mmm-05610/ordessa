"""Controlled native boundary for product-composition acceptance tests.

This adapter simulates only Harness/native effects and observations. It is
independent from the Server Environment database and the Agent submission
journal, and records every dispatch (including an accidental second dispatch)
under the complete Environment/principal/request key. It does not deduplicate.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from ordessa_agent.submission_service import (
    NativeSubmitBinding,
    NativeSubmitDeclaration,
    NativeSubmitResult,
)
from ordessa_environment_api import RequestKey
from ordessa_persistence_sqlite import ProtectedFingerprintHmac
from pacthold.core.registration import CoreContributionSet
from ordessa_server_product.composition import ServerProductComposition


@dataclass(frozen=True)
class _AgentSubmitContract:
    contract_id = "agent.submit@1"


class _ControlledSubmissionPolicy:
    """Explicit test-only policy for local config intent and native submit."""

    def admit_invoke(self, principal: str, surface: str, guarantee: str) -> bool:
        return principal == "local" and surface in {
            "agent.configuration-intent", "agent.submit",
        }

    def admit_object_access(self, principal: str, object_ref: str, mode: str) -> bool:
        return principal == "local"


class ControlledNativeFixture:
    """SQLite-backed native submit/query/history stand-in, with no dedup path."""

    def __init__(
        self,
        effects_path: str | Path,
        *,
        mode: str,
        attachment_bytes: Mapping[str, bytes] | None = None,
        owner_ref: str = "native-owner:controlled-1",
        existing_conditional: bool = True,
        create_with_config_conditional: bool = True,
        immutable_attachments: bool = True,
    ) -> None:
        if mode not in ("existing", "createWithConfig"):
            raise ValueError("mode must be selected explicitly as existing or createWithConfig")
        self.effects_path = Path(effects_path)
        self.effects_path.parent.mkdir(parents=True, exist_ok=True)
        self.mode = mode
        self.owner_ref = owner_ref
        self.declaration = NativeSubmitDeclaration(
            owner_ref=owner_ref,
            existing_conditional=existing_conditional,
            create_with_config_conditional=create_with_config_conditional,
            immutable_attachments=immutable_attachments,
        )
        self._attachments = {name: bytes(data) for name, data in (attachment_bytes or {}).items()}
        self._target: str | None = None
        self._generation = 1
        self._session_id = "logical-session-controlled-1"
        self._native_session_id = "native-session-controlled-1"
        self.dispatches: list[tuple[str, str, str]] = []
        with sqlite3.connect(self.effects_path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS native_effects ("
                "environment_namespace TEXT NOT NULL, principal_scope TEXT NOT NULL, request_id TEXT NOT NULL, "
                "dispatch_count INTEGER NOT NULL, mode TEXT NOT NULL, payload TEXT NOT NULL, "
                "PRIMARY KEY(environment_namespace, principal_scope, request_id))"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS native_effect_events ("
                "event_id INTEGER PRIMARY KEY AUTOINCREMENT, environment_namespace TEXT NOT NULL, "
                "principal_scope TEXT NOT NULL, request_id TEXT NOT NULL, mode TEXT NOT NULL, payload TEXT NOT NULL)"
            )

    def set_mode(self, mode: str) -> None:
        """The test selects mode before each operation; the fixture never infers it."""
        if mode not in ("existing", "createWithConfig"):
            raise ValueError("mode must be selected explicitly as existing or createWithConfig")
        self.mode = mode

    def bind_backend_target(self, target: str) -> None:
        """Accept only the logical target returned by agent.session.resolve."""
        if not isinstance(target, str) or not target.strip():
            raise ValueError("a backend-minted canonical target is required")
        self._target = target

    def resolve_binding(self, target: str) -> NativeSubmitBinding:
        if self._target is None or target != self._target:
            raise RuntimeError("native fixture has no matching backend-minted target binding")
        return NativeSubmitBinding(
            target=target,
            owner_ref=self.owner_ref,
            mode=self.mode,
            surface_id="agent.submit",
            base_revision=f"native-revision-{self._generation}",
            identity={
                "sessionId": self._session_id,
                "nativeSessionId": self._native_session_id,
                "generation": str(self._generation),
            },
        )

    def read_attachment(self, target: str, attachment_id: str) -> bytes:
        if target != self._target:
            raise RuntimeError("attachment target does not match the backend-minted binding")
        try:
            return self._attachments[attachment_id]
        except KeyError as error:
            raise FileNotFoundError(f"controlled attachment unavailable: {attachment_id}") from error

    def submit_existing(self, request: RequestKey, capture: Any, *,
                        attachments: Mapping[str, bytes]) -> None:
        self._record_effect(request, capture, attachments=attachments, mode="existing")

    def create_with_config(self, request: RequestKey, capture: Any, *,
                           attachments: Mapping[str, bytes]) -> None:
        self._record_effect(request, capture, attachments=attachments, mode="createWithConfig")

    def _record_effect(self, request: RequestKey, capture: Any, *,
                       attachments: Mapping[str, bytes], mode: str) -> None:
        if mode != self.mode:
            raise RuntimeError("native method does not match the externally selected mode")
        if self._target is None or capture.target.get("target") != self._target:
            raise RuntimeError("capture target does not match native target binding")
        attachment_ids = tuple(capture.draft.get("attachmentIds", ()))
        if set(attachments) != set(attachment_ids) or any(
            not isinstance(content, bytes) for content in attachments.values()
        ):
            raise RuntimeError("native submission requires the exact immutable captured attachment bytes")
        attachment_hashes = {
            attachment_id: hashlib.sha256(attachments[attachment_id]).hexdigest()
            for attachment_id in attachment_ids
        }
        config_apply = {
            "outcome": "applied",
            "operationIds": list(capture.config_op_ids),
        }
        input_acceptance = {
            "outcome": "accepted",
            "draftRevision": capture.draft["draftRevision"],
            "session": {
                "sessionId": self._session_id,
                "nativeSessionId": self._native_session_id,
                "generation": self._generation,
                "ownerRef": self.owner_ref,
            },
        }
        run_result = {"outcome": "running", "runId": f"run-{capture.submission_id}"}
        payload = {
            "target": self._target,
            "mode": mode,
            "submissionId": capture.submission_id,
            "draft": _plain(capture.draft),
            "configOperationIds": list(capture.config_op_ids),
            "attachmentSha256": attachment_hashes,
            "binding": _plain(capture.binding),
            "configApply": config_apply,
            "inputAcceptance": input_acceptance,
            "runResult": run_result,
        }
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        key = (request.environment_namespace, request.principal_scope, request.request_id)
        # Deliberately increments on every dispatch: this fixture exposes a
        # duplicate native effect instead of hiding it behind fake idempotency.
        with sqlite3.connect(self.effects_path) as connection:
            connection.execute(
                "INSERT INTO native_effects VALUES (?, ?, ?, 1, ?, ?) "
                "ON CONFLICT(environment_namespace, principal_scope, request_id) DO UPDATE SET "
                "dispatch_count=dispatch_count+1, mode=excluded.mode, payload=excluded.payload",
                (*key, mode, payload_json),
            )
            connection.execute(
                "INSERT INTO native_effect_events(environment_namespace, principal_scope, request_id, mode, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (*key, mode, payload_json),
            )
        self.dispatches.append(key)

    def query(self, request: RequestKey) -> NativeSubmitResult | None:
        key = (request.environment_namespace, request.principal_scope, request.request_id)
        with sqlite3.connect(self.effects_path) as connection:
            row = connection.execute(
                "SELECT payload FROM native_effects WHERE environment_namespace=? AND principal_scope=? AND request_id=?",
                key,
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        return NativeSubmitResult(
            outcome="accepted",
            config_apply=payload["configApply"],
            input_acceptance=payload["inputAcceptance"],
            run_result=payload["runResult"],
        )

    def list_sessions(self, target: str) -> tuple[Mapping[str, Any], ...]:
        with sqlite3.connect(self.effects_path) as connection:
            rows = connection.execute(
                "SELECT payload FROM native_effects ORDER BY rowid"
            ).fetchall()
        sessions: dict[str, Mapping[str, Any]] = {}
        for (payload_json,) in rows:
            payload = json.loads(payload_json)
            if payload.get("target") != target:
                continue
            session = payload["inputAcceptance"].get("session")
            if not isinstance(session, Mapping):
                continue
            sessions[str(session["sessionId"])] = {
                "target": target,
                **dict(session),
            }
        return tuple(sessions.values())

    def effect_count(self, request: tuple[str, str, str]) -> int:
        with sqlite3.connect(self.effects_path) as connection:
            row = connection.execute(
                "SELECT dispatch_count FROM native_effects WHERE environment_namespace=? AND principal_scope=? AND request_id=?",
                request,
            ).fetchone()
        return 0 if row is None else int(row[0])

    def all_effect_counts(self) -> Mapping[tuple[str, str, str], int]:
        with sqlite3.connect(self.effects_path) as connection:
            rows = connection.execute(
                "SELECT environment_namespace, principal_scope, request_id, dispatch_count FROM native_effects"
            ).fetchall()
        return {(str(env), str(principal), str(request)): int(count)
                for env, principal, request, count in rows}


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(child) for child in value]
    return value


def controlled_submission_policy() -> _ControlledSubmissionPolicy:
    """Explicit test-only allow policy for the intended local operations."""
    return _ControlledSubmissionPolicy()


def test_protected_fingerprint() -> ProtectedFingerprintHmac:
    """Fixed test-only key material; never used by a product runtime."""
    return ProtectedFingerprintHmac(
        {"controlled-test-key": b"fixture-only-protected-hmac-key"},
        active_key_id="controlled-test-key",
    )


_DEFAULT = object()


def controlled_product_composition(
    *,
    native_submit_port: ControlledNativeFixture | None,
    fingerprint_port: Any = _DEFAULT,
    submission_policy: Any = _DEFAULT,
) -> ServerProductComposition:
    """Compose only the native/fingerprint/policy seam; keep all product services real."""
    return ServerProductComposition(
        native_submit_port=native_submit_port,
        fingerprint_port=test_protected_fingerprint() if fingerprint_port is _DEFAULT else fingerprint_port,
        submission_policy=controlled_submission_policy() if submission_policy is _DEFAULT else submission_policy,
        submission_contributions=CoreContributionSet(contracts=(_AgentSubmitContract,)),
    )
