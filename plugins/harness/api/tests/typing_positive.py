from typing import assert_never

from ordessa_harness_api import ApplicationResult, Intent, SetField


def intent_name(intent: Intent) -> str:
    if intent.kind == "set-field":
        assert isinstance(intent, SetField)
        return intent.kind
    if intent.kind == "reset-field":
        return intent.kind
    if intent.kind == "mount-content":
        return intent.kind
    if intent.kind == "remove-owned-content":
        return intent.kind
    if intent.kind == "bind-secret":
        return intent.kind
    if intent.kind == "invoke-action":
        return intent.kind
    assert_never(intent)


def outcome(result: ApplicationResult) -> str:
    if result.kind == "confirmed":
        return result.applied_revision
    if result.kind == "refused":
        return result.code.value
    if result.kind == "unknown":
        return result.allowed_next_action
    assert_never(result)
