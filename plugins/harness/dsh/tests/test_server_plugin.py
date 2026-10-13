"""dsh server plugin build: explicit owner view wiring, never a fake grant.

Controlled doubles only: no real owner, records, journal or native process.
"""
from types import SimpleNamespace
import pytest
from ordessa_execution_api.environment import GuaranteeUnavailableError
from ordessa_harness_dsh.server_plugin import DshServerPlugin
from ordessa_harness_dsh import DshRuntimeProvider
from server_plugin_api import (ServerPluginContext,
                               PACTHOLD_CONTRIBUTIONS_POINT_ID,
                               PACTHOLD_CONTRIBUTIONS_API_VERSION)

# Test fixture digest only — NOT a real implementation digest. Production
# digests are injected by the deployment fingerprint gate (freeze §3).
DIGEST = "sha256:" + "a" * 64
ENVIRONMENT_ID = "env-dsh-fixture"
DEFINITION = {"environmentNamespace": ENVIRONMENT_ID, "definitionId": "dsh", "revision": "1"}


class OwnerView:
    """Duck-typed deployment OwnerProviderView: records and verifier only."""

    def __init__(self, records, verifier):
        self.records, self.verifier = records, verifier


class ViewVerifier:
    def verify_and_consume(self, context, *args):
        return context.facts


def fresh_view():
    """One internally consistent owner view: records.verifier is THE verifier."""
    verifier = ViewVerifier()
    return OwnerView(records=ready_records(verifier), verifier=verifier)


def ready_records(verifier):
    return SimpleNamespace(verifier=verifier, reserve_unit=lambda *a, **k: None,
                           begin_session=lambda *a, **k: None,
                           record_session=lambda *a, **k: None,
                           read_unit=lambda *a, **k: None,
                           read_session=lambda *a, **k: None)


def ready_projection():
    return SimpleNamespace(verify_preparation=lambda *a, **k: None,
                           revalidate_start=lambda *a, **k: None,
                           read_unit=lambda *a, **k: None,
                           read_session=lambda *a, **k: None,
                           publication_facts=lambda *a, **k: None,
                           publish_channel=lambda *a, **k: None)


def ready_provider(view, *, records=None, verifier=None):
    """A provider wired to exactly the given owner view (or an impostor pair)."""
    return DshRuntimeProvider(definition_ref=DEFINITION, implementation_digest=DIGEST,
                              unit_records=view.records if records is None else records,
                              projection=ready_projection(),
                              verifier=view.verifier if verifier is None else verifier,
                              channel_factory=SimpleNamespace(open=lambda *a, **k: None))


def staged_context(environment_id, owner="absent", owner_view=None):
    """One binding; `owner` attribute presence on the Environment is explicit."""
    environment = SimpleNamespace(environment_id=environment_id)
    if owner == "absent":
        pass  # legacy deployment: no owner_ports attribute at all
    elif owner is None:
        environment.owner_ports = SimpleNamespace()  # staged, exposes no view
    else:
        environment.owner_ports = SimpleNamespace(provider_view=owner_view)
    binding = SimpleNamespace(environment=environment)
    return ServerPluginContext(plugin_id="dsh", data_root=None,
                               ports={"core.binding": binding})


def recording_factory(*, substitute=None):
    """Factory honouring the frozen two-argument contract (owner_view may be None)."""
    calls = []

    def factory(environment_id, owner_view=None):
        calls.append((environment_id, owner_view))
        if substitute is not None:
            return ready_provider(substitute)
        if owner_view is None:
            return DshRuntimeProvider(definition_ref=DEFINITION,
                                      implementation_digest=DIGEST)
        return ready_provider(owner_view)

    factory.calls = calls
    return factory


def registration_providers(registration):
    (contribution,) = registration.contributions.contributions
    assert contribution.point_id == PACTHOLD_CONTRIBUTIONS_POINT_ID
    assert contribution.api_version == PACTHOLD_CONTRIBUTIONS_API_VERSION
    assert contribution.required is True
    (payload,) = contribution.payload.agent_runtime_providers
    return payload


