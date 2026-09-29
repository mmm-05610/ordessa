"""Session selection, overlay and same-session switching (US2/US3/US4).

v1 state machine (settled -> pending -> settled/needs_recovery) is preserved;
v2 changes *how* a switch is proven (docs/design/profile-v2/application.md):

- The pending switch is applied at the next-turn admission boundary through
  the Harness-owned ``HarnessConfigPort`` (inspect/plan/apply/reconcile).
  Profile never claims success from its own database state.
- Every attempt writes an ``ApplicationJournal`` entry; only a port-confirmed
  outcome commits the binding, clears overlays and records an AppliedReceipt.
- A port-confirmed outcome that cannot be committed locally leaves the
  journal ``unknown`` — send stays blocked until ``reconcile`` resolves it.
- v1 history keeps its rows; without a receipt it is projected as
  ``legacy-unverified`` and can never be upgraded to confirmed (PV-04).
"""
from __future__ import annotations

import sqlite3
from typing import Any

from . import application_journal as journal
from . import repository as repo
from .contracts import (
    EVIDENCE_PORT_CONFIRMED,
    ApplyConfirmed,
    ApplyRejected,
    ApplyUnknown,
    AppliedReceipt,
    ConfigIntent,
    JournalEntry,
    SessionRef,
    UNSET,
)
from .errors import ProfileError
from .harness_port_adapter import PermitUnavailable
from .resolution import (
    Resolution,
    check_required,
    conflict_free,
    resolve_profile_items,
    resolve_session_items,
)
from .sensitive import digest, json_dumps, json_loads, reject_sensitive_keys


