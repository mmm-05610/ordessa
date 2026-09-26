"""Work Order 135: the typed code must reach the *live* leg, not just the low seam.

Order 120 fixed the credential failure at two pure seams (``SecretLocatorUnavailable``
carries ``code = CREDENTIAL_NOT_AVAILABLE``; ``_safe_code`` reads it) and its gates
passed. A's real-machine recompute still read the generic ``EXECUTION_FAILED``:
the exception that actually reaches the user first travels through the Work Core
dispatch wrap (``work_core/services.py``), which used to *stringify* the cause into
``DispatchAmbiguous`` and drop the code - so 120's gate only ever walked one leg.

These gates drive the whole decision path the transcript takes, and each is fed the
exception produced by the *real* ``dispatch_execution`` (not a hand-built typed error):

    accept -> dispatch_execution -> [DispatchAmbiguous.code] -> _safe_code (as
    sidecar_backend:287 calls it) -> wire.execution.state projection -> reason.

Counterexample gates prove the code-attach is load-bearing: a stringify-only wrap
(the pre-fix shape) and a genuinely unknown failure both still land on the generic
reason, and no secret content ever reaches the leg.
"""
from __future__ import annotations

import pytest

from pacthold.resource_contracts import PromptFragmentV1
from ordessa_server_compat.execution.sidecar_backend import _safe_code
from ordessa_server.wire.projection import _event_body
from pacthold.storage.secrets import SecretLocatorUnavailable
from pacthold.work_core.errors import DispatchAmbiguous
from pacthold.work_core.models import Ref, RefType
from pacthold.work_core.registry import ExtensionRegistry, ProviderDescriptor
from pacthold.work_core.repository import CoreRepository
from pacthold.work_core.services import ExecutionService, WorkService


class _FailingStartProvider:
    """A provider whose native start raises the given error (mirrors port_factory,
    which reads the credential secret and re-raises a wrapped failure)."""

    def __init__(self, error: BaseException) -> None:
        self._error = error
        self.started: list = []

    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor("fake-execution", "Fake Execution", "test")

    def capabilities(self) -> dict[str, str]:
        return {"start": "supported", "observe": "supported"}

    def input_limits(self) -> dict[str, tuple[int, int]]:
        return {PromptFragmentV1.contract_id: (1, 1)}

    def start(self, request):
        self.started.append(request)
        raise self._error

    def observe(self, native_ref):
        return native_ref


class _PromptResource:
    supported_contract_ids = frozenset({PromptFragmentV1.contract_id})

    def resolve(self, contract_id, ref):
        return PromptFragmentV1(ref.native_id, "content", "sha256:" + ref.native_id)


def _dispatch_raised(tmp_agent_box_home, error: BaseException) -> BaseException:
    """Drive the real dispatch leg and return the exception it raises."""
    repo = CoreRepository()
    work = WorkService(repo).create_work("typed-code-live-leg")
    service = ExecutionService(repo)
    execution = service.create_execution(
        work.id, "fake-execution", responsibility_intent="start fails",
    )
    registry = ExtensionRegistry()
    registry.register_execution_provider(_FailingStartProvider(error))
    registry.register_resource_provider("fake-resource", _PromptResource())
    inputs = ((PromptFragmentV1.contract_id, Ref(RefType.ARTIFACT, "fake-resource", "p1")),)
    with pytest.raises(DispatchAmbiguous) as raised:
        service.dispatch_execution(execution.id, inputs, registry, "dispatch-live-leg")
    return raised.value


def _execution_state_reason(error_code: str) -> str:
    """Project a failed turn to the wire event the client reads (execution.state)."""
    body = _event_body(
        "execution.state",
        {"session_id": "sess-1", "turn_id": "turn-1"},
        {"state": "failed", "error_code": error_code},
    )
    return body["reason"]


def test_missing_credential_code_reaches_execution_state(tmp_agent_box_home):
    # The exception the real dispatch leg raises carries the code *structurally*.
    raised = _dispatch_raised(
        tmp_agent_box_home, SecretLocatorUnavailable("credential_e0879"),
    )
    assert getattr(raised, "code", None) == "CREDENTIAL_NOT_AVAILABLE"
    # sidecar_backend:287 maps it with _safe_code ...
    code = _safe_code(raised)
    assert code == "CREDENTIAL_NOT_AVAILABLE"
    # ... and the wire projection puts it in the user-visible reason.
    assert _execution_state_reason(code) == "CREDENTIAL_NOT_AVAILABLE"


def test_port_factory_converted_runtime_error_reaches_execution_state(tmp_agent_box_home):
    # The exact shape A's log shows: RuntimeError("CREDENTIAL_NOT_AVAILABLE").
    raised = _dispatch_raised(
        tmp_agent_box_home, RuntimeError("CREDENTIAL_NOT_AVAILABLE"),
    )
    assert _execution_state_reason(_safe_code(raised)) == "CREDENTIAL_NOT_AVAILABLE"


def test_counterexample_stringify_only_wrap_still_gives_generic_reason(tmp_agent_box_home):
    # The pre-fix wrap: a Dispatch that only carries the code as message text and
    # no structural .code. This is what a revert produces; the leg must go generic.
    legacy = DispatchAmbiguous(
        "Execution Dispatch is ambiguous for exec-1: RuntimeError: CREDENTIAL_NOT_AVAILABLE"
    )
    assert not hasattr(legacy, "code")
    assert _safe_code(legacy) == "EXECUTION_FAILED"


def test_truly_unknown_failure_stays_generic(tmp_agent_box_home):
    # A failure with no typed code anywhere: a sentence message. Must NOT be renamed.
    raised = _dispatch_raised(
        tmp_agent_box_home, RuntimeError("worker vanished at 03:14 during spawn"),
    )
    assert getattr(raised, "code", None) is None
    assert _execution_state_reason(_safe_code(raised)) == "EXECUTION_FAILED"


def test_leg_carries_zero_credential_content(tmp_agent_box_home):
    # Even the missing-locator message names the non-sensitive id, never a secret.
    raised = _dispatch_raised(
        tmp_agent_box_home, SecretLocatorUnavailable("credential_e0879"),
    )
    rendered = f"{raised} {getattr(raised, 'code', '')}"
    assert "credential_e0879" in rendered          # id is fine
    assert "secret-bytes" not in rendered          # no secret value
    assert _execution_state_reason(_safe_code(raised)) == "CREDENTIAL_NOT_AVAILABLE"