def assert_called_once_with(factory, view):
    """Exactly one two-argument factory call for this environment and view."""
    assert len(factory.calls) == 1
    environment_id, received = factory.calls[0]
    assert environment_id.value == ENVIRONMENT_ID
    assert received is view


def test_descriptor_reports_dsh_identity():
    plugin = DshServerPlugin(recording_factory())
    descriptor = plugin.descriptor()
    assert descriptor.id == "dsh"
    assert descriptor.display_name == "Independent DeepSeek dsh AgentUnit"
    assert descriptor.version == "0.1.0a1"


def test_owner_view_present_provider_consumes_exactly_owner_records_and_verifier():
    view = fresh_view()
    factory = recording_factory()
    registration = DshServerPlugin(factory).build(
        staged_context(ENVIRONMENT_ID, owner="staged", owner_view=view))
    assert_called_once_with(factory, view)
    provider = registration_providers(registration)
    assert provider.records is view.records and provider.verifier is view.verifier
    # Capabilities follow the consumed owner records: the full unit lifecycle
    # minus the configuration family (absent for dsh in this version).
    assert "prepare" in provider.descriptor.supported_methods
    assert "start" in provider.descriptor.supported_methods
    assert "apply_configuration" not in provider.descriptor.supported_methods
    assert "describe_configuration" not in provider.descriptor.supported_methods


def test_owner_view_present_with_substituted_records_and_verifier_is_refused():
    view = fresh_view()
    impostor = fresh_view()
    factory = recording_factory(substitute=impostor)
    with pytest.raises(GuaranteeUnavailableError, match="owner"):
        DshServerPlugin(factory).build(
            staged_context(ENVIRONMENT_ID, owner="staged", owner_view=view))
    assert_called_once_with(factory, view)


def test_owner_view_present_but_ignored_by_factory_is_refused():
    view = fresh_view()
    calls = []

    def factory(environment_id, owner_view=None):
        calls.append((environment_id, owner_view))
        return DshRuntimeProvider(definition_ref=DEFINITION,
                                  implementation_digest=DIGEST)

    with pytest.raises(GuaranteeUnavailableError, match="owner"):
        DshServerPlugin(factory).build(
            staged_context(ENVIRONMENT_ID, owner="staged", owner_view=view))
    assert len(calls) == 1
    assert calls[0][0].value == ENVIRONMENT_ID and calls[0][1] is view


def test_owner_view_absent_builds_discovery_only_and_factory_receives_none():
    factory = recording_factory()
    registration = DshServerPlugin(factory).build(
        staged_context(ENVIRONMENT_ID, owner="absent"))
    assert_called_once_with(factory, None)
    provider = registration_providers(registration)
    assert "prepare" not in provider.descriptor.supported_methods
    assert "start" not in provider.descriptor.supported_methods


def test_owner_staged_without_provider_view_degrades_to_discovery_only():
    factory = recording_factory()
    registration = DshServerPlugin(factory).build(
        staged_context(ENVIRONMENT_ID, owner=None))
    assert_called_once_with(factory, None)
    provider = registration_providers(registration)
    assert "prepare" not in provider.descriptor.supported_methods
    assert "start" not in provider.descriptor.supported_methods


def test_noncallable_factory_is_refused():
    with pytest.raises(TypeError):
        DshServerPlugin(None)


def test_missing_binding_refuses_before_any_factory_call():
    factory = recording_factory()
    with pytest.raises(GuaranteeUnavailableError):
        DshServerPlugin(factory).build(ServerPluginContext(
            plugin_id="dsh", data_root=None, ports={}))
    assert factory.calls == []


def test_wrong_family_or_environment_provider_is_refused():
    view = fresh_view()

    def foreign_factory(environment_id, owner_view=None):
        from ordessa_harness_codex import CodexRuntimeProvider
        return CodexRuntimeProvider(definition_ref=DEFINITION,
                                    implementation_digest=DIGEST)

    with pytest.raises(GuaranteeUnavailableError):
        DshServerPlugin(foreign_factory).build(
            staged_context(ENVIRONMENT_ID, owner="staged", owner_view=view))
