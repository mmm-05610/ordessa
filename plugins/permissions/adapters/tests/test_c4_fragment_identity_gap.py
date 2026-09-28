"""A real C4 plan cannot invent the caller's trusted fragment item identity."""
from __future__ import annotations

from _permissions_adapters_helpers import make_ceiling, make_intent
from ordessa_harness.application import ConfigurationApplicationService, OperationJournal, RuntimeSnapshot
from ordessa_harness.contributions import CONFIGURATION_POINT, HarnessContributionRegistry, POINT_API_VERSION
from ordessa_harness.materialization import MergeAuthority, TargetAuthority
from ordessa_harness_api import (
    AdapterContext, AdapterRefusal, ApplicationTarget, DesiredFragment, Installation, Plan,
    TargetDescriptor, TargetHandle, VerificationUnknown,
)
from ordessa_permissions_adapters import (
    ClaudeAdapter, PolicyCompileSnapshot, PolicyConfigurationAdapter,
)
from ordessa_server.plugin_host import MethodRegistry, ServerPluginHost, StreamRouteRegistry
from server_plugin_api import Contribution, ContributionBatch, ServerPluginDescriptor, ServerPluginRegistration


def test_c4_plan_preserves_a_real_fragment_item_id(tmp_path) -> None:
    brand = ClaudeAdapter()
    snapshot = PolicyCompileSnapshot.of(
        harness_id="claude-code", native_version="0.81.2",
        intent=make_intent("claude-code", [
            {"key": "external_directory", "action": "allow"},
            {"key": "bash", "action": "deny"}]), ceiling=make_ceiling())
    desired = brand.compilePolicy(snapshot).as_record()
    payload = PolicyConfigurationAdapter(brand, snapshot_resolver=lambda _ctx, _desired: snapshot)

    class Plugin:
        def descriptor(self):
            return ServerPluginDescriptor("test.permissions.c4", "Controlled policy", "1")

        def build(self, _context):
            return ServerPluginRegistration(contributions=ContributionBatch((
                Contribution(CONFIGURATION_POINT, POINT_API_VERSION, payload),)))

    registry = HarnessContributionRegistry()
    host = ServerPluginHost(methods=MethodRegistry(), stream_routes=StreamRouteRegistry())
    host.register_contribution_point(CONFIGURATION_POINT, POINT_API_VERSION,
                                     handler=registry.configuration_handler, exclusive=False)
    host.activate(Plugin())
    target = ApplicationTarget("controlled-server", "controlled-session", "controlled-channel", 1)
    handle = TargetHandle(".claude/settings.json", 1)
    descriptor = TargetDescriptor(handle, "file", "json", "instance",
                                  (("permissions", "ask"), ("permissions", "deny")))
    context = AdapterContext((descriptor,), Installation("claude-code", (0, 81, 2),
                             (0, 1, 0), "controlled:installation"),
                             "permissions.ask", "instance", "controlled:capability")
    private_root = tmp_path / "private"
    private_root.mkdir(mode=0o700)
    private_root.chmod(0o700)

    class Runtime:
        def capture(self, actual):
            assert actual == target
            return RuntimeSnapshot(target, context,
                MergeAuthority((TargetAuthority(descriptor, ("settings.json",),
                    (("permissions", "ask"), ("permissions", "deny"))),)),
                {}, {}, private_root, {}, "base-1", "native-pin-1", 1,
                "authority-1", "secrets-1")

    class Permit:
        def verify(self, *_args):
            raise AssertionError("plan must not spend a permit")

    service = ConfigurationApplicationService(
        principal="alice", target=target, carrier=host, runtime=Runtime(),
        permits=Permit(), journal=OperationJournal(tmp_path / "journal.sqlite"))
    fragment = DesiredFragment("permissions.policy-adapters", "policy-choice-1", "v1",
                               "controlled:test", "source-1", "set", desired)
    try:
        planned = service.plan(target, (fragment,), "base-1")
        assert isinstance(planned, Plan)
        merged = service._prepared[planned.plan_id].merged  # controlled C4 identity proof
        assert {intent.item_id for intent in merged.intents} == {fragment.item_id}
        assert {intent.facet_id for intent in merged.intents} == {fragment.facet_id}
        assert list(private_root.iterdir()) == []  # planning cannot publish a generation
        for failure in (RuntimeError("authority offline"),
                        OSError("authority socket gone"),
                        KeyError("snapshot missing")):
            def authority_offline(_context, _desired, failure=failure):
                raise failure

            payload._snapshot_resolver = authority_offline
            capabilities = service.inspect(target)
            assert {item.status for item in capabilities.capabilities} == {"unknown"}
            assert isinstance(payload.compile(context, {}, desired), AdapterRefusal)
            assert isinstance(payload.verify(context, desired), VerificationUnknown)
        payload._snapshot_resolver = None
        assert {item.status for item in service.inspect(target).capabilities} == {"unknown"}
        assert isinstance(payload.compile(context, {}, desired), AdapterRefusal)
    finally:
        host.deactivate("test.permissions.c4")
