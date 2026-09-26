"""MB-E2a modular boundary pins — neutral execution contracts, single implementation.

Approval `MB-E2a-execution-contract-release.md` (baseline d12aa979): the pure
standard-library contract definitions now live exactly once in
``pacthold.execution.contracts``; every historical entry re-exports the same
objects. These pins lock the equal-move:

* identity — old and new entries expose the SAME object, and the historical
  ``execution_contract`` submodule attribute on ``ordessa_server.execution``
  survives (``test_e_inc1a_matrix_pins`` imports it today);
* single implementation — an AST walk finds each definition exactly once, in
  ``contracts.py`` only; the old carrier modules hold imports, not classes
  (counter-example: re-defining any moved name in a carrier turns this red);
* dependency direction — the new ``pacthold.execution`` package imports
  nothing outside the standard library and itself (counter-example: adding a
  Server / Work Core repository / H-P plugin import there turns this red);
* value surface — enum members, dataclass field order and the port's method
  surface are unchanged by the move.

Run (from this task tree root, `work/e2a/`):
    PYTHONPATH=src:$(ls -d plugins/*/src | paste -sd:) \
    ../../tmp/venv/bin/python -m pytest -q -p no:cacheprovider \
    tests/server/test_e_modular_execution_boundary.py
"""
from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
from pathlib import Path

import pacthold.execution as execution_pkg
import pacthold.execution.contracts as contracts
import ordessa_server.execution as server_execution
import ordessa_server.execution.execution_contract as legacy_contract

MOVED_DEFINITIONS = (
    "CancelOutcome", "DeadlinePolicy", "DeliveryOutcome", "EvidenceClass",
    "ExecutionObservation", "ExecutionReceipt", "ExecutionRequest",
    "NeutralBinding", "ObservationState", "TurnExecutionPort",
)
# Names the old ``execution_contract`` module itself must still answer for.
LEGACY_CARRIER_NAMES = tuple(
    name for name in MOVED_DEFINITIONS if name != "TurnExecutionPort"
)
# Names the ``ordessa_server.execution`` package already exposed before the
# move; the package surface must neither lose nor grow them.
PACKAGE_EXPOSED_BEFORE = (
    "CancelOutcome", "ExecutionObservation", "ExecutionReceipt",
    "ExecutionRequest", "TurnExecutionPort",
)
# threading/uuid added by decisions/E2b-pin-amendments-ruling.md: the
# lifecycle machine's lock and dispatch-id minting need them; still stdlib.
STDLIB_ROOTS = frozenset(
    {"__future__", "dataclasses", "datetime", "enum", "threading", "types",
     "typing", "uuid"}
)


def _class_defs(path: Path) -> list[str]:
    return [
        node.name
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ClassDef)
    ]


def _module_path(module: object) -> Path:
    return Path(getattr(module, "__file__")).resolve()  # type: ignore[attr-defined]


def test_legacy_carrier_reexports_same_objects() -> None:
    for name in LEGACY_CARRIER_NAMES:
        assert getattr(legacy_contract, name) is getattr(contracts, name), name


def test_package_entries_reexport_same_objects() -> None:
    for name in PACKAGE_EXPOSED_BEFORE:
        assert getattr(server_execution, name) is getattr(contracts, name), name
    for name in MOVED_DEFINITIONS:
        assert getattr(execution_pkg, name) is getattr(contracts, name), name


def test_legacy_package_surface_did_not_grow() -> None:
    # Counter-example pin: names the historical package never exposed must
    # stay off it - the equal-move re-exports, it does not widen the entry.
    never_exposed = set(LEGACY_CARRIER_NAMES) - set(PACKAGE_EXPOSED_BEFORE)
    package_attrs = vars(server_execution)
    leaked = sorted(name for name in never_exposed if name in package_attrs)
    assert leaked == []


def test_execution_contract_submodule_attribute_survives() -> None:
    # ``from ordessa_server.execution import execution_contract`` must keep
    # resolving to the same module object, not only its re-exported names.
    assert server_execution.execution_contract is legacy_contract


def test_definitions_live_exactly_once_in_new_contracts() -> None:
    contracts_path = _module_path(contracts)
    for py in sorted(contracts_path.parent.rglob("*.py")):
        defs = _class_defs(py)
        if py == contracts_path:
            for name in MOVED_DEFINITIONS:
                assert defs.count(name) == 1, (py.name, name)
        else:
            for name in MOVED_DEFINITIONS:
                assert name not in defs, (py.name, name)


