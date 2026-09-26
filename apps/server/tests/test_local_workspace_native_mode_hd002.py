"""The local placement's two explicit composition modes (BC-0033, C-0026).

Native is a Server startup choice, not a fallback: these tests keep one probe
answer (`unavailable`) fixed and let only the mode vary, so every difference
between the two columns is the mode and nothing else. The isolated refusals -
code, status, retryable - are pinned verbatim because old compositions must
not feel this change, and the validity ladder is pinned under native too
because weakening it there would turn a mode into a bypass.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ordessa_server.errors import ServerError
from ordessa_server.idempotency import IdempotentRecords
from ordessa_workspace.local_environment import (
    EXECUTION_MODES, LocalEnvironmentProvider,
)
from ordessa_workspace.records import WorkspaceRecords
from ordessa_workspace.service import WorkspaceService
from pacthold.storage import Database

UNAVAILABLE = {"status": "unavailable", "code": "sandbox_provider_unresolved"}
LOCAL_ENVIRONMENT = {"kind": "local", "host": None, "user": None}


def _service(tmp_path: Path, provider: LocalEnvironmentProvider) -> WorkspaceService:
    database = Database(tmp_path / "data")
    database.initialize()
    # No connector on purpose: a local placement never needed a peer machine,
    # and the readiness answer must come from the provider's mode alone.
    return WorkspaceService(WorkspaceRecords(database, IdempotentRecords(database)),
                            IdempotentRecords(database), local=provider)


# --- isolated: the historic refusal, verbatim --------------------------------


def test_isolated_open_refusal_is_typed_code_status_and_retryable():
    provider = LocalEnvironmentProvider(sandbox_probe=lambda: UNAVAILABLE)
    assert provider.execution_mode == "isolated"
    with pytest.raises(ServerError) as raised:
        provider.open_workspace("/tmp")
    assert raised.value.code == "LOCAL_SANDBOX_UNAVAILABLE"
    assert raised.value.status == 503
    assert raised.value.retryable is True
    assert provider.readiness_blockers() == [
        {"code": "LOCAL_SANDBOX_UNAVAILABLE", "retryable": True}
    ]


def test_service_reports_the_isolated_refusal_through_the_existing_chain(tmp_path: Path):
    service = _service(tmp_path, LocalEnvironmentProvider(sandbox_probe=lambda: UNAVAILABLE))
    assert service.readiness_blockers() == [
        {"code": "LOCAL_SANDBOX_UNAVAILABLE", "retryable": True}
    ]
    project = tmp_path / "proj"
    project.mkdir()
    with pytest.raises(ServerError) as raised:
        service.open_environment(environment=LOCAL_ENVIRONMENT, path=str(project),
                                 expected_version=None)
    assert raised.value.code == "LOCAL_SANDBOX_UNAVAILABLE"


# --- native: same machine, same rules, no room -------------------------------


def test_native_opens_a_valid_project_under_the_very_probe_isolated_refuses(
        tmp_path: Path):
    provider = LocalEnvironmentProvider(
        sandbox_probe=lambda: UNAVAILABLE, execution_mode="native")
    project = tmp_path / "project"
    project.mkdir()
    assert provider.open_workspace(str(project)) == {"path": str(project.resolve())}
    assert provider.readiness_blockers() == []


def test_native_never_asks_the_sandbox_probe_at_all(tmp_path: Path):
    def never_called():
        raise AssertionError("a native composition must not consult the sandbox probe")

    provider = LocalEnvironmentProvider(
        sandbox_probe=never_called, execution_mode="native")
    project = tmp_path / "project"
    project.mkdir()
    assert provider.open_workspace(str(project)) == {"path": str(project.resolve())}
    assert provider.readiness_blockers() == []


def test_native_keeps_every_validity_refusal_of_the_isolated_ladder(tmp_path: Path):
    provider = LocalEnvironmentProvider(
        sandbox_probe=lambda: UNAVAILABLE, execution_mode="native")
    with pytest.raises(ServerError) as missing:
        provider.open_workspace(str(tmp_path / "gone"))
    assert missing.value.code == "LOCAL_PATH_MISSING"
    assert missing.value.status == 404
    with pytest.raises(ServerError) as relative:
        provider.open_workspace("relative/path")
    assert relative.value.code == "LOCAL_PATH_INVALID"
    with pytest.raises(ServerError) as root:
        provider.open_workspace("/")
    assert root.value.code == "LOCAL_PATH_FORBIDDEN"
    assert root.value.status == 403
    a_file = tmp_path / "file.txt"
    a_file.write_text("x")
    with pytest.raises(ServerError) as not_dir:
        provider.open_workspace(str(a_file))
    assert not_dir.value.code == "LOCAL_PATH_NOT_DIRECTORY"


def test_a_project_deleted_after_open_is_still_a_stale_refusal_under_native(
        tmp_path: Path):
    provider = LocalEnvironmentProvider(
        sandbox_probe=lambda: UNAVAILABLE, execution_mode="native")
    project = tmp_path / "project"
    project.mkdir()
    provider.open_workspace(str(project))
    project.rmdir()
    with pytest.raises(ServerError) as raised:
        provider.open_workspace(str(tmp_path / "project"))
    assert raised.value.code == "LOCAL_PATH_MISSING"


def test_service_opens_dedups_and_stays_honest_under_native(tmp_path: Path):
    provider = LocalEnvironmentProvider(
        sandbox_probe=lambda: UNAVAILABLE, execution_mode="native")
    service = _service(tmp_path, provider)
    assert service.readiness_blockers() == []
    project = tmp_path / "proj"
    project.mkdir()
    created, opened = service.open_environment(
        environment=LOCAL_ENVIRONMENT, path=str(project), expected_version=None)
    assert created is True
    assert opened["env_kind"] == "local"
    assert opened["normalized_path"] == str(project.resolve())
    again_created, repeated = service.open_environment(
        environment=LOCAL_ENVIRONMENT, path=str(project), expected_version=None)
    assert again_created is False
    assert repeated["id"] == opened["id"]


# --- the mode itself is explicit, never guessed ------------------------------


def test_an_unknown_composition_mode_is_refused_at_construction():
    with pytest.raises(ValueError, match="not supported"):
        LocalEnvironmentProvider(execution_mode="whatever")
    assert EXECUTION_MODES == frozenset({"isolated", "native"})


def test_the_default_construction_is_isolated_so_no_caller_defaults_into_native(
        tmp_path: Path):
    provider = LocalEnvironmentProvider()
    assert provider.execution_mode == "isolated"
