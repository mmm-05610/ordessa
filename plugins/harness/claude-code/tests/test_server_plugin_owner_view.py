"""Controlled wiring of the assembled owner view into the server plugin build.

A stand-in carries only the frozen contract surface: ``AssembledOwner.provider_view``
returning ``OwnerProviderView``-shaped records + verifier, never an issuer.
Identity is object identity, no registration, native IO or model runs, and the
factory always sees the two-argument contract ``(environment_id, owner_view)``
even when no owner was staged.
"""
from types import SimpleNamespace

import pytest
from ordessa_execution_api.environment import GuaranteeUnavailableError

from ordessa_harness_claude_code.provider import ClaudeCodeRuntimeProvider
from ordessa_harness_claude_code.server_plugin import ClaudeCodeServerPlugin

DIGEST = 'sha256:' + 'c' * 64
DISCOVERY_METHODS = {'describe_definition', 'inspect_installation',
                     'assess_configuration', 'plan_preparation'}


class ViewVerifier:
    """Idle verifier stand-in; identity object, grants nothing."""


class ViewUnitRecords:
    def __init__(self, verifier):
        self.verifier = verifier

    def reserve_unit(self, *args, **kwargs):
        raise AssertionError('controlled contract stand-in reserves nothing')


class Preparer:
    def verify_preparation(self, plan, facts):
        return True


class OwnerView:
    """Only the frozen OwnerProviderView surface: records + verifier."""

    def __init__(self, records, verifier):
        self.records, self.verifier = records, verifier


class AssembledOwnerStandIn:
    """Only the frozen AssembledOwner.provider_view surface; no issuer."""

    def __init__(self, records, verifier):
        self._records, self._verifier = records, verifier

    @property
    def provider_view(self):
        return OwnerView(self._records, self._verifier)


def definition(environment_id):
    return {'environmentNamespace': environment_id, 'definitionId': 'claude',
            'revision': '1'}


def context_owner():
    verifier = ViewVerifier()
    return AssembledOwnerStandIn(ViewUnitRecords(verifier), verifier)


def host_binding(environment):
    return SimpleNamespace(ports={'core.binding': SimpleNamespace(environment=environment)})


def control(calls, make_provider):
    def factory(environment_id, owner_view=None):
        calls.append((environment_id.value, owner_view))
        return make_provider(environment_id, owner_view)
    return ClaudeCodeServerPlugin(factory)


def contributed_provider(registration):
    (contribution,) = registration.contributions.contributions
    (provider,) = contribution.payload.agent_runtime_providers
    return provider


def test_owner_absent_degrades_to_discovery_only_without_prepare_or_start():
    calls = []
    plugin = control(calls, lambda environment_id, owner_view: ClaudeCodeRuntimeProvider(
        definition_ref=definition(environment_id.value), implementation_digest=DIGEST))
    registration = plugin.build(host_binding(SimpleNamespace(environment_id='test')))
    assert calls == [('test', None)]
    provider = contributed_provider(registration)
    assert isinstance(provider, ClaudeCodeRuntimeProvider)
    assert provider.descriptor.provider_id == 'claude'
    assert set(provider.descriptor.supported_methods) == DISCOVERY_METHODS
    assert not ({'prepare', 'start'} & set(provider.descriptor.supported_methods))


def test_owner_view_absent_when_environment_owner_attribute_is_empty():
    calls = []
    plugin = control(calls, lambda environment_id, owner_view: ClaudeCodeRuntimeProvider(
        definition_ref=definition(environment_id.value), implementation_digest=DIGEST))
    plugin.build(host_binding(SimpleNamespace(environment_id='test', owner_ports=None)))
    plugin.build(host_binding(SimpleNamespace(environment_id='test', owner_ports=object())))
    plugin.build(host_binding(SimpleNamespace(environment_id='test')))
    assert calls == [('test', None)] * 3


def test_assembled_owner_view_is_consumed_exactly_and_build_succeeds():
    calls = []
    owner = context_owner()
    records = owner.provider_view.records
    verifier = owner.provider_view.verifier

    def make_provider(environment_id, owner_view):
        # The factory consumes exactly the staged view's original objects.
        assert owner_view.records is records and owner_view.verifier is verifier
        return ClaudeCodeRuntimeProvider(definition_ref=definition(environment_id.value),
            implementation_digest=DIGEST, verifier=owner_view.verifier,
            unit_records=owner_view.records, preparation_authority=Preparer())

    plugin = control(calls, make_provider)
    registration = plugin.build(host_binding(SimpleNamespace(environment_id='test',
        owner_ports=owner)))
    assert len(calls) == 1 and calls[0][0] == 'test' and calls[0][1] is not None
    provider = contributed_provider(registration)
    assert provider._records is records and provider._verifier is verifier
    assert 'prepare' in provider.descriptor.supported_methods
    assert 'start' not in provider.descriptor.supported_methods


@pytest.mark.parametrize('mode', ['records', 'verifier', 'both'])
def test_other_records_or_verifier_are_refused_when_owner_view_present(mode):
    owner = context_owner()
    view = owner.provider_view
    other_verifier = ViewVerifier()
    other_records = ViewUnitRecords(other_verifier)
    verifier = view.verifier if mode == 'records' else other_verifier
    records = view.records if mode == 'verifier' else other_records
    calls = []

    def make_provider(environment_id, owner_view):
        return ClaudeCodeRuntimeProvider(definition_ref=definition(environment_id.value),
            implementation_digest=DIGEST, verifier=verifier, unit_records=records)

    plugin = control(calls, make_provider)
    with pytest.raises(GuaranteeUnavailableError, match='owner'):
        plugin.build(host_binding(SimpleNamespace(environment_id='test', owner_ports=owner)))
    assert len(calls) == 1 and calls[0][0] == 'test'
    assert calls[0][1].records is view.records and calls[0][1].verifier is view.verifier