def test_old_carriers_hold_no_second_definition() -> None:
    # The re-export carrier defines no class at all; the package __init__
    # keeps its composition classes (HarnessDescriptor/Registry) but none of
    # the moved contract names.
    assert _class_defs(_module_path(legacy_contract)) == []
    init_defs = _class_defs(_module_path(server_execution))
    for name in MOVED_DEFINITIONS:
        assert name not in init_defs, name


def test_new_package_imports_stdlib_and_self_only() -> None:
    offenders: list[str] = []
    for py in sorted(_module_path(contracts).parent.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] not in STDLIB_ROOTS and not (
                        alias.name == "pacthold.execution"
                        or alias.name.startswith("pacthold.execution.")
                    ):
                        offenders.append(f"{py.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative import stays inside the package
                    continue
                module = node.module or ""
                if module.split(".")[0] not in STDLIB_ROOTS and not (
                    module == "pacthold.execution"
                    or module.startswith("pacthold.execution.")
                ):
                    offenders.append(f"{py.name}: from {module}")
    assert offenders == []


def test_enum_value_surface_unchanged() -> None:
    def members(enum_cls: type) -> list[tuple[str, str]]:
        return [(member.name, member.value) for member in enum_cls]  # type: ignore[attr-defined]

    assert members(contracts.CancelOutcome) == [
        ("CONFIRMED_STOPPED", "confirmed_stopped"),
        ("REFUSED_NO_ACTIVE_RUN", "refused_no_active_run"),
        ("UNKNOWN", "unknown"),
    ]
    assert members(contracts.DeliveryOutcome) == [
        ("DELIVERED", "delivered"),
        ("REFUSED_UNKNOWN_ROUTE", "refused_unknown_route"),
        ("UNKNOWN", "unknown"),
    ]
    assert members(contracts.ObservationState) == [
        ("NOT_KNOWN_TO_E", "not_known_to_e"),
        ("RUNNING", "running"),
        ("TERMINAL", "terminal"),
        ("STOPPED_CONFIRMED", "stopped_confirmed"),
    ]
    assert members(contracts.EvidenceClass) == [
        ("DISPATCH_ACK", "dispatch_ack"),
        ("NATIVE_REPORT", "native_report"),
        ("TERMINAL_RECEIPT", "terminal_receipt"),
        ("CANCEL_CONFIRMATION", "cancel_confirmation"),
        ("NONE", "none"),
    ]


def test_dataclass_field_surface_unchanged() -> None:
    def field_names(cls: type) -> list[str]:
        return [field.name for field in dataclasses.fields(cls)]

    assert field_names(contracts.NeutralBinding) == [
        "contract_id", "object_digest", "mount_token",
    ]
    assert field_names(contracts.DeadlinePolicy) == [
        "hard_deadline", "idle_timeout_seconds",
    ]
    assert field_names(contracts.ExecutionRequest) == [
        "execution_key", "bundle_ref", "resource_bindings",
        "capability_demand", "deadline_policy", "correlation",
    ]
    assert field_names(contracts.ExecutionReceipt) == [
        "execution_key", "dispatch_id", "replayed",
    ]
    assert field_names(contracts.ExecutionObservation) == [
        "execution_key", "state", "evidence", "observed_at",
    ]


def test_port_method_surface_unchanged() -> None:
    port = contracts.TurnExecutionPort
    assert list(inspect.signature(port.accept).parameters) == ["self", "turn_id"]
    assert list(inspect.signature(port.submit).parameters) == ["self", "request"]
    assert list(inspect.signature(port.cancel_execution).parameters) == [
        "self", "execution_key",
    ]
    assert list(inspect.signature(port.observe_execution).parameters) == [
        "self", "execution_key",
    ]
    # The bool ``cancel`` compatibility shell stays deleted (E-INC1b b-1).
    assert not hasattr(port, "cancel")


def test_s_consumer_import_paths_keep_identity() -> None:
    sessions_service = importlib.import_module("ordessa_server.sessions.service")
    assert sessions_service.CancelOutcome is contracts.CancelOutcome
    assert sessions_service.TurnExecutionPort is contracts.TurnExecutionPort
    assert sessions_service.HarnessRegistry is server_execution.HarnessRegistry

    # The host bootstrap composes no product code any more (core-cleanup
    # stage 3): the identity chain anchors at the compatibility core, which
    # is what the composition serves through the plugin ports.
    compat_execution = importlib.import_module("ordessa_server_compat.execution")
    assert compat_execution.TurnExecutionPort is contracts.TurnExecutionPort
    assert compat_execution.HarnessRegistry is server_execution.HarnessRegistry
