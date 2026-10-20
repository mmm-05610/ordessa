"""Cross-session safety: process-level sandbox changes need an impact set."""
from __future__ import annotations

import pytest
from _sandbox_api_helpers import codex_intent

from ordessa_sandbox_api import (
    SandboxApplyScope,
    SandboxApiError,
    SandboxErrorCode,
    SessionSlot,
    check_cross_session_impact,
)


def test_process_scope_change_with_coresident_sessions_refuses_without_impact_set():
    intent = codex_intent(scope=SandboxApplyScope.PROCESS, declared_impact_set=())
    with pytest.raises(SandboxApiError) as excinfo:
        check_cross_session_impact(
            intent,
            current_session_id="s1",
            co_resident=(SessionSlot("s1", "gen-1"), SessionSlot("s2", "gen-1")),
        )
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN


def test_process_scope_change_with_declared_impact_set_passes():
    intent = codex_intent(scope=SandboxApplyScope.PROCESS,
                          declared_impact_set=("s2",))
    check_cross_session_impact(
        intent,
        current_session_id="s1",
        co_resident=(SessionSlot("s1", "gen-1"), SessionSlot("s2", "gen-1")),
    )


def test_session_scope_change_needs_no_impact_set():
    intent = codex_intent(scope=SandboxApplyScope.SESSION)
    check_cross_session_impact(
        intent,
        current_session_id="s1",
        co_resident=(SessionSlot("s1", "gen-1"), SessionSlot("s2", "gen-1")),
    )


def test_process_scope_alone_in_process_passes():
    intent = codex_intent(scope=SandboxApplyScope.PROCESS)
    check_cross_session_impact(intent, current_session_id="s1",
                               co_resident=(SessionSlot("s1", "gen-1"),))


def test_impact_set_must_cover_every_co_resident_session():
    intent = codex_intent(scope=SandboxApplyScope.PROCESS,
                          declared_impact_set=("s2",))
    with pytest.raises(SandboxApiError) as excinfo:
        check_cross_session_impact(
            intent,
            current_session_id="s1",
            co_resident=(SessionSlot("s1", "g"), SessionSlot("s2", "g"),
                         SessionSlot("s3", "g")),
        )
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN
