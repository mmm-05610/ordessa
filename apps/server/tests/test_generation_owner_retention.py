"""The generation wrapper retains its original owner until cleanup confirms."""
import builtins
import importlib.util
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
import time as _time

import pytest


ROOT = Path(__file__).resolve().parents[3]
_OPERATOR_PATH = ROOT / "tooling/checks/server_product/probe-work-package-generation.py"
_OPERATOR_SPEC = importlib.util.spec_from_file_location(
    "generation_owner_retention_operator", _OPERATOR_PATH)
_OPERATOR = importlib.util.module_from_spec(_OPERATOR_SPEC)
_OPERATOR_SPEC.loader.exec_module(_OPERATOR)


class _TestScopeEnd(BaseException):
    """Test-only timer escape after production catches SystemExit."""


def _install_test_escape_timer(monkeypatch):
    """Bound a retained test worker without adding a production escape switch."""
    def escape_after_catch(_seconds):
        raise _TestScopeEnd()

    monkeypatch.setattr(_OPERATOR, "time", SimpleNamespace(
        time=_time.time, sleep=escape_after_catch))


class _Owner:
    def __init__(self):
        self.authorization_calls = 0
        self.token = object()

    def authorization(self):
        self.authorization_calls += 1
        return self.token


class _Units:
    def __init__(self, unit):
        self.unit = unit
        self.list_calls = 0

    def list(self):
        self.list_calls += 1
        return [self.unit]


class _Runtime:
    def __init__(self, unit, *, stop_mode="complete"):
        self.unit_execution_owner = _Owner()
        self.units = _Units(unit)
        self.stop_calls = 0
        self.stopped = False
        self.stop_state = "idle"
        self.stop_mode = stop_mode

    def stop(self):
        self.stop_calls += 1
        if self.stop_mode == "raise":
            self.stop_state = "pending"
            raise RuntimeError("controlled runtime stop is unresolved")
        if self.stop_mode == "pending":
            self.stop_state = "pending"
            return
        self.stop_state = "completed"
        self.stopped = True


class _Unit:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.close_calls = []
        self.prompt_calls = 0

    def close(self, authorization):
        self.close_calls.append(authorization)
        if not self.outcomes:
            raise AssertionError("unexpected additional Unit.close call")
        outcome = self.outcomes.pop(0)
        return dict(outcome)


def _terminal_test_state(state, monkeypatch, *, unresolved=True):
    _install_test_escape_timer(monkeypatch)
    unit = _Unit([{"state": state, "unresolved": unresolved,
                   "quiescence": {"reason": "controlled-terminal"}}])
    runtime = _Runtime(unit)
    owner_before = runtime.unit_execution_owner
    units_before = runtime.units
    stop_before = runtime.stop
    disposed = []
    observations = []
    entered_wait = Event()
    errors = []

    def on_observation(observation):
        observations.append(dict(observation))

    def wait_for_resume(observation):
        entered_wait.set()
        raise SystemExit("test requests another owner inspection")

    def before_runtime_stop():
        disposed.append("disposed")

    def run():
        try:
            _OPERATOR.retain_generation_owner(
                runtime, (), on_observation=on_observation,
                wait_for_resume=wait_for_resume,
                before_runtime_stop=before_runtime_stop)
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=run, daemon=True)
    thread.start()
    assert entered_wait.wait(2), "terminal outcome was not surfaced for inspection"
    thread.join(2)
    assert not thread.is_alive(), "test scope did not release its retained-owner worker"
    assert len(errors) == 1 and isinstance(errors[0], _TestScopeEnd)
    assert len(observations) == 1
    assert observations[0]["state"] == "OWNER_RETAINED"
    assert observations[0]["runtime_stopped"] is False
    assert observations[0]["inspection_required"] is True
    assert observations[0]["units"] == [{
        "index": 0, "state": state, "attempts": 1,
        "quiescence": {"reason": "controlled-terminal"},
    }]
    assert runtime.unit_execution_owner is owner_before
    assert runtime.units is units_before
    assert runtime.stop == stop_before
    assert runtime.stop_calls == 0 and runtime.stopped is False
    assert runtime.units.list_calls == 1
    assert runtime.unit_execution_owner.authorization_calls == 1
    assert unit.close_calls == [runtime.unit_execution_owner.token]
    assert unit.prompt_calls == 0
    assert disposed == []


