"""T05 — cross-session safety (US3 / FR-06).

Two same-brand sessions with different intents sharing one process-level native
sandbox must not let one compile silently change the other's isolation. Unless
the intent declares an impact set covering every co-resident session, the
process-scoped compile refuses with `SANDBOX_EFFECT_UNKNOWN` and emits nothing
(data-model.md 多会话/变更; harness-adapters.md 横向反例 "两个会话不同上限").
"""
from __future__ import annotations

from _sandbox_adapters_helpers import (
    CODEX_TARGET,
    authorized_facts,
    codex_intent,
    permissive_ceiling,
    target_handle,
)

from ordessa_sandbox_api import SandboxApplyScope, SessionSlot
from ordessa_sandbox_adapters import CompileRefusal, CompiledIntent, CodexSandboxAdapter

CEILING = (permissive_ceiling(),)


def _co_resident():
    return authorized_facts(current_session_id="s-a",
                            co_resident_sessions=(SessionSlot(session_id="s-a"),
                                                  SessionSlot(session_id="s-b")))


def test_process_scope_undeclared_impact_refused():
    adapter = CodexSandboxAdapter()
    intent = codex_intent(scope=SandboxApplyScope.PROCESS, declared_impact_set=())
    result = adapter.compile(intent, target_handle(CODEX_TARGET), CEILING, authorized=_co_resident())
    assert isinstance(result, CompileRefusal)
    assert result.code.value == "SANDBOX_EFFECT_UNKNOWN"
    # it never emits an intent that silently affects the other session
    assert result.emitted_intents == ()


def test_process_scope_with_declared_impact_set_compiles():
    adapter = CodexSandboxAdapter()
    intent = codex_intent(scope=SandboxApplyScope.PROCESS,
                          declared_impact_set=("s-b",))
    result = adapter.compile(intent, target_handle(CODEX_TARGET), CEILING, authorized=_co_resident())
    assert isinstance(result, CompiledIntent)


def test_session_scope_ignores_co_residency():
    adapter = CodexSandboxAdapter()
    result = adapter.compile(codex_intent(scope=SandboxApplyScope.SESSION),
                             target_handle(CODEX_TARGET), CEILING, authorized=_co_resident())
    assert isinstance(result, CompiledIntent)


def test_no_co_resident_sessions_compiles_at_process_scope():
    adapter = CodexSandboxAdapter()
    solo = authorized_facts(current_session_id="s-a",
                            co_resident_sessions=(SessionSlot(session_id="s-a"),))
    intent = codex_intent(scope=SandboxApplyScope.PROCESS)
    result = adapter.compile(intent, target_handle(CODEX_TARGET), CEILING, authorized=solo)
    assert isinstance(result, CompiledIntent)
