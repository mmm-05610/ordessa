"""Order 65 C: the delegation service behind the two MCP tools.

The bridge (a stdio MCP server the parent harness starts) forwards
`list_subagents` / `run_subagent` here, and this service answers from the same
records the rest of the Server uses:

* **list** resolves the live roster (authorized edges only) and the two tool
  definitions, including the roster summary embedded in the description;
* **run** validates the call (`validate_run_arguments` - narrowing-only,
  bounded, authorized), resolves `task_id` or a fresh child session, creates a
  **normal turn** for the child Profile, links it to the parent turn
  (`parent_turn_id`), dispatches it, waits within the ten-minute bound, and
  returns the child's **bounded final message** plus a `task_id` handle;
* **cancellation propagates**: both stop entry points cascade the request to
  the child turns the ledger links to the stopped turn (see
  `SessionService.cancel_descendants`);
* **usage attribution** is the link: the child's own usage columns stay on the
  child turn and the parent's roll-up is the join - nothing is copied between
  turns, and nothing is invented.

Cross-family continuation is refused (a native session belongs to its family's
store); an unknown handle is refused; nothing here guesses.
"""
from __future__ import annotations

import json
import time
from typing import Any, Iterable, Mapping, Sequence

from ordessa_server.errors import ServerError
# INC1c c-1B/c-2 (E2): the product-domain reach of this module is declared as
# one top-level block only - hidden function-local imports of the same domain
# are gone (the `_merged_posture` leg). The roster semantics and the posture
# resolver stay produced here at the creation point (adjudicated B案), now
# anchored the same way the Session leg anchors (INC1c-release裁①).
from ordessa_server_compat.profiles.permissions import resolve_all
from ordessa_server_compat.profiles.subagents import (
    DEFAULT_TIMEOUT_SECONDS,
    DelegationError,
    MAX_ROSTER_ENTRIES,
    check_cycle,
    grant_edges,
    has_delegation,
    inline_available,
    resolve_roster,
    tool_definitions,
    validate_run_arguments,
)

#: The final message is bounded: the subagent's summary, not its transcript.
MAX_SUMMARY_CHARS = 4096
#: Errors in the child turn become a typed tool result, never raw stdout.
TERMINAL_OK = "completed"