def test_pending_close_retains_same_owner_until_confirmed_then_stops():
    unit = _Unit([
        {"state": "pending", "unresolved": True,
         "quiescence": {"reason": "sdk_operations_active"}},
        {"state": "confirmed", "unresolved": False,
         "quiescence": {"reason": "sdk_idle"}},
    ])
    runtime = _Runtime(unit)
    owner_before = runtime.unit_execution_owner
    units_before = runtime.units
    stop_before = runtime.stop
    on_retained = Event()
    resume = Event()
    observations = []
    disposed = []
    results = []
    errors = []

    def on_observation(observation):
        observations.append(dict(observation))
        if observation.get("state") == "OWNER_RETAINED":
            on_retained.set()

    def wait_for_resume(observation):
        if observation.get("state") == "OWNER_RETAINED":
            if not resume.wait(5):
                raise TimeoutError("retained owner was not resumed by the test")

    def before_runtime_stop():
        disposed.append((runtime, runtime.unit_execution_owner))

    def run():
        try:
            results.append(_OPERATOR.retain_generation_owner(
                runtime, (), on_observation=on_observation,
                wait_for_resume=wait_for_resume,
                before_runtime_stop=before_runtime_stop))
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=run, daemon=True)
    try:
        thread.start()
        assert on_retained.wait(2), "pending close was not surfaced for inspection"
        assert thread.is_alive(), "runner returned while the same Unit close was pending"
        assert results == [] and errors == []
        assert runtime.unit_execution_owner is owner_before
        assert runtime.units is units_before
        assert runtime.stop == stop_before
        assert runtime.stop_calls == 0 and runtime.stopped is False
        assert runtime.stop_state == "idle"
        assert runtime.units.list_calls == 1
        assert runtime.unit_execution_owner.authorization_calls == 1
        assert unit.close_calls == [runtime.unit_execution_owner.token]
        assert unit.prompt_calls == 0
        assert disposed == []
        assert observations[0]["state"] == "OWNER_RETAINED"
        assert observations[0]["runtime_stopped"] is False
        assert observations[0]["units"] == [{
            "index": 0, "state": "pending", "attempts": 1,
            "quiescence": {"reason": "sdk_operations_active"},
        }]

        resume.set()
        thread.join(2)
        assert not thread.is_alive(), "confirmed owner cleanup did not terminate the runner"
    finally:
        resume.set()
        thread.join(2)

    assert errors == []
    assert results == [(["confirmed"], [2])]
    assert runtime.unit_execution_owner is owner_before
    assert runtime.units is units_before
    assert runtime.stop_calls == 1 and runtime.stopped is True
    assert runtime.stop_state == "completed"
    assert runtime.units.list_calls == 1
    assert runtime.unit_execution_owner.authorization_calls == 1
    assert unit.close_calls == [runtime.unit_execution_owner.token,
                                runtime.unit_execution_owner.token]
    assert unit.prompt_calls == 0
    assert disposed == [(runtime, owner_before)]
    assert observations[0]["state"] == "OWNER_RETAINED"


@pytest.mark.parametrize("stop_mode", ["pending", "raise"])
def test_runtime_stop_without_confirmed_state_retains_confirmed_unit_owner(
        stop_mode, monkeypatch):
    _install_test_escape_timer(monkeypatch)
    unit = _Unit([{"state": "confirmed", "unresolved": False,
                   "quiescence": {"reason": "sdk_idle"}}])
    runtime = _Runtime(unit, stop_mode=stop_mode)
    owner_before = runtime.unit_execution_owner
    units_before = runtime.units
    observations = []
    disposed = []
    entered_wait = Event()
    errors = []

    def on_observation(observation):
        observations.append(dict(observation))
        if observation.get("stop_error"):
            entered_wait.set()

    def wait_for_resume(_observation):
        raise SystemExit("test requests another owner inspection")

    def before_runtime_stop():
        disposed.append((runtime, runtime.unit_execution_owner))

    def run():
        try:
            _OPERATOR.retain_generation_owner(
                runtime, (), on_observation=on_observation,
                wait_for_resume=wait_for_resume,
                before_runtime_stop=before_runtime_stop)
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=run, daemon=True)
    thread.start()
    assert entered_wait.wait(2), "unconfirmed stop did not retain its owner"
    thread.join(2)
    assert not thread.is_alive(), "test scope did not release retained stop worker"
    assert len(errors) == 1 and isinstance(errors[0], _TestScopeEnd)
    assert len(observations) == 1
    observation = observations[0]
    assert observation["state"] == "OWNER_RETAINED"
    assert observation["runtime_stopped"] is False
    assert observation["stop_error"]
    assert observation["units"] == [{
        "index": 0, "state": "confirmed", "attempts": 1,
        "quiescence": {"reason": "sdk_idle"},
    }]
    assert runtime.unit_execution_owner is owner_before
    assert runtime.units is units_before
    assert runtime.stop_calls == 1
    assert runtime.stop_state == "pending"
    assert runtime.stopped is False
    assert runtime.units.list_calls == 1
    assert runtime.unit_execution_owner.authorization_calls == 1
    assert unit.close_calls == [runtime.unit_execution_owner.token]
    assert unit.prompt_calls == 0
    assert disposed == [(runtime, owner_before)]