class SessionService:
    def __init__(self, core) -> None:
        self.core = core

    # -- helpers -------------------------------------------------------
    def _idempotent(self, conn: sqlite3.Connection, scope: str, key: str,
                    request: dict[str, Any]) -> dict[str, Any] | None:
        return repo.idempotency_check(conn, scope, key, digest(request))

    def _require_session(self, conn: sqlite3.Connection,
                         session_id: str) -> dict[str, Any]:
        """Address a session by canonical uid or legacy v1 id."""
        row = None
        if isinstance(session_id, str) and session_id:
            row = repo.get_session_by_uid(conn, session_id)
            if row is None:
                row = repo.get_session(conn, session_id)
        if row is None:
            raise ProfileError(
                "SESSION_NOT_FOUND", "Session was not found", status=404,
            )
        return row

    def _validate_target(self, conn: sqlite3.Connection, session: dict[str, Any],
                         profile_id: str) -> dict[str, Any]:
        """Selection gates; every refusal happens before any state change
        (US2.5, FR-006)."""
        target = self.core.require_profile(conn, profile_id)
        if target["harness_id"] != session["harness_id"]:
            raise ProfileError(
                "SESSION_PROFILE_MISMATCH",
                "Profile belongs to a different Harness; cross-Harness "
                "switching is out of scope",
                status=409,
            )
        if target["archived_at"] is not None:
            raise ProfileError(
                "PROFILE_ARCHIVED", "Profile is archived", status=409,
            )
        return target

    def session_ref_of(self, session: dict[str, Any]) -> SessionRef:
        return SessionRef(
            realm=session["realm"], harness_id=session["harness_id"],
            native_session_key=session["native_session_key"],
            session_uid=session["session_uid"],
        )

    def session_view(self, session: dict[str, Any]) -> dict[str, Any]:
        blockers = json_loads(session["blockers_json"]) \
            if session["blockers_json"] else None
        return {
            "session_id": session["session_id"],
            "session_uid": session["session_uid"],
            "realm": session["realm"],
            "native_session_key": session["native_session_key"],
            "harness_id": session["harness_id"],
            "current_profile_id": session["current_profile_id"],
            "current_revision": int(session["current_revision"]),
            "pending_profile_id": session["pending_profile_id"],
            "pending_seq": (
                int(session["pending_seq"])
                if session["pending_seq"] is not None else None
            ),
            "switch_state": session["switch_state"],
            "blockers": blockers,
        }

    # -- US2: selection --------------------------------------------------
    def open_session(self, key: str, *, session_id: str, harness_id: str,
                     profile_id: str, realm: str = "local",
                     session_uid: str | None = None) -> dict[str, Any]:
        """Register a session binding.

        v2 callers pass ``session_uid`` (the canonical stable identity);
        ``session_id`` stays the routing/legacy address and must not be
        treated as cross-connection identity (data-model.md §1).
        """
        if not self.core.harnesses.exists(harness_id):
            raise ProfileError(
                "HARNESS_UNKNOWN", "Requested Harness is not configured",
                status=404,
            )
        uid = session_uid or session_id
        if uid.startswith("legacy:") and uid != session_id:
            raise ProfileError(
                "PROFILE_VALUE_INVALID",
                "the legacy: uid prefix is reserved for migrated rows",
                status=422,
            )
        request = {"session_id": session_id, "harness_id": harness_id,
                   "profile_id": profile_id, "realm": realm, "uid": uid}
        with self.core.db.transaction() as conn:
            prior = self._idempotent(conn, "sessions.open", key, request)
            if prior:
                return prior["response"]
            existing = repo.get_session_by_uid(conn, uid)
            if existing is not None:
                raise ProfileError(
                    "PROFILE_VALUE_INVALID",
                    "session already exists", status=422,
                )
            self._validate_target(conn, {"harness_id": harness_id}, profile_id)
            profile = self.core.require_profile(conn, profile_id)
            timestamp = self.core.timestamp()
            repo.upsert_session(
                conn, session_id=session_id, harness_id=harness_id,
                current_profile_id=profile_id,
                current_revision=int(profile["current_revision"]),
                switch_state="settled", pending_profile_id=None,
                pending_seq=None, blockers=None, timestamp=timestamp,
                realm=realm, session_uid=uid,
                native_session_key=session_id,
            )
            session = self._require_session(conn, uid)
            response = self.session_view(session)
            repo.idempotency_insert(
                conn, "sessions.open", key, digest(request), 201, response,
                timestamp,
            )
            return response

    def select_profile(self, key: str, *, session_id: str,
                       profile_id: str) -> dict[str, Any]:
        """Register the user's selection as pending; nothing is applied here
        (PA01: the choice is recorded and takes effect on the next submit).
        Selecting the current profile again never clears overlays (G07)."""
        request = {"session_id": session_id, "profile_id": profile_id}
        with self.core.db.transaction() as conn:
            prior = self._idempotent(
                conn, f"sessions.select:{session_id}", key, request,
            )
            if prior:
                return prior["response"]
            session = self._require_session(conn, session_id)
            self._validate_target(conn, session, profile_id)
            next_seq = (int(session["pending_seq"]) if session["pending_seq"]
                        is not None else 0) + 1
            repo.upsert_session(
                conn, session_id=session["session_id"],
                harness_id=session["harness_id"],
                current_profile_id=session["current_profile_id"],
                current_revision=int(session["current_revision"]),
                switch_state="pending", pending_profile_id=profile_id,
                pending_seq=next_seq, blockers=None,
                timestamp=self.core.timestamp(),
                realm=session["realm"],
                session_uid=session["session_uid"],
                native_session_key=session["native_session_key"],
            )
            updated = self._require_session(conn, session_id)
            response = self.session_view(updated)
            repo.idempotency_insert(
                conn, f"sessions.select:{session_id}", key, digest(request),
                200, response, self.core.timestamp(),
            )
            return response

    # -- US2: begin-turn validation + atomic application -----------------
    def begin_turn(self, key: str, *, session_id: str) -> dict[str, Any]:
        """Next-turn admission boundary.

        Without a pending selection this resolves the current configuration
        and records the turn (no application claim).  With a pending
        selection the full difference is planned and applied through the
        Harness port before the message may go out; anything unproven blocks
        the send (G09/G10)."""
        request = {"session_id": session_id}
        scope = f"sessions.begin_turn:{session_id}"
        with self.core.db.read() as conn:
            session = self._require_session(conn, session_id)
            switch_state = session["switch_state"]
            pending_profile = session["pending_profile_id"]
        if switch_state == "needs_recovery":
            raise ProfileError(
                "SESSION_NEEDS_RECOVERY",
                "session is marked not safe to send; run verify_recovery",
                status=409,
            )
        if pending_profile is not None:
            return self._begin_turn_switch(
                key, scope, request, session_id, pending_profile)
        with self.core.db.transaction() as conn:
            prior = self._idempotent(conn, scope, key, request)
            if prior:
                return prior["response"]
            session = self._require_session(conn, session_id)
            result = self._turn_on_current(conn, session)
            repo.idempotency_insert(
                conn, scope, key, digest(request), 200, result,
                self.core.timestamp(),
            )
            return result

    def _begin_turn_switch(self, key: str, scope: str, request: dict[str, Any],
                           session_id: str, pending_profile: str) -> dict[str, Any]:
        port = self.core.config_port
        with self.core.db.read() as conn:
            prior = self._idempotent(conn, scope, key, request)
            if prior:
                return prior["response"]
            session = self._require_session(conn, session_id)
            entry = journal.latest_for_session(conn, session["session_uid"])
            if entry is not None and entry["state"] == "unknown":
                raise ProfileError(
                    "SESSION_NEEDS_RECOVERY",
                    "an earlier application is unproven; reconcile before "
                    "sending",
                    status=409,
                ).with_current({"operation_id": entry["operation_id"]})
        session_ref = self.session_ref_of(session)
        operation_id = self.core.mint_id("op")
        operation_key = f"{session_ref.session_uid}:{operation_id}"
        policy = self.core.policy.get_public(session_ref.realm)
        intents, blocked_items = self.core.compile_switch_diffs(
            session, pending_profile)
        if blocked_items:
            raise ProfileError(
                "SWITCH_BLOCKED",
                "target profile has differences that cannot be applied "
                "to this session",
                status=409,
            ).with_blockers(blocked_items)
        # US4.6: every harness-required item must resolve usable on the
        # target — a required-but-absent item refuses the switch (G13).
        with self.core.db.read() as conn:
            target_resolved = resolve_profile_items(
                conn, profile_id=pending_profile,
                harness_id=session["harness_id"],
                config_revision=self._target_revision(pending_profile),
                provider_lookup=self.core.provider_lookup,
            )
        check_required(
            target_resolved,
            self.core.harnesses.required_item_ids(session["harness_id"]),
        )
        plan_digest = digest([_intent_facts(i) for i in intents])
        with self.core.db.transaction() as conn:
            journal.record(conn, JournalEntry(
                operation_id=operation_id, session_ref=session_ref,
                state="planned", profile_id=pending_profile,
                profile_revision=self._target_revision(pending_profile),
                plan_digest=plan_digest,
                created_at=self.core.timestamp(),
            ))
        if port is None:
            # Typed absence: nothing was applied, nothing was cleared; the
            # attempt is journalled as planned and the pending selection
            # stays intact for when a port appears.
            raise ProfileError(
                "APPLICATION_PORT_ABSENT",
                "no Harness application port is registered; the pending "
                "switch cannot be proven and the turn stays blocked",
                status=409,
            )
        generation = self.core.registry.generation
        try:
            inspection = port.inspect(session_ref)
            plan = port.plan(session_ref, tuple(intents), operation_key)
        except ProfileError:
            raise
        except Exception as exc:  # port crashed before producing a verdict
            self._journal_transition(
                operation_id, "unknown",
                failure=f"port-failure:{type(exc).__name__}")
            self._mark_needs_recovery(session)
            raise ProfileError(
                "SESSION_NEEDS_RECOVERY",
                "the application port failed before producing a verdict; "
                "reconcile before sending",
                status=409,
            ) from exc
        del inspection  # fence facts live in plan.fence; kept for traceability
        self.core.registry.check_current(generation)
        if plan.blocked:
            self._journal_transition(
                operation_id, "rejected",
                failure="plan-blocked",
                detail_refs=tuple(
                    f"{i.facet_id}/{i.item_id}" for i in plan.items
                    if i.status == "blocked"),
            )
            raise ProfileError(
                "SWITCH_BLOCKED",
                "the Harness refused to apply the pending configuration",
                status=409,
            ).with_blockers([
                {"facet_id": i.facet_id, "item_id": i.item_id,
                 "reason": i.status, "detail": i.reason}
                for i in plan.items if i.status == "blocked"
            ])
        with self.core.db.transaction() as conn:
            journal.transition(
                conn, operation_id=operation_id, new_state="applying",
                timestamp=self.core.timestamp(),
            )
        try:
            outcome = port.apply(plan, tuple(intents))
        except PermitUnavailable as exc:
            # The host authorization gate refused before anything was
            # attempted: retriable refusal, journal rejected, no recovery
            # state (application.md §3 — unknown is only for started work).
            self._journal_transition(
                operation_id, "rejected", failure=f"permit-unavailable:{exc}")
            raise ProfileError(
                "SWITCH_BLOCKED",
                "the host did not mint a submission permit; nothing was "
                "applied and the switch can be retried",
                status=409,
            ) from exc
        except Exception as exc:
            self._journal_transition(
                operation_id, "unknown",
                failure=f"port-failure:{type(exc).__name__}")
            self._mark_needs_recovery(session)
            raise ProfileError(
                "SESSION_NEEDS_RECOVERY",
                "the application port failed mid-apply; reconcile before "
                "sending",
                status=409,
            ) from exc
        return self._handle_apply_outcome(
            key=key, scope=scope, request=request, session=session,
            session_ref=session_ref, pending_profile=pending_profile,
            operation_id=operation_id,
            plan=plan, outcome=outcome, policy=policy,
        )

    def _handle_apply_outcome(self, *, key, scope, request, session,
                              session_ref, pending_profile, operation_id,
                              plan, outcome, policy) -> dict[str, Any]:
        timestamp = self.core.timestamp()
        if isinstance(outcome, ApplyRejected):
            self._journal_transition(
                operation_id, "rejected", failure=outcome.reason)
            raise ProfileError(
                "SWITCH_BLOCKED",
                "the Harness rejected the application; the previous "
                "configuration remains in force",
                status=409,
            ).with_blockers([
                {"facet_id": i.facet_id, "item_id": i.item_id,
                 "reason": i.status, "detail": i.reason}
                for i in outcome.items
            ] or [{"facet_id": "*", "item_id": "*", "reason": "rejected",
                  "detail": outcome.reason}])
        if isinstance(outcome, ApplyUnknown):
            self._journal_transition(
                operation_id, "unknown", failure=outcome.reason)
            self._mark_needs_recovery(session)
            raise ProfileError(
                "SESSION_NEEDS_RECOVERY",
                "the application outcome could not be proven; the session "
                "stays blocked until reconcile",
                status=409,
            ).with_current({"operation_id": operation_id})
        if not isinstance(outcome, ApplyConfirmed):
            self._journal_transition(operation_id, "unknown",
                                     failure="unexpected-outcome")
            self._mark_needs_recovery(session)
            raise ProfileError(
                "SESSION_NEEDS_RECOVERY",
                "the application port returned an unrecognized outcome",
                status=409,
            )
        receipt = AppliedReceipt(
            operation_id=operation_id,
            session_ref=session_ref,
            runtime_generation=outcome.receipt.runtime_generation,
            config_digest=outcome.receipt.config_digest,
            profile_id=pending_profile,
            profile_revision=self._target_revision(pending_profile),
            overlay_revision=int(session["pending_seq"])
            if session["pending_seq"] is not None else None,
            policy_revision=int(policy["revision"]),
            provider_generations={
                "registry": self.core.registry.generation,
                **outcome.receipt.provider_generations,
            },
            evidence_kind=outcome.receipt.evidence_kind or EVIDENCE_PORT_CONFIRMED,
            confirmed_at=timestamp,
            execution_id=outcome.receipt.execution_id,
        )
        try:
            with self.core.db.transaction() as conn:
                if self.core.commit_injection is not None:
                    # Counterexample hook: external success + local commit
                    # failure (G10/G11).  Raises inside the transaction.
                    self.core.commit_injection(operation_id)
                journal.transition(
                    conn, operation_id=operation_id, new_state="confirmed",
                    timestamp=timestamp,
                )
                journal.record_receipt(conn, receipt, timestamp)
                repo.upsert_session(
                    conn, session_id=session["session_id"],
                    harness_id=session["harness_id"],
                    current_profile_id=pending_profile,
                    current_revision=receipt.profile_revision,
                    switch_state="settled", pending_profile_id=None,
                    pending_seq=None, blockers=None, timestamp=timestamp,
                    realm=session["realm"],
                    session_uid=session["session_uid"],
                    native_session_key=session["native_session_key"],
                )
                # Successful switch only: clear the old overlays (G07).
                repo.clear_overlays(conn, session["session_id"])
                target_resolution = resolve_profile_items(
                    conn, profile_id=pending_profile,
                    harness_id=session["harness_id"],
                    config_revision=receipt.profile_revision,
                    provider_lookup=self.core.provider_lookup,
                )
                result = self._record_turn(
                    conn, session=session, resolution=target_resolution,
                    profile_id=pending_profile,
                    revision=receipt.profile_revision, applied_switch=True,
                    pending_seq=receipt.overlay_revision,
                    ticket={
                        "operation_id": operation_id,
                        "applied": True,
                        "receipt": receipt.as_public_dict(),
                    },
                )
                repo.idempotency_insert(
                    conn, scope, key, digest(request), 200, result, timestamp,
                )
        except ProfileError:
            raise
        except Exception as exc:
            # External success + local commit failure: journal unknown; the
            # switch is NOT reported and the send stays blocked (G10/G11).
            self._journal_transition(
                operation_id, "unknown",
                failure=f"commit-failed:{type(exc).__name__}",
                detail_refs=(f"receipt-digest:{receipt.config_digest}",),
            )
            self._mark_needs_recovery(session)
            raise ProfileError(
                "SESSION_NEEDS_RECOVERY",
                "the configuration was confirmed externally but the local "
                "commit failed; reconcile before sending",
                status=409,
            ) from exc
        return result

    def _journal_transition(self, operation_id: str, new_state: str,
                            failure: str | None = None,
                            detail_refs: tuple[str, ...] = ()) -> None:
        with self.core.db.transaction() as conn:
            journal.transition(
                conn, operation_id=operation_id, new_state=new_state,
                timestamp=self.core.timestamp(), failure=failure,
                detail_refs=detail_refs,
            )

    def _mark_needs_recovery(self, session: dict[str, Any]) -> None:
        """PA05: an unprovable application enters needs-recovery and blocks
        the send.  Bindings and overlays are untouched — only the visible
        safety state changes (recovery never guesses, see verify_recovery)."""
        with self.core.db.transaction() as conn:
            repo.upsert_session(
                conn, session_id=session["session_id"],
                harness_id=session["harness_id"],
                current_profile_id=session["current_profile_id"],
                current_revision=int(session["current_revision"]),
                switch_state="needs_recovery",
                pending_profile_id=session["pending_profile_id"],
                pending_seq=session["pending_seq"],
                blockers=[{"reason": "application_unproven"}],
                timestamp=self.core.timestamp(),
                realm=session["realm"],
                session_uid=session["session_uid"],
                native_session_key=session["native_session_key"],
            )

    def reconcile(self, key: str, *, session_id: str) -> dict[str, Any]:
        """Resolve an ``unknown`` journal through the port (G11).  Never
        replays user messages; a port-confirmed reconciliation is recorded
        and the session settles with the reconciled configuration."""
        port = self.core.config_port
        if port is None:
            raise ProfileError(
                "APPLICATION_PORT_ABSENT",
                "no Harness application port is registered; the unknown "
                "application cannot be reconciled",
                status=409,
            )
        with self.core.db.read() as conn:
            session = self._require_session(conn, session_id)
            entry = journal.latest_for_session(conn, session["session_uid"])
        if entry is None or entry["state"] != "unknown":
            raise ProfileError(
                "PROFILE_VALUE_INVALID",
                "no unknown application to reconcile for this session",
                status=422,
            )
        operation_id = entry["operation_id"]
        operation_key = f"{session['session_uid']}:{operation_id}"
        outcome = port.reconcile(operation_key, self.session_ref_of(session))
        timestamp = self.core.timestamp()
        if outcome.state == "confirmed-current" and outcome.receipt is not None:
            receipt = AppliedReceipt(
                operation_id=operation_id,
                session_ref=self.session_ref_of(session),
                runtime_generation=outcome.receipt.runtime_generation,
                config_digest=outcome.receipt.config_digest,
                profile_id=entry["profile_id"],
                profile_revision=int(entry["profile_revision"]),
                overlay_revision=None,
                policy_revision=int(
                    self.core.policy.get_public(session["realm"])["revision"]),
                provider_generations={
                    "registry": self.core.registry.generation,
                    **outcome.receipt.provider_generations,
                },
                evidence_kind=outcome.receipt.evidence_kind
                or EVIDENCE_PORT_CONFIRMED,
                confirmed_at=timestamp,
                execution_id=outcome.receipt.execution_id,
            )
            with self.core.db.transaction() as conn:
                journal.transition(
                    conn, operation_id=operation_id, new_state="confirmed",
                    timestamp=timestamp,
                    detail_refs=("reconciled",),
                )
                journal.record_receipt(conn, receipt, timestamp)
                repo.upsert_session(
                    conn, session_id=session["session_id"],
                    harness_id=session["harness_id"],
                    current_profile_id=entry["profile_id"],
                    current_revision=receipt.profile_revision,
                    switch_state="settled", pending_profile_id=None,
                    pending_seq=None, blockers=None, timestamp=timestamp,
                    realm=session["realm"],
                    session_uid=session["session_uid"],
                    native_session_key=session["native_session_key"],
                )
                repo.clear_overlays(conn, session["session_id"])
            return {
                "operation_id": operation_id,
                "state": "confirmed-current",
                "receipt": receipt.as_public_dict(),
                "session": self._session_view_safe(session["session_uid"]),
            }
        if outcome.state == "rejected-unchanged":
            self._journal_transition(
                operation_id, "rejected",
                failure=outcome.reason or "reconcile: unchanged",
                detail_refs=("reconciled",),
            )
            # The pending switch did not take effect; restore the settled
            # state on the previous binding without clearing anything.
            with self.core.db.transaction() as conn:
                repo.upsert_session(
                    conn, session_id=session["session_id"],
                    harness_id=session["harness_id"],
                    current_profile_id=session["current_profile_id"],
                    current_revision=int(session["current_revision"]),
                    switch_state="settled", pending_profile_id=None,
                    pending_seq=None,
                    blockers=[{"reason": "switch_rejected_after_unknown"}],
                    timestamp=timestamp,
                    realm=session["realm"],
                    session_uid=session["session_uid"],
                    native_session_key=session["native_session_key"],
                )
            return {
                "operation_id": operation_id,
                "state": "rejected-unchanged",
                "session": self._session_view_safe(session["session_uid"]),
            }
        return {
            "operation_id": operation_id,
            "state": "unknown",
            "reason": outcome.reason or "still unverifiable",
        }

    def _session_view_safe(self, session_addr: str) -> dict[str, Any]:
        with self.core.db.read() as conn:
            return self.session_view(self._require_session(conn, session_addr))

    def _target_revision(self, profile_id: str) -> int:
        with self.core.db.read() as conn:
            return int(self.core.require_profile(conn, profile_id)[
                "current_revision"])

    def _turn_on_current(self, conn: sqlite3.Connection,
                         session: dict[str, Any]) -> dict[str, Any]:
        profile = self.core.require_profile(conn, session["current_profile_id"])
        resolution = resolve_session_items(
            conn, session_id=session["session_id"],
            profile_id=profile["profile_id"],
            harness_id=session["harness_id"],
            config_revision=int(profile["current_revision"]),
            provider_lookup=self.core.provider_lookup,
        )
        conflict_free(resolution, self.core.provider_lookup)
        check_required(
            resolution,
            self.core.harnesses.required_item_ids(session["harness_id"]),
        )
        return self._record_turn(
            conn, session=session, resolution=resolution,
            profile_id=profile["profile_id"],
            revision=int(profile["current_revision"]),
            applied_switch=False, pending_seq=None,
        )

    def _record_turn(self, conn: sqlite3.Connection, *, session: dict[str, Any],
                     resolution: Resolution, profile_id: str, revision: int,
                     applied_switch: bool, pending_seq: int | None,
                     ticket: dict[str, Any] | None = None) -> dict[str, Any]:
        turn_id = self.core.mint_id("turn")
        turn_seq = repo.latest_turn_seq(conn, session["session_id"]) + 1
        repo.insert_turn(
            conn, turn_id=turn_id, session_id=session["session_id"],
            turn_seq=turn_seq, profile_id=profile_id, config_revision=revision,
            effective_digest=resolution.source_digest(),
            sources=resolution.items, created_at=self.core.timestamp(),
        )
        body = dict(ticket) if ticket is not None else {}
        body.update({
            "turn_id": turn_id,
            "session_id": session["session_id"],
            "turn_seq": turn_seq,
            "profile_id": profile_id,
            "config_revision": revision,
            "applied_switch": applied_switch,
            "pending_seq": pending_seq,
            "effective": resolution.items,
            "effective_digest": resolution.source_digest(),
        })
        return body

    # -- US3: overlays -----------------------------------------------------
    def set_overlay(self, key: str, *, session_id: str, facet_id: str,
                    item_id: str, value: Any) -> dict[str, Any]:
        request = {"session_id": session_id, "facet_id": facet_id,
                   "item_id": item_id, "value": value}
        with self.core.db.transaction() as conn:
            prior = self._idempotent(
                conn, f"sessions.set_overlay:{session_id}", key, request,
            )
            if prior:
                return prior["response"]
            session = self._require_session(conn, session_id)
            policy = self.core.policy.get(conn, session["realm"])
            if not policy.facet_enabled_for(facet_id):
                raise ProfileError(
                    "FACET_DISABLED",
                    f"configuration facet {facet_id} is disabled on this "
                    "server realm",
                    status=409,
                ).with_item(f"{facet_id}/{item_id}")
            if not policy.override_writes_allowed(facet_id):
                raise ProfileError(
                    "OVERRIDE_WRITES_FORBIDDEN",
                    "session override writes are not allowed on this realm",
                    status=409,
                ).with_item(f"{facet_id}/{item_id}")
            reject_sensitive_keys(value)
            provider = self.core.registry.require(facet_id)
            if self.core._is_v2_provider(provider):
                facet_version = self._validate_v2_overlay_item(
                    provider, session, facet_id, item_id, value)
            else:
                facet_version = self._validate_v1_overlay_item(
                    provider, session, facet_id, item_id, value)
            reject_sensitive_keys(value)
            json_dumps(value)
            repo.upsert_overlay(
                conn, session_id=session_id, facet_id=facet_id,
                item_id=item_id, value_json=json_dumps(value),
                facet_version=facet_version,
                timestamp=self.core.timestamp(),
            )
            session = self._require_session(conn, session_id)
            response = {"session": self.session_view(session)}
            repo.idempotency_insert(
                conn, f"sessions.set_overlay:{session_id}", key,
                digest(request), 200, response, self.core.timestamp(),
            )
            return response

    def _validate_v2_overlay_item(self, provider, session, facet_id,
                                  item_id, value) -> str:
        """v2 overlay validation: descriptor lookup + applicability + schema
        + provider validate.  Unsupported refuses; unknown stores honestly
        (application-time blocks it).  Returns the stored facet_version."""
        from .contracts import Applicability, validate_value_against_schema
        descriptor = provider.descriptor()
        item = descriptor.item(item_id)
        if item is None:
            raise ProfileError(
                "FACET_VALUE_INVALID",
                f"unknown item {item_id} for facet {facet_id}",
                status=422,
            ).with_item(f"{facet_id}/{item_id}")
        applicability = provider.applicability(
            {"harness_id": session["harness_id"]})
        if applicability is Applicability.UNSUPPORTED:
            raise ProfileError(
                "FACET_NOT_APPLICABLE",
                f"facet {facet_id} does not apply to harness "
                f"{session['harness_id']}",
                status=409,
            ).with_item(f"{facet_id}/{item_id}")
        reject_sensitive_keys(value)
        try:
            validate_value_against_schema(
                dict(item.value_schema), value, where=item_id)
        except ProfileError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProfileError(
                "FACET_VALUE_INVALID", str(exc), status=422,
            ).with_item(f"{facet_id}/{item_id}") from exc
        violations = provider.validate({item_id: value}, {})
        if violations:
            raise ProfileError(
                "FACET_VALUE_INVALID", violations[0].message, status=422,
            ).with_item(f"{facet_id}/{item_id}")
        return descriptor.schema_version

    def _validate_v1_overlay_item(self, provider, session, facet_id,
                                  item_id, value) -> str:
        if not provider.applies_to(session["harness_id"]):
            raise ProfileError(
                "FACET_NOT_APPLICABLE",
                f"facet {facet_id} does not apply to harness "
                f"{session['harness_id']}",
                status=409,
            ).with_item(f"{facet_id}/{item_id}")
        if item_id not in provider.item_ids:
            raise ProfileError(
                "FACET_VALUE_INVALID",
                f"unknown item {item_id} for facet {facet_id}",
                status=422,
            ).with_item(f"{facet_id}/{item_id}")
        try:
            provider.validate_value(item_id, value)
        except ProfileError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProfileError(
                "FACET_VALUE_INVALID", str(exc), status=422,
            ).with_item(f"{facet_id}/{item_id}") from exc
        return provider.facet_version

    def clear_overlay(self, key: str, *, session_id: str, facet_id: str,
                      item_id: str) -> dict[str, Any]:
        """Per-item restore-follow; removing a missing overlay is a no-op
        (FR-019).  Clearing stays available even when new override writes
        are forbidden (G04) — it never adds or changes data."""
        request = {"session_id": session_id, "facet_id": facet_id,
                   "item_id": item_id}
        with self.core.db.transaction() as conn:
            prior = self._idempotent(
                conn, f"sessions.clear_overlay:{session_id}", key, request,
            )
            if prior:
                return prior["response"]
            self._require_session(conn, session_id)
            repo.delete_overlay(conn, session_id=session_id,
                                facet_id=facet_id, item_id=item_id)
            session = self._require_session(conn, session_id)
            response = {"session": self.session_view(session)}
            repo.idempotency_insert(
                conn, f"sessions.clear_overlay:{session_id}", key,
                digest(request), 200, response, self.core.timestamp(),
            )
            return response

    # -- reads -------------------------------------------------------------
    def session_config(self, session_id: str) -> dict[str, Any]:
        """Live projection backing US5: current vs pending vs session-only vs
        unavailable, with no permission/credential fields (FR-020).  The
        evidence projection distinguishes port-confirmed receipts from
        legacy-unverified history (PV-04)."""
        with self.core.db.read() as conn:
            session = self._require_session(conn, session_id)
            profile = self.core.require_profile(
                conn, session["current_profile_id"],
            )
            resolution = resolve_session_items(
                conn, session_id=session_id,
                profile_id=profile["profile_id"],
                harness_id=session["harness_id"],
                config_revision=int(profile["current_revision"]),
                provider_lookup=self.core.provider_lookup,
            )
            pending = None
            if session["pending_profile_id"] is not None:
                pending_row = conn.execute(
                    "SELECT profile_id, display_name, current_revision, "
                    "archived_at FROM profile_profiles WHERE profile_id=?",
                    (session["pending_profile_id"],),
                ).fetchone()
                if pending_row is not None:
                    pending = {
                        "profile_id": pending_row["profile_id"],
                        "display_name": pending_row["display_name"],
                        "revision": int(pending_row["current_revision"]),
                        "archived": pending_row["archived_at"] is not None,
                        "seq": int(session["pending_seq"]),
                    }
            current_name = profile["display_name"]
            evidence = journal.session_view(conn, session["session_uid"])
            return {
                "session_id": session_id,
                "session_uid": session["session_uid"],
                "realm": session["realm"],
                "harness_id": session["harness_id"],
                "switch_state": session["switch_state"],
                "current": {
                    "profile_id": profile["profile_id"],
                    "display_name": current_name,
                    "revision": int(profile["current_revision"]),
                },
                "pending": pending,
                "items": resolution.items,
                "unavailable": resolution.unavailable,
                "blockers": (
                    json_loads(session["blockers_json"])
                    if session["blockers_json"] else None
                ),
                "evidence": evidence,
            }

    def turns(self, session_id: str) -> list[dict[str, Any]]:
        with self.core.db.read() as conn:
            self._require_session(conn, session_id)
            rows = conn.execute(
                "SELECT turn_id, session_id, turn_seq, profile_id,"
                " config_revision, effective_digest, sources_json, created_at"
                " FROM profile_turns WHERE session_id=? ORDER BY turn_seq",
                (session_id,),
            ).fetchall()
            return [
                {
                    "turn_id": r["turn_id"],
                    "session_id": r["session_id"],
                    "turn_seq": int(r["turn_seq"]),
                    "profile_id": r["profile_id"],
                    "config_revision": int(r["config_revision"]),
                    "effective_digest": r["effective_digest"],
                    "effective": json_loads(r["sources_json"]),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]

    # -- edge case 1: restart-safe verification ----------------------------
    def verify_recovery(self, key: str, *, session_id: str) -> dict[str, Any]:
        """v2: needs_recovery sessions recover only through port evidence.

        A persisted ``pending`` was not applied (application is atomic with
        the journal) and stays pending.  A ``needs_recovery`` session with an
        unknown journal must reconcile through ``reconcile``; without a port
        it stays blocked — a database read never upgrades it (PV-04)."""
        request = {"session_id": session_id}
        with self.core.db.transaction() as conn:
            prior = self._idempotent(
                conn, f"sessions.verify_recovery:{session_id}", key, request,
            )
            if prior:
                return prior["response"]
            session = self._require_session(conn, session_id)
            state = session["switch_state"]
            verification = "unchanged"
            if state == "needs_recovery":
                entry = journal.latest_for_session(
                    conn, session["session_uid"])
                if entry is not None and entry["state"] == "unknown":
                    verification = "requires_reconcile"
                else:
                    verification = "requires_port"
            elif state == "pending":
                verification = "pending_intact_not_applied"
            session = self._require_session(conn, session_id)
            response = dict(self.session_view(session))
            response["verification"] = verification
            repo.idempotency_insert(
                conn, f"sessions.verify_recovery:{session_id}", key,
                digest(request), 200, response, self.core.timestamp(),
            )
            return response


def _intent_facts(intent: ConfigIntent) -> dict[str, Any]:
    """Digest facts of one intent — never the value payload (G15)."""
    return {
        "facet_id": intent.facet_id,
        "item_id": intent.item_id,
        "op": intent.op,
        "native_key": intent.native_key,
        "source": intent.source,
        "value_present": intent.op == "set" and intent.value is not UNSET,
    }