def _iter_model_ids(value: Any) -> Iterable[str]:
    """Every ``modelId`` a child's model-control value names (provider/model
    references may nest); a bare string is taken as a single id."""
    if isinstance(value, Mapping):
        model_id = value.get("modelId")
        if isinstance(model_id, str):
            yield model_id
        for nested in value.values():
            yield from _iter_model_ids(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_model_ids(nested)


def _child_permission_ceiling(child_profile: Mapping[str, Any]) -> list[str]:
    """The presets a caller may still *narrow* the child to (order 60's rule).

    ``plan`` is the narrow preset and ``default`` is wider; a child already on
    ``plan`` cannot be asked to run at ``default``, while a child on ``default``
    (or any wider/unset preset) may be run at either. This is the source the
    production path feeds into ``validate_run_arguments``' ``child_limits`` -
    without it the ``SUBAGENT_PERMISSION_WIDENED`` branch is structurally dead.
    """
    preset = str(child_profile.get("permission_preset") or "default")
    return ["plan"] if preset == "plan" else ["default", "plan"]


class DelegationService:
    def __init__(
        self, *, records, profiles, sessions, execution=None, registry=None,
        data_root=None, objects=None,
    ) -> None:
        self.records = records            # SessionRecords (the ledger layer)
        self.profiles = profiles
        self.sessions = sessions          # SessionService (creates Sessions)
        self.execution = execution        # TurnExecutionPort (may be None)
        self.registry = registry
        self.data_root = data_root
        self.objects = objects

    # -- shared resolution --------------------------------------------------

    def list_for(self, *, parent_profile_id: str) -> dict[str, Any]:
        """The two tools' definitions and the live roster for one parent."""
        edges = grant_edges(self.profiles.subagent_grants())
        if not has_delegation(edges, parent_profile_id):
            return {"tools": [], "roster": []}
        profiles = self.profiles.list(include_archived=False)
        roster = resolve_roster(
            parent_id=parent_profile_id, edges=edges, profiles=profiles,
            workspace_of=self._workspace_map(profiles),
            availability=self._availability_map(profiles))
        return {
            "tools": tool_definitions(roster=roster),
            "roster": roster[:MAX_ROSTER_ENTRIES],
        }

    # -- run ----------------------------------------------------------------

    def run(
        self, *, parent_turn_id: str, parent_profile_id: str,
        arguments: Mapping[str, Any], calls_this_turn: int = 0,
    ) -> dict[str, Any]:
        edges = grant_edges(self.profiles.subagent_grants())
        if not has_delegation(edges, parent_profile_id):
            raise DelegationError(
                "SUBAGENT_NOT_AUTHORIZED", "this role has no authorized subagents")
        profiles = self.profiles.list(include_archived=False)
        # Order 138 (`65:83`, ops `R-0070 ①`): the delegation act is scoped to the
        # *parent turn's* workspace. A fresh child lands there - never wherever the
        # child profile last happened to run - and only children that operate in the
        # same workspace are candidates for this turn (a cross-workspace child is not
        # offered, so requesting it is an explicit `SUBAGENT_NOT_AUTHORIZED`, not a
        # silent landing in another project).
        parent_workspace_id = self.records.get_turn_context(parent_turn_id)["workspace_id"]
        roster = resolve_roster(parent_id=parent_profile_id, edges=edges, profiles=profiles,
                                workspace_of=self._workspace_map(profiles),
                                availability=self._availability_map(profiles))
        roster = [entry for entry in roster
                  if entry.get("workspace") == parent_workspace_id]
        # Order 136: `child_limits` must be sourced from the *child's own* rules
        # at the production call site. It used to be omitted entirely, which made
        # `validate_run_arguments`' narrowing checks structurally dead (an
        # over-wide preset or a different model slipped through as ACCEPTED).
        child_limits = self._child_limits_for_request(arguments, roster=roster)
        try:
            validated = validate_run_arguments(arguments, roster=roster, child_limits=child_limits)
        except DelegationError:
            raise
        if calls_this_turn >= 4:
            raise DelegationError(
                "SUBAGENT_TURNS_EXCEEDED", "at most 4 subagent calls are allowed per turn")
        chosen = next(
            entry for entry in roster if entry["name"] == validated["subagent"])
        if not chosen["available"]:
            raise DelegationError(
                "SUBAGENT_UNAVAILABLE",
                f"the subagent is not available: {chosen['reason']}",
                available=[entry["name"] for entry in roster],
            )
        child_profile = self.profiles.get(chosen["profileId"])
        if bool(child_profile.get("archived_at")):
            raise ServerError("PROFILE_ARCHIVED", "Profile is archived", status=409)
        # Order 146 (`AUD-B-031`, `65:102` "children run through the existing
        # execution chain"): the existing chain's accept/create_turn gate refuses a
        # `recovery_pending` Profile with a 409 `PROFILE_RECOVERY_REQUIRED`, but the
        # delegation path used to bypass it (it inserts the child turn itself). A
        # profile with unresolved recovery evidence is therefore *unavailable* to a
        # delegated run too - typed, before any child session or turn is created.
        if bool(child_profile.get("recovery_pending")):
            raise DelegationError(
                "SUBAGENT_UNAVAILABLE",
                "the subagent Profile has unresolved recovery evidence; "
                "restart reconciliation is required before it can run",
                available=[entry["name"] for entry in roster],
            )

        # The ancestry is read out of the ledger, never handed over by the
        # caller: the bridge knows only its own turn, and a self-reported chain
        # is no chain (order 086 stage 3 - the rule below was written down and
        # could not see the calls it was meant to refuse).
        check_cycle([*self.records.turn_ancestry_profile_ids(parent_turn_id),
                     chosen["profileId"]])

        # Whether the child itself holds grants is what decides if it may hand
        # work on - recorded on the result so the parent can relay it honestly.
        child_may_delegate = has_delegation(edges, chosen["profileId"])

        session_id, native_id, resumed = self._resolve_child_session(
            child_profile=child_profile, chosen=chosen, validated=validated,
            parent_workspace_id=parent_workspace_id)

        # Create the child turn as a normal turn, linked to the parent.
        # a-3 K3'-E: the parent's posture原料 now travels through the parent
        # Turn's frozen effective configuration instead of re-reading the
        # parent Profile's live row - the second derivation path is gone.
        merged_posture = self._merged_posture(
            parent_turn_id=parent_turn_id, parent_profile_id=parent_profile_id,
            child_profile=child_profile)
        turn_id = self._create_child_turn(
            session_id=session_id, child_profile=child_profile,
            parent_turn_id=parent_turn_id, prompt=validated["prompt"],
            model=validated.get("model"), posture=merged_posture,
        )
        if self.execution is None:
            raise ServerError(
                "EXECUTION_CAPABILITY_UNAVAILABLE", "no execution port is composed",
                status=503,
            )
        self.execution.accept(turn_id)
        outcome = self._await_terminal(
            session_id=session_id, turn_id=turn_id, timeout=validated["timeout"])
        # The continuable handle is the child session's own native id, read
        # after the turn ran: a fresh session only has one once it has been
        # opened for real (`native_id` covers the continuation case).
        session_after = self.records.get_session(session_id)
        checkpoint = session_after.get("checkpoint") or {}
        handle = checkpoint.get("native_id") or native_id
        summary = self._final_message(turn_id=turn_id)
        usage = self._usage_of(turn_id)
        return {
            "subagent": chosen["name"],
            "task_id": handle,
            "resumed": resumed,
            "state": outcome["state"],
            "summary": summary,
            "errorCode": outcome.get("error_code"),
            "canDelegate": child_may_delegate,
            "turnId": turn_id,
            "sessionId": session_id,
            "usage": usage,
        }

    # -- internals ----------------------------------------------------------

    def _child_limits_for_request(
        self, arguments: Mapping[str, Any], *, roster: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any] | None:
        """Source the narrowing ceiling for the *requested* child.

        ``validate_run_arguments`` is still the authorization gate: an unknown or
        unauthorized name resolves to no child here and is refused there for that
        reason (never as a widening), so sourcing limits cannot leak a child the
        caller may not call.
        """
        name = arguments.get("subagent")
        entry = next((item for item in roster if item["name"] == name), None)
        if entry is None:
            return None
        return self._child_limits(self.profiles.get(entry["profileId"]))

    def _child_limits(self, child_profile: Mapping[str, Any]) -> dict[str, Any]:
        limits: dict[str, Any] = {"permissions": _child_permission_ceiling(child_profile)}
        models = self._child_model_ids(child_profile)
        if models:
            limits["models"] = models
        return limits

    def _child_model_ids(self, child_profile: Mapping[str, Any]) -> list[str] | None:
        """The model ids the child pins in its own model slot, or ``None``.

        Checked only when the family declares a model slot and the child actually
        references models there; otherwise the dimension stays unchecked so a
        child that declares no models is never rejected for it. This mirrors the
        "optional arguments only narrow" rule without over-reaching into provider
        model-set resolution.
        """
        registry = self.registry
        if registry is None or self.objects is None:
            return None
        try:
            descriptor = registry.get(str(child_profile.get("harness_type")))
            control_id = getattr(descriptor, "model_control_id", None) if descriptor else None
            digest = child_profile.get("config_object_digest")
            if not control_id or not digest:
                return None
            config = json.loads(self.objects.read(str(digest)))
            value = (config.get("configuration") or {}).get(control_id) if isinstance(config, Mapping) else None
            ids = sorted({model_id for model_id in _iter_model_ids(value) if isinstance(model_id, str)})
            return ids or None
        except Exception:  # a limit that cannot be sourced stays unchecked, never fatal
            return None

    def _resolve_child_session(
        self, *, child_profile: Mapping[str, Any], chosen: Mapping[str, Any],
        validated: Mapping[str, Any], parent_workspace_id: str,
    ) -> tuple[str, str | None, bool]:
        task_id = validated.get("task_id")
        if task_id is None:
            # Order 138: a fresh child runs in the *parent turn's* workspace, not the
            # child profile's last-touched one (which let a conversation about project A
            # write into project B and drift the landing point).
            workspace_id = parent_workspace_id
            # A unique key per call: two concurrent subagent calls in the same
            # millisecond must not collide on the idempotency record.
            import uuid as _uuid


            session = self.sessions.create_session(
                f"subagent-{_uuid.uuid4().hex}",
                {"workspace_id": workspace_id, "profile_id": chosen["profileId"]},
            )[1]
            return session["session_id"], None, False
        # Continuation: the handle is a native session id of a *specific, authorized*
        # child session - not "any session of the same family".
        with self.records.database.read() as conn:
            rows = conn.execute(
                "SELECT id,profile_id FROM server_sessions "
                "WHERE checkpoint_native_id=?", (task_id,),
            ).fetchall()
        if not rows:
            raise DelegationError(
                "SUBAGENT_TASK_UNKNOWN", "no subagent session carries that task_id")
        if len(rows) > 1:
            # Order 139 (AUD-B-021): `checkpoint_native_id` has no unique index, so the
            # same handle can resolve to several sessions and `fetchone()` would land on
            # whichever row the ledger happens to return first. That is an
            # unreproducible landing point; fail deterministically instead of choosing.
            raise DelegationError(
                "SUBAGENT_NOT_AUTHORIZED",
                "this task_id resolves to more than one session; the continuation is ambiguous")
        row = rows[0]
        session = self.records.get_session(str(row["id"]))
        owner = self.profiles.get(str(session["profile_id"]))
        if str(owner["harness_type"]) != str(child_profile["harness_type"]):
            # A native session lives in its family's store: continuing it from
            # another family is impossible, and silently opening a fresh one
            # would pretend continuity.
            raise DelegationError(
                "SUBAGENT_TASK_FAMILY_MISMATCH",
                "a subagent session can only be continued within its own family",
            )
        if str(session["profile_id"]) != str(chosen["profileId"]):
            # Order 139: a parent only authorized to call child C must not resume the
            # native handle of a different profile D just because D is the same family.
            # The session must belong to the child this run actually selected (the same
            # roster the grant was read from), so authorization and continuation are one
            # fact. Reuses SUBAGENT_NOT_AUTHORIZED - no new code, no contract change.
            raise DelegationError(
                "SUBAGENT_NOT_AUTHORIZED",
                "that task_id is not a session of the authorized subagent for this call",
            )
        return str(row["id"]), task_id, True

    def _child_workspace(self, profile_id: str) -> str | None:
        """The workspace a Profile currently operates in: its last-touched session."""
        with self.records.database.read() as conn:
            row = conn.execute(
                "SELECT s.workspace_id FROM server_sessions s "
                "WHERE s.profile_id=? ORDER BY s.updated_at DESC LIMIT 1",
                (profile_id,),
            ).fetchone()
        return str(row["workspace_id"]) if row is not None else None

    def _workspace_map(self, profiles: Sequence[Mapping[str, Any]]) -> dict[str, str | None]:
        """profile id -> current workspace, for the roster's `workspace` field."""
        return {str(profile["id"]): self._child_workspace(str(profile["id"]))
                for profile in profiles}

    def _availability_map(self, profiles: Sequence[Mapping[str, Any]]) -> dict[str, str]:
        """profile id -> typed unavailability reason, for the roster's `available`.

        Order 146 (`AUD-B-032`): `availability` used to be a parameter no caller
        supplied, so every entry read `available=true` (the "unavailable" dimension
        was decorative). Feed the decidable child facts here so the roster's
        availability - and `run`'s `SUBAGENT_UNAVAILABLE` gate behind it - are real.
        """
        reasons: dict[str, str] = {}
        registry = self.registry
        for profile in profiles:
            profile_id = str(profile["id"])
            if profile.get("archived_at"):
                reasons[profile_id] = "PROFILE_ARCHIVED"
            elif bool(profile.get("recovery_pending")):
                reasons[profile_id] = "PROFILE_RECOVERY_REQUIRED"
            elif registry is not None and str(profile.get("harness_type")) not in registry:
                reasons[profile_id] = "HARNESS_UNAVAILABLE"
        return reasons

    def _shared_workspace_id(self, child_profile: Mapping[str, Any]) -> str:
        workspace_id = self._child_workspace(str(child_profile["id"]))
        if workspace_id is not None:
            return workspace_id
        raise DelegationError(
            "SUBAGENT_WORKSPACE_UNKNOWN",
            "the subagent Profile has no workspace to run in yet",
        )

    def _merged_posture(
        self, *, parent_turn_id: str, parent_profile_id: str,
        child_profile: Mapping[str, Any],
    ) -> dict[str, Any]:
        """The child's posture, narrowed by the parent's prohibitions.

        Only the parent's `deny`s (and its neutral limits, which are those
        `deny`s) travel: the child's own allow/ask set stays the child's, so a
        delegation can tighten a key but never widen one. The result is frozen
        into the child turn's effective configuration, exactly where the
        runtime reads a turn's posture from.

        a-3 K3'-E: the parent's own posture is read from the parent Turn's
        **frozen** effective configuration (top-level `permissions`, frozen
        once at acceptance), never re-derived from the parent Profile's live
        row. A parent Turn that carries no such section (a turn accepted before
        the section existed) is refused typed instead of silently falling back
        to a live read.
        """
        def posture_of(row: Mapping[str, Any]) -> dict[str, Any]:
            raw = row.get("permission_rules_json")
            rules = json.loads(raw) if raw else []
            return resolve_all(rules, preset=str(row.get("permission_preset") or "default"))

        parent_context = self.records.get_turn_context(parent_turn_id)
        parent_posture = self._frozen_posture(parent_context)
        if parent_posture is None:
            raise ServerError(
                "PROFILE_CONFIGURATION_INVALID",
                "the parent Turn has no frozen permission posture to narrow the child",
                status=409,
            )
        child = self.profiles.get(str(child_profile["id"]))
        child_posture = posture_of(child)
        merged_keys = {
            key: "deny" if parent_posture.get("keys", {}).get(key) == "deny" else action
            for key, action in child_posture["keys"].items()
        }
        return {"preset": child_posture["preset"], "keys": merged_keys,
                "inheritedFrom": parent_profile_id}

    def _frozen_posture(self, turn_context: Mapping[str, Any]) -> dict[str, Any] | None:
        """The `permissions` section of a Turn's frozen effective configuration,
        or `None` when the turn (or this composition) carries none."""
        digest = turn_context.get("effective_config_object_digest")
        if self.objects is None or not isinstance(digest, str) or not digest.strip():
            return None
        value = json.loads(self.objects.read(digest))
        if not isinstance(value, Mapping):
            return None
        posture = value.get("permissions")
        return dict(posture) if isinstance(posture, Mapping) else None

    def _create_child_turn(
        self, *, session_id: str, child_profile: Mapping[str, Any],
        parent_turn_id: str, prompt: str, model: str | None,
        posture: Mapping[str, Any] | None = None,
    ) -> str:
        import json

        from ordessa_server.ids import now, opaque_id

        turn_id = opaque_id("turn")
        timestamp = now()
        # INC1c c-1B (B案 anchoring): the revision the frozen assembly above was
        # computed from, re-checked inside the acceptance transaction below.
        expected_revision = int(child_profile["config_revision"])
        # The turn's input is a real published object (the delegated prompt),
        # and its effective configuration starts from the child Profile's own
        # frozen configuration - the model slot and every other control are the
        # child's - with the merged permission posture on top.
        input_digest = None
        effective_digest: str | None = None
        if self.objects is not None:
            input_digest = self.objects.publish(json.dumps(
                {"schema_version": 1, "message": {"text": prompt}},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode()).digest
            child_value = json.loads(self.objects.read(str(child_profile["config_object_digest"])))
            if not isinstance(child_value, dict):
                child_value = {}
            child_value = dict(child_value)
            child_value.setdefault("schema_version", 1)
            child_value["harness_type"] = str(child_profile["harness_type"])
            if posture is not None:
                child_value["permissions"] = dict(posture)
            effective_digest = self.objects.publish(json.dumps(
                child_value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode()).digest
        with self.records.database.transaction() as conn:
            # Order 146 (`AUD-B-034`): the exclusive-home concurrency lock is one of
            # the existing chain's gates; the delegation path used to insert the child
            # turn without it, so a profile that declared an exclusive home could get
            # two active turns (one per session). Reuse the same check, atomically.
            self.records._refuse_exclusive_home_concurrency(conn, child_profile)
            # INC1c c-1B: Session-isomorphic same-transaction anchor - a live-row
            # edit between the frozen assembly above and this INSERT is refused
            # with the same typed conflict the Session leg raises (never a
            # silently re-read live configuration).
            anchor = conn.execute(
                "SELECT config_revision FROM server_profiles WHERE id=?",
                (child_profile["id"],),
            ).fetchone()
            if anchor is None:
                raise ServerError("PROFILE_NOT_FOUND", "Profile was not found", status=404)
            if int(anchor["config_revision"]) != expected_revision:
                raise ServerError(
                    "PROFILE_REVISION_CONFLICT",
                    "Profile revision changed before delegated Turn creation",
                    status=409,
                )
            # a-3 key cell (race ruling §一.2①, E sole writer): the child row
            # mints its K1.1-family key at creation - `execution:{turn_id}`,
            # the same derivation as the Session write points - so the
            # acceptance consumer reads it instead of refusing an identity-less
            # row. The column arrives with S's K1.1 schema v21: on this single
            # leg the INSERT is a declared confluence red until the merge lands
            # S's six first.
            try:
                conn.execute(
                    "INSERT INTO server_turns(id,session_id,profile_id,profile_revision,"
                    "native_generation,state,capture_state,cleanup_state,input_object_digest,"
                    "effective_config_object_digest,execution_key,parent_turn_id,"
                    "captured_profile_revision,created_at,updated_at) "
                    "VALUES (?,?,?,1,0,'accepted','pending','pending',?,?,?,?,?,?,?)",
                    (turn_id, session_id, child_profile["id"], input_digest,
                     effective_digest, f"execution:{turn_id}", parent_turn_id,
                     expected_revision,
                     timestamp, timestamp),
                )
            except Exception as exc:
                # Order 146 (`AUD-B-035`, `65:36` "failure is a typed result"): a
                # same-session `task_id` retry hits the per-session active-turn index
                # exactly like the existing chain, so translate the raw
                # `IntegrityError` (which names table/column) into the same product
                # code instead of leaking it to the wire.
                if "UNIQUE constraint failed" in str(exc):
                    raise ServerError(
                        "TURN_CONCURRENCY_CONFLICT",
                        "the subagent session already has an active Turn",
                        status=409,
                    ) from exc
                raise
            conn.execute(
                "UPDATE server_sessions SET status='active',version=version+1,"
                "updated_at=? WHERE id=?", (timestamp, session_id),
            )
            self.records._append_session_event(
                conn, session_id, turn_id, "turn.accepted",
                {"state": "accepted", "parent_turn_id": parent_turn_id,
                 "model": model, "prompt_preview": prompt[:200]},
            )
        return turn_id

    def _await_terminal(self, *, session_id: str, turn_id: str, timeout: int) -> dict[str, Any]:
        deadline = time.monotonic() + min(timeout, DEFAULT_TIMEOUT_SECONDS)
        while time.monotonic() < deadline:
            # Order 146 (`AUD-B-029`): read this turn's own state, not a scan of a
            # session snapshot whose turn list is windowed to the first 200 rows.
            turn = self.records.get_turn_context(turn_id)
            if turn["state"] in {"completed", "failed", "cancelled", "unknown"}:
                return dict(turn)
            time.sleep(0.05)
        # Order 141 (`:81` resource boundary must really stop, `:90` no silent
        # degrade): time-out was not a stop entry point, so the child kept running
        # (and spending) while the refusal carried nothing to locate it. Stop the
        # child first, keep the typed code, and put the locatable handle plus the
        # usage actually incurred into the message the caller gets back.
        usage_so_far = self._usage_of(turn_id)
        self.sessions.cancel_turn(turn_id, f"subagent-timeout:{turn_id}")
        handle = self._child_native_handle(session_id)
        detail = (
            f"the subagent did not finish within {timeout}s; the child turn was stopped. "
            f"turnId={turn_id}; task_id={handle or 'none'}; "
            f"usage so far: {usage_so_far if usage_so_far else 'none recorded'}"
        )
        raise DelegationError("SUBAGENT_TIMEOUT", detail)

    def _child_native_handle(self, session_id: str) -> str | None:
        checkpoint = self.records.get_session(session_id).get("checkpoint") or {}
        return checkpoint.get("native_id")


    def _final_message(self, *, turn_id: str) -> str:
        # Order 146 (`AUD-B-029`): read the turn's own message deltas, bounded by
        # the declared summary-character cap - not a session snapshot's first 200
        # event rows (which truncated the newest content and returned '' on
        # continuation, so the parent could not tell "the child said nothing" from
        # "we dropped what it said").
        summary = "".join(self.records.turn_message_deltas(turn_id))
        if len(summary) > MAX_SUMMARY_CHARS:
            summary = summary[:MAX_SUMMARY_CHARS] + "…"
        return summary

    def _usage_of(self, turn_id: str) -> dict[str, Any] | None:
        with self.records.database.read() as conn:
            row = conn.execute(
                "SELECT usage_input_tokens,usage_output_tokens,usage_total_tokens,"
                "usage_source FROM server_turns WHERE id=?", (turn_id,),
            ).fetchone()
        if row is None or row["usage_source"] is None:
            return None
        return {
            "inputTokens": row["usage_input_tokens"],
            "outputTokens": row["usage_output_tokens"],
            "totalTokens": row["usage_total_tokens"],
            "usageSource": row["usage_source"],
        }