@pytest.mark.parametrize("state", ["unknown", "partial", "refused"])
def test_terminal_unit_outcome_is_retained_without_retry_or_disposal(state, monkeypatch):
    _terminal_test_state(state, monkeypatch)


def test_pending_close_without_unresolved_proof_requires_inspection_no_auto_poll(monkeypatch):
    _terminal_test_state("pending", monkeypatch, unresolved=False)
    observed_input = []

    def record_input(prompt):
        observed_input.append(prompt)
        return "inspect"

    def fail_if_polled(_seconds):
        raise AssertionError("nonretryable pending close must not auto-poll")

    monkeypatch.setattr(builtins, "input", record_input)
    monkeypatch.setattr(_OPERATOR, "time", SimpleNamespace(
        time=_time.time, sleep=fail_if_polled))
    observation = {
        "state": "OWNER_RETAINED", "runtime_stopped": False,
        "inspection_required": True,
        "units": [{"index": 0, "state": "pending", "attempts": 1}],
    }
    _OPERATOR.wait_generation_owner_resume(observation)
    assert observed_input == ["Owner retained; press Enter to inspect the same owner again: "]


def test_unknown_owner_snapshot_refreshes_without_retry_or_disposal(monkeypatch):
    _install_test_escape_timer(monkeypatch)

    class _InspectableUnit(_Unit):
        def __init__(self):
            super().__init__([{"state": "unknown", "unresolved": True,
                              "quiescence": {"reason": "unknown_native_outcome"}}])
            self.snapshot_states = iter(("opening", "unknown"))
            self.snapshot_calls = 0

        def snapshot(self):
            self.snapshot_calls += 1
            return {"state": next(self.snapshot_states)}

    unit = _InspectableUnit()
    runtime = _Runtime(unit)
    owner_before = runtime.unit_execution_owner
    units_before = runtime.units
    observations = []
    disposed = []
    wait_calls = []
    errors = []
    second_observation = Event()

    def on_observation(observation):
        observations.append(dict(observation))
        if len(observations) == 2:
            second_observation.set()

    def wait_for_resume(_observation):
        wait_calls.append(None)
        if len(wait_calls) == 1:
            return  # Simulate Enter: inspect the same retained owner again.
        raise SystemExit("test requests another owner inspection")

    def before_runtime_stop():
        disposed.append((runtime, runtime.unit_execution_owner))

    def run():
        try:
            _OPERATOR.retain_generation_owner(
                runtime, (), on_observation=on_observation,
                wait_for_resume=wait_for_resume,
                before_runtime_stop=before_runtime_stop)
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=run, daemon=True)
    thread.start()
    assert second_observation.wait(2), "second retained-owner inspection was not emitted"
    thread.join(2)
    assert not thread.is_alive(), "test timer did not release the inspection worker"
    assert len(errors) == 1 and isinstance(errors[0], _TestScopeEnd)
    assert len(observations) == 2
    assert all(observation["state"] == "OWNER_RETAINED"
               and observation["runtime_stopped"] is False
               and observation["inspection_required"] is True
               for observation in observations)
    assert observations[0]["inspection"] == [{"index": 0, "owner_state": "opening"}]
    assert observations[1]["inspection"] == [{"index": 0, "owner_state": "unknown"}]
    assert all(observation["units"] == [{
        "index": 0, "state": "unknown", "attempts": 1,
        "quiescence": {"reason": "unknown_native_outcome"},
    }] for observation in observations)
    assert unit.snapshot_calls == 2
    assert len(wait_calls) == 2
    assert unit.close_calls == [runtime.unit_execution_owner.token]
    assert unit.prompt_calls == 0
    assert runtime.unit_execution_owner is owner_before
    assert runtime.units is units_before
    assert runtime.units.list_calls == 1
    assert runtime.unit_execution_owner.authorization_calls == 1
    assert runtime.stop_calls == 0 and runtime.stop_state == "idle"
    assert runtime.stopped is False
    assert disposed == []
