"""Order 006 closeout: Server's Core facade must point at one Environment.

These are boundary regressions, not a second execution test suite. The E1
Environment owns effect admission; a Server adapter may carry its identity and
refuse guarantees it cannot provide, but must never create a parallel
CoreRuntime or route around the Environment.
"""
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from ordessa_server.core_binding import CoreBinding
from ordessa_environment_api import (
    GuaranteeLevel,
    GuaranteeUnavailableError,
    RequestKey,
)
from pacthold.public import CoreContributionSet, Environment, InstallationRecord


@dataclass(frozen=True)
class _RegistrationContract:
    contract_id = "server.binding-registration@1"
    label: str = "registration seam"


def test_core_binding_forwards_the_product_environment_without_a_second_runtime(tmp_path):
    environment = Environment("server-root")
    path = tmp_path / "server-root.sqlite"
    factory_paths = []

    def environment_factory(store_path):
        factory_paths.append(Path(store_path))
        return environment

    binding = CoreBinding(path, environment_factory=environment_factory)
    try:
        assert binding.open() is environment
        assert binding.environment is environment
        assert factory_paths == [path]
        assert not path.exists(), "Server constructed an independent CoreStore file"
        assert not hasattr(binding, "submit"), "legacy execution must not bypass Environment"

        source = Path(__import__("ordessa_server.core_binding", fromlist=["__file__"]).__file__)
        assert "CoreRuntime" not in source.read_text(encoding="utf-8")
    finally:
        binding.close()


def test_binding_environment_refuses_reliable_invocation_without_store_or_key(tmp_path):
    environment = Environment("server-root")
    binding = CoreBinding(tmp_path / "unused.sqlite", environment_factory=lambda _path: environment)
    effects = []
    try:
        assert binding.environment is environment
        with pytest.raises(GuaranteeUnavailableError, match="refused before dispatch"):
            binding.environment.invoke(
                "missing.surface",
                RequestKey("server-root", "local", "request-one"),
                guarantee=GuaranteeLevel.RELIABLE,
                input_digest="a" * 64,
                handler=lambda: effects.append("dispatched"),
            )
        assert effects == []
        assert not (tmp_path / "unused.sqlite").exists()
    finally:
        binding.close()


def test_host_contribution_transaction_stages_and_commits_in_the_same_environment(tmp_path):
    environment = Environment("server-root")
    owner = "sample.plugin"
    environment.install(InstallationRecord(owner, "a" * 64))
    environment.enable(owner)
    binding = CoreBinding(tmp_path / "unused.sqlite", environment_factory=lambda _path: environment)
    contribution = SimpleNamespace(payload=CoreContributionSet(contracts=(_RegistrationContract,)))
    try:
        prepared = binding.stage(contribution, owner)
        assert prepared.state == "staged"
        assert environment.registry_snapshot.contract_ids == ()

        binding.commit(contribution, prepared, owner)
        assert prepared.state == "committed"
        assert environment.registry_snapshot.contract_ids == (_RegistrationContract.contract_id,)
    finally:
        binding.close()
