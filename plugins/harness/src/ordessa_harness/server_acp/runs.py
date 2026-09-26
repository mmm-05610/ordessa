"""The channel's run record, written through the product's own ledger.

One channel run is exactly one execution: a dedicated Session and one Turn in
the existing `server_turns` table, accepted through the same
`SessionRecords` methods the product uses everywhere else.  Nothing here
creates a second execution ledger, rewrites the Turn state machine, or claims
a terminal transition the ledger itself did not make:

  * release ends the run through `finish_cancelled` with an explicit
    `terminal_reason` ("released" for a client-initiated close),
  * an unexpected Agent exit ends it through `fail_turn` with the real
    reason code, and
  * a Server restart seals it through the existing recovery path.

`channel_run_view` below is the single adaptation point where those ledger
facts are read as the client-facing run vocabulary; no other layer in this
package - and nothing on the Harness or frontend side - translates them.
"""
from __future__ import annotations

from typing import Any, Mapping

from ordessa_server.records import digest


def open_run(*, session_records, profile_records, connection_id: str,
             harness_id: str, workspace_id: str, profile_id: str,
             cwd: str) -> tuple[str, str, dict[str, Any]]:
    """Accept the Session and the single Turn that are this channel's run.

    Called only after the transport is demonstrably up, so a refusal or a
    launch failure never leaves a phantom run in the ledger; the registry's
    own zero-launch order.
    """
    binding = {"harnessId": harness_id, "projectId": workspace_id, "cwd": cwd}
    key = connection_id
    request_digest = digest({"acpChannel": True, **binding})
    _status, session = session_records.create_session(
        key=key, request_digest=request_digest,
        workspace_id=workspace_id, profile_id=profile_id,
    )
    session_id = str(session["session_id"])
    profile = profile_records.get(profile_id)
    claimed, _turn_status, body = session_records.create_turn(
        session_id=session_id, key=key, request_digest=request_digest,
        input_object_digest=digest(binding),
        expected_profile_revision=int(profile["config_revision"]),
        effective_config_object_digest=str(profile["config_object_digest"]),
    )
    if not claimed:  # the key is freshly minted; a replay here is a bug, not a race
        raise RuntimeError("ACP_CHANNEL_ACCEPT_REPLAYED")
    return session_id, str(body["turn_id"]), binding


def end_run_released(session_records, execution_id: str, *, reason: str) -> None:
    """A released run is a cancelled Turn that says why it was cancelled."""
    session_records.finish_cancelled(execution_id, terminal_reason=reason)


def end_run_failed(session_records, execution_id: str, code: str) -> None:
    """An abnormally ended run is a failed Turn carrying the real code."""
    session_records.fail_turn(execution_id, code)


#: Ledger states that mean "the run is still on"; terminal states are read as ended.
_IN_FLIGHT = {"accepted", "dispatching", "running", "capturing"}


def channel_run_view(row: Mapping[str, Any]) -> dict[str, Any]:
    """The single closed/interrupted adaptation point (contract section 4).

    The test-side vocabulary `closed`/`interrupted` is produced nowhere else.
    The ledger's own terminal facts decide: a cancelled run ended normally
    and names its reason; a failed or restart-sealed run was interrupted,
    and the stored error code is the real reason.  A completed run keeps its
    own state - a channel run never reaches it, and no ending is ever
    restated as a success claim for the work inside it.
    """
    state = str(row["state"])
    terminal_reason = row.get("terminal_reason") or None
    error_code = row.get("error_code") or None
    view: dict[str, Any] = {
        "executionId": str(row["id"]),
        "sessionId": str(row["session_id"]),
        "harnessType": str(row.get("harness_type") or ""),
        "state": state,
        "endReason": terminal_reason,
        "inFlight": state in _IN_FLIGHT,
        "stopRequestedAt": row.get("stop_requested_at"),
        "endedAt": None if state in _IN_FLIGHT else row.get("updated_at"),
    }
    if state == "cancelled":
        view["state"] = "closed"
        view["endReason"] = terminal_reason or str(error_code or "cancelled")
    elif state in {"failed", "unknown"}:
        view["state"] = "interrupted"
        view["endReason"] = terminal_reason or str(error_code or state)
    return view
