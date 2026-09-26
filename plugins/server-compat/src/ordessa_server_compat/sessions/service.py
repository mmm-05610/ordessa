"""Session use cases: first-send acceptance owns exactly one dispatch."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ordessa_server.errors import ServerError, unavailable
from ordessa_server_compat.execution import HarnessRegistry
from pacthold.execution.contracts import CancelOutcome, TurnExecutionPort
from ordessa_server_compat.profiles.permissions import resolve_all
from ordessa_server.records import digest, reject_sensitive_keys
from ordessa_server_compat.sessions.repository import SessionRecords


class SessionService:
    def __init__(self, records: SessionRecords, idempotency, objects, *,
                 harnesses: HarnessRegistry, profiles, credentials,
                 queue=None,
                 execution: TurnExecutionPort | None = None,
                 on_event=None, secret_store=None, core_filer=None) -> None:
        self.records = records
        self.idempotency = idempotency
        self.objects = objects
        self.harnesses = harnesses
        self.profiles = profiles
        self.credentials = credentials
        self.queue = queue
        self.execution = execution
        self.secret_store = secret_store
        self.on_event = on_event or (lambda: None)
        self.model_configs = None
        self.core_filer = core_filer
        self.native_profile_identity: tuple[str, str, str] | None = None
        self.native_workspace_validator = None
        if core_filer is not None:
            # a-3 K2-S': the single filing implementation lives on the records
            # (the queue-adoption successor is filed post-completion there);
            # a service-level filer forwards to it so both entries share one seam.
            records.attach_core_filer(core_filer)

    def file_core_records(self, turn_id: str) -> None:
        """a-3 K2-S entry (co-signed shape): delegates to the records home.

        Post-commit, idempotency-first, dormant while no filer is composed -
        see `SessionRecords.file_core_records` for the full semantics.
        """
        self.records.file_core_records(turn_id)

    def bind_model_configs(self, model_configs) -> None:
        self.model_configs = model_configs

    def bind_native_profile(self, profile_id: str, harness: str, config_digest: str) -> None:
        """Fix the one internal execution identity for a native Server."""
        identity = (profile_id, harness, config_digest)
        if self.native_profile_identity not in (None, identity):
            raise RuntimeError("NATIVE_PROFILE_ALREADY_BOUND")
        self.native_profile_identity = identity

    def bind_native_workspace_validator(self, validate) -> None:
        if self.native_workspace_validator not in (None, validate):
            raise RuntimeError("NATIVE_WORKSPACE_VALIDATOR_ALREADY_BOUND")
        self.native_workspace_validator = validate

    def _validate_native_workspace(self, workspace_id: str | None, session_id: str | None = None) -> None:
        if self.native_workspace_validator is None:
            return
        if workspace_id is None and session_id is not None:
            workspace_id = self.records.get_session(session_id)["workspace_id"]
        self.native_workspace_validator(workspace_id)

    def create_session(self, key: str, body: dict[str, Any]):
        if self.native_profile_identity is not None:
            raise ServerError(
                "NATIVE_FIRST_SEND_REQUIRED", "native sessions start with the first message",
                status=409,
            )
        return self.records.create_session(
            key=key, request_digest=digest(body),
            workspace_id=body["workspace_id"], profile_id=body["profile_id"],
        )

    # -- wire/1 intent acceptance ------------------------------------------

    def accept_intent(self, **kwargs: Any):
        """Accept one send intent; the winner is the only dispatcher.

        Configuration validation happens before acceptance so a rejected send
        leaves no Session and no queued work behind (core-semantics/1 §6).
        """
        self._validate_native_workspace(kwargs.get("workspace_id"), kwargs.get("session_id"))
        profile_id = kwargs.pop("profile_id")
        overrides = kwargs.pop("overrides", None)
        if overrides:
            self._validate_overrides_for(profile_id, overrides)
        effective, execution = self._effective_configuration(
            profile_id, overrides or [],
        )
        self._assert_profile_executable(profile_id, execution=execution)
        kwargs["effective_config_object_digest"] = self._publish_effective_configuration(
            profile_id, effective, execution,
        )
        kwargs["queue_records"] = self.queue
        kwargs["resolve_config_version"] = self._resolve_config_version
        return self.records.accept_intent(profile_id=profile_id, **kwargs)

    def _publish_effective_configuration(
        self, profile_id: str, configuration: dict[str, Any],
        execution: Mapping[str, Any] | None,
    ) -> str:
        profile = self.profiles.get(profile_id)
        value = {
            "schema_version": 1,
            "harness_type": profile["harness_type"],
            "configuration": configuration,
        }
        if execution is not None:
            value["execution"] = dict(execution)
        # a-3 K3' (S freeze side): the Profile's posture is resolved once at
        # acceptance and frozen into the Turn's effective object, so a delegated
        # child can narrow from this frozen fact instead of re-deriving it from
        # the live Profile row (the last "version frozen != content frozen"
        # second-producer path). Purely additive: nothing on the Server side
        # reads this object's content today, and older turns' objects keep
        # whatever shape they were published with - history is never rewritten.
        raw_rules = profile.get("permission_rules_json")
        value["permissions"] = resolve_all(
            json.loads(raw_rules) if raw_rules else [],
            preset=str(profile.get("permission_preset") or "default"),
        )
        record = self.objects.publish(json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode())
        return record.digest

    def _effective_configuration(
        self, profile_id: str, overrides: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        profile = self.profiles.get(profile_id)
        stored = json.loads(self.objects.read(profile["config_object_digest"]))
        configuration = dict(stored.get("configuration") or {})
        configuration.update({item["controlId"]: item["value"] for item in overrides})
        execution = None
        if self.model_configs is not None:
            execution = self.model_configs.freeze_execution_configuration(
                profile["harness_type"], configuration,
            )
        return configuration, execution

    def _assert_profile_executable(
        self, profile_id: str, *, execution: Mapping[str, Any] | None = None,
    ) -> None:
        profile = self.profiles.get(profile_id)
        self._assert_native_profile(profile_id, profile)
        harness_type = profile["harness_type"]
        if harness_type not in self.harnesses:
            raise unavailable("CAPABILITY_UNSUPPORTED", "Session Harness is not configured")
        descriptor = self.harnesses.get(harness_type)
        if self.execution is None:
            raise unavailable("EXECUTION_CAPABILITY_UNAVAILABLE", "Turn execution is not configured")
        credential_id = (execution or {}).get("credentialId") or profile.get("credential_id")
        if descriptor.credential_kind is not None:
            if not credential_id:
                raise ServerError(
                    "CREDENTIAL_REQUIRED", "Profile has no authorized credential", status=409,
                )
            self.credentials.get(credential_id, kind=descriptor.credential_kind)

    def _assert_native_profile(self, profile_id: str, profile=None) -> None:
        if self.native_profile_identity is not None:
            expected_id, expected_harness, expected_config = self.native_profile_identity
            if profile is None:
                profile = self.profiles.get(profile_id)
            if (profile_id != expected_id or profile["harness_type"] != expected_harness
                    or profile["archived_at"] is not None
                    or profile["config_object_digest"] != expected_config
                    or profile["credential_id"] is not None
                    or profile["account_id"] is not None
                    or profile["recovery_pending"]):
                raise ServerError(
                    "NATIVE_PROFILE_CONFLICT", "native execution identity changed",
                    status=409,
                )

    def _validate_overrides_for(self, profile_id: str, overrides: list[dict[str, Any]]) -> None:
        profile = self.profiles.get(profile_id)
        descriptor = self.harnesses.get(profile["harness_type"])
        locked = [item["controlId"] for item in overrides if item["controlId"] in descriptor.security_locked_controls]
        if locked:
            raise ServerError(
                "PROFILE_CONFIGURATION_INVALID",
                f"controls are security locked: {', '.join(sorted(locked))}",
                status=422,
            )
        if descriptor.configuration_validator is None:
            return
        configured = json.loads(self.objects.read(profile["config_object_digest"]))
        merged = dict(configured["configuration"])
        merged.update({item["controlId"]: item["value"] for item in overrides})
        try:
            descriptor.configuration_validator(merged)
        except (TypeError, ValueError) as exc:
            raise ServerError("TURN_OVERRIDES_INVALID", str(exc), status=422) from exc

    def _resolve_config_version(self, conn, profile, overrides) -> int:
        """Freeze the effective configuration version at acceptance time.

        The version is the Profile revision read inside the accepting
        transaction: a later Profile edit bumps the revision, so a queued item
        can still prove which configuration it was accepted under without the
        Server keeping a second copy of that configuration.
        """
        del overrides
        current = conn.execute(
            "SELECT config_revision FROM server_profiles WHERE id=?", (profile["id"],),
        ).fetchone()
        if current is None:
            raise ServerError("PROFILE_NOT_FOUND", "Profile was not found", status=404)
        return int(current["config_revision"])

    def create_turn(self, session_id: str, key: str, body: dict[str, Any]):
        if self.execution is None:
            raise unavailable("EXECUTION_CAPABILITY_UNAVAILABLE", "Turn execution is not configured")
        scope = f"POST:/sessions/{session_id}/turns"
        request_digest = digest(body)
        prior = self.idempotency.get(scope, key, request_digest)
        if prior:
            return prior
        self._validate_native_workspace(None, session_id)
        overrides = self._validated_overrides(session_id, body)
        self._assert_session_harness(session_id)
        # b-4/O-B3-1: freeze the effective configuration at acceptance with the
        # same helper pair the intent path uses; the Turn row carries the digest.
        _session, profile = self._session_profile(session_id)
        if int(profile["config_revision"]) != int(body["expected_profile_revision"]):
            raise ServerError(
                "PROFILE_REVISION_CONFLICT",
                "Profile revision changed before Turn creation",
                status=409,
            )
        effective, execution = self._effective_configuration(
            profile["id"], overrides or [],
        )
        frozen_digest = self._publish_effective_configuration(
            profile["id"], effective, execution,
        )
        claimed, status, result = self.records.create_turn(
            session_id=session_id, key=key, request_digest=request_digest,
            input_object_digest=self._publish_input(body),
            expected_profile_revision=body["expected_profile_revision"],
            effective_config_object_digest=frozen_digest,
        )
        self.on_event()
        if claimed:
            # Exactly the acceptance owner dispatches; a concurrent replay
            # observes the committed receipt and must not dispatch again.
            try:
                self.file_core_records(result["turn_id"])
                self.execution.accept(result["turn_id"])
            except Exception:
                # Dispatch/capture failures are durable Turn events recorded
                # by the execution port. The accepted HTTP receipt stays the
                # idempotent product answer.
                pass
        return status, result

    def import_credential(self, *, kind: str, source: str, key: str):
        """Import one credential from a source file into this Server's own store.

        The caller names a *path*: the secret is read by this Server's own secret
        store (symlink, file-type and size rules live there), so a request body
        never carries credential material, and the answer carries only the opaque
        id the product will reference. This is the running Server's counterpart
        to the one-shot CLI - the CLI cannot do it while this process holds the
        data-root lock, which is exactly the case the interface needs.

        The same key replays the same answer: an import that a client retries
        must not leave a second credential behind.
        """
        scope = "POST:/credentials"
        request_digest = digest({"kind": kind, "source": source})
        prior = self.idempotency.get(scope, key, request_digest)
        if prior:
            return prior
        if self.secret_store is None:
            raise unavailable("CREDENTIAL_STORE_UNAVAILABLE",
                              "This Server was composed without a secret store")
        try:
            credential_id, locator = self.secret_store.import_file(Path(source), kind)
        except (OSError, ValueError) as exc:
            raise ServerError(
                "CREDENTIAL_SOURCE_UNREADABLE",
                f"the credential source could not be imported: {type(exc).__name__}",
                status=422,
            ) from exc
        try:
            self.credentials.register(credential_id, kind, locator)
        except BaseException:
            self.secret_store.delete(locator)
            raise
        result = {"credentialId": credential_id, "kind": kind}
        return self.idempotency.save(scope, key, request_digest, 201, result)

    def list_credentials(self) -> list[dict[str, Any]]:
        """Every credential this Server can resolve, without its locator.

        Ids and kinds only: what a client needs to offer a choice, and nothing
        that says where the secret lives.
        """
        return self.credentials.list()

    def cancel_turn(self, turn_id: str, key: str):
        scope = f"POST:/turns/{turn_id}/cancel"
        request_digest = digest({"turn_id": turn_id})
        prior = self.idempotency.get(scope, key, request_digest)
        if prior:
            return prior
        if self.execution is None:
            raise unavailable("EXECUTION_CAPABILITY_UNAVAILABLE", "Turn cancellation is not configured")
        # A finished Turn has nothing to stop, and the answer says so instead of
        # recording a request that never described it: the same rule the wire's
        # `runs.stop` applies, so both entry points agree on what a late cancel
        # means. `record_cancel_request` returns the Turn untouched in that case.
        self.records.record_cancel_request(turn_id)
        requested = self.records.get_turn_context(turn_id)
        stopped = requested["state"] in self.records.TERMINAL_TURN_STATES
        accepted = False if stopped else (
            self.execution.cancel_execution(turn_id)
            == CancelOutcome.CONFIRMED_STOPPED)
        if not stopped:
            self.cancel_descendants(turn_id)
        self.on_event()
        return self.idempotency.save(
            scope, key, request_digest, 202,
            {"turn_id": turn_id, "cancel_requested": not stopped, "accepted": accepted},
        )

    def cancel_descendants(self, turn_id: str) -> list[str]:
        """Ask the turns one delegated turn left behind to stop as well.

        Order 65's rule, wired by order 086: a child turn runs *inside* its
        parent's tool call, so a parent that is stopped mid-call would otherwise
        leave a live process and a ledger that says the work is over. The
        recursion is bounded by the ledger - a turn's parent is always older -
        and the children come from `parent_turn_id`, not from any caller's word.
        """
        stopped: list[str] = []
        for child_id in self.records.live_child_turn_ids(turn_id):
            self.records.record_cancel_request(child_id)
            self.execution.cancel_execution(child_id)
            stopped.append(child_id)
            stopped.extend(self.cancel_descendants(child_id))
        return stopped

    def get_session(self, session_id: str):
        return self.records.get_session(session_id)

    def list_events(self, session_id: str, after: int):
        return self.records.list_events(session_id, after)

    # -- internals ------------------------------------------------------------

    def _publish_input(self, body: dict[str, Any]) -> str:
        record = self.objects.publish(json.dumps(
            {"schema_version": 1, "text": body["text"]},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode())
        return record.digest

    def _session_profile(self, session_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        session = self.records.get_session(session_id)
        profile = self.profiles.get(session["profile_id"])
        return session, profile

    def _assert_session_harness(self, session_id: str) -> None:
        _session, profile = self._session_profile(session_id)
        self._assert_native_profile(profile["id"], profile)
        harness_type = profile["harness_type"]
        if harness_type not in self.harnesses:
            raise unavailable("HARNESS_UNAVAILABLE", "Session Harness is not configured")
        descriptor = self.harnesses.get(harness_type)
        credential_id = profile.get("credential_id")
        if descriptor.credential_kind is not None:
            if not credential_id:
                raise ServerError(
                    "CREDENTIAL_REQUIRED", "Profile has no authorized credential", status=409,
                )
            self.credentials.get(credential_id, kind=descriptor.credential_kind)

    def _validated_overrides(self, session_id: str, body: dict[str, Any]):
        """Validate override merges before acceptance; None means no overrides."""
        overrides = body.get("overrides")
        if overrides is None:
            return None
        reject_sensitive_keys(overrides)
        _session, profile = self._session_profile(session_id)
        descriptor = self.harnesses.get(profile["harness_type"])
        if descriptor.configuration_validator is None:
            return overrides
        configured = json.loads(self.objects.read(profile["config_object_digest"]))
        merged = dict(configured["configuration"])
        merged.update(overrides)
        try:
            descriptor.configuration_validator(merged)
        except (TypeError, ValueError) as exc:
            raise ServerError("TURN_OVERRIDES_INVALID", str(exc), status=422) from exc
        return overrides
