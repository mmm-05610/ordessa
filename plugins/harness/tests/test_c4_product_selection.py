"""No-model C4 selection against the real default product's six C2 records."""
from __future__ import annotations

import sqlite3
import pytest

from ordessa_harness.application import ConfigurationApplicationService, OperationJournal, RuntimeSnapshot
from ordessa_harness.materialization import MergeAuthority
from ordessa_harness_api import AdapterContext, ApplicationTarget, DesiredFragment, Installation
from ordessa_server.bootstrap import build_runtime


TARGET = ApplicationTarget("controlled-server", "controlled-session", "controlled-channel", 1)


class Runtime:
    def __init__(self, root, *, adapter_version=(0, 1, 0), entry="approval_policy"):
        self.root = root
        self.adapter_version = adapter_version
        self.entry = entry
        self.effects = 0

    def capture(self, target):
        assert target == TARGET
        return RuntimeSnapshot(target, AdapterContext((),
            Installation("codex", (2, 0, 0), self.adapter_version, "controlled:pin"),
            self.entry, "instance", "controlled:capability"),
            MergeAuthority(()), {}, {}, self.root, {}, "base-1", "pin-1", 1,
            "authority-1", "secret-1")

    def activate_generation(self, *_args):
        self.effects += 1
        raise AssertionError("unselected Q5 facets must never cause a native effect")


class Permit:
    calls = 0

    def verify(self, *_args):
        self.calls += 1
        raise AssertionError("no permit during inspect")


def test_real_product_c4_inspect_selects_matching_permissions_facet(tmp_path):
    product = build_runtime(tmp_path / "product")
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    try:
        service = ConfigurationApplicationService(principal="alice", target=TARGET,
            carrier=product.plugin_host, runtime=Runtime(root), permits=Permit(),
            journal=OperationJournal(tmp_path / "journal.sqlite"))
        capabilities = service.inspect(TARGET)
        assert {item.facet_id for item in capabilities.capabilities} == {
            "permissions.policy-adapters"}
        assert {item.status for item in capabilities.capabilities} == {"unknown"}
        fragment = DesiredFragment("permissions.policy-adapters", "policy-choice-1", "v1",
                                   "controlled:test", "source-1", "set",
                                   {"approval_policy": "untrusted"})
        planned = service.plan(TARGET, (fragment,), "base-1")
        assert planned.kind == "refused" and planned.code.value == "capability-unsupported"
    finally:
        product.stop()


@pytest.mark.parametrize("runtime_adapter_version", ((1, 0, 0), (0, 1, 0)))
def test_real_product_joint_q5_facets_fail_closed_without_independent_adapter_version_evidence(
        tmp_path, runtime_adapter_version):
    product = build_runtime(tmp_path / "product")
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    try:
        runtime = Runtime(root, adapter_version=runtime_adapter_version,
                          entry="sandbox_mode")
        permit = Permit()
        journal = OperationJournal(tmp_path / "journal.sqlite")
        service = ConfigurationApplicationService(principal="alice", target=TARGET,
            carrier=product.plugin_host,
            runtime=runtime, permits=permit, journal=journal)
        capabilities = service.inspect(TARGET)
        # Both contributors are published and C4 selects by facet. An obsolete
        # 1.0 observation matches neither; the current 0.1 pin names both,
        # but no untrusted assessment may become a confirmed capability.
        from ordessa_harness.contributions import CONFIGURATION_POINT
        assert len(product.plugin_host.contributions(CONFIGURATION_POINT)) == 6
        expected = (set() if runtime_adapter_version == (1, 0, 0)
                    else {"permissions.policy-adapters", "sandbox.native-configuration"})
        assert {item.facet_id for item in capabilities.capabilities} == expected
        assert all(item.status == "unknown" for item in capabilities.capabilities)
        fragments = (
            DesiredFragment("sandbox.native-configuration", "sandbox-choice", "1",
                            "controlled:sandbox", "source-1", "set",
                            {"sandbox_mode": "read-only"}),
            DesiredFragment("permissions.policy-adapters", "policy-choice", "v1",
                            "controlled:permissions", "source-2", "set",
                            {"approval_policy": "untrusted"}),
        )
        planned = service.plan(TARGET, fragments, "base-1")
        assert planned.kind == "refused" and planned.code.value == "capability-unsupported"
        assert service._prepared == {} and runtime.effects == 0 and permit.calls == 0
        with sqlite3.connect(journal.path) as db:
            assert db.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 0
        assert not product.plugin_host.owner_busy("ordessa.sandbox-adapters")
        assert not product.plugin_host.owner_busy("ordessa.permissions-adapters")
    finally:
        product.stop()
