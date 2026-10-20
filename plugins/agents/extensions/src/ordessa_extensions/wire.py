"""The `extensions.*` wire family: the EXT-3 diagnosability face.

Two methods, nothing more (the task needs approval state diagnosable and
revocable — not a full admin surface):

* `extensions.approvals.list` — every approval record with its state;
* `extensions.approvals.revoke` — the explicit revocation move.

No handler accepts an owner, a principal or a filesystem path from the
request; the ledger is the composition-owned instance (single source of
approval truth), so what a client reads here is what the loader gates on.
"""
from __future__ import annotations

from typing import Any, Mapping

from server_plugin_api import ServerMethodDescriptor

from .approval import ApprovalError, ApprovalLedger
from .error_families import to_server_error


def _hook_id(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise to_server_error(ApprovalError(
            "HOOK_ID_INVALID", "hookId must be a bounded string"))
    return value


def _request_id(params: Mapping[str, Any]) -> str:
    value = params.get("requestId")
    if not isinstance(value, str) or not value:
        raise to_server_error(ApprovalError(
            "INVALID_REQUEST", "requestId must be a non-empty string"))
    return value


def build_methods(ledger: ApprovalLedger,
                  *, owner: str) -> tuple[ServerMethodDescriptor, ...]:
    def approvals_list(params: Mapping[str, Any]) -> dict[str, Any]:
        _request_id(params)
        return {"records": [record.as_json()
                            for record in ledger.records()]}

    def approvals_revoke(params: Mapping[str, Any]) -> dict[str, Any]:
        _request_id(params)
        hook_id = _hook_id(params.get("hookId"))
        try:
            record = ledger.revoke(hook_id)
        except ApprovalError as exc:
            raise to_server_error(exc) from exc
        return {"record": record.as_json()}

    return (
        ServerMethodDescriptor(
            method_id="extensions.approvals.list",
            required_params=frozenset({"requestId"}),
            optional_params=frozenset(),
            handler=approvals_list, owner=owner, availability=None,
        ),
        ServerMethodDescriptor(
            method_id="extensions.approvals.revoke",
            required_params=frozenset({"requestId", "hookId"}),
            optional_params=frozenset(),
            handler=approvals_revoke, owner=owner, availability=None,
        ),
    )


__all__ = ["build_methods"]
