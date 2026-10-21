"""Codex server plugin build: one frozen definition declaration, never a fake grant.

The plugin publishes only the frozen ``HarnessDefinitionDeclaration`` at the
host's definition point. The retired provider factory and the owner-view
wiring it used are gone: no live owner, records, journal or native process is
consumed here.
"""
from types import SimpleNamespace

import pytest

from ordessa_agents.harness.providers.registry import (
    HARNESS_DEFINITION_VERSION,
    HarnessCatalog,
    HarnessDefinitionDeclaration,
    HarnessDefinitionDescriptor,
    HarnessInstallationObservation,
)
from ordessa_execution_api.environment import GuaranteeUnavailableError
from ordessa_harness_codex import CodexRuntimeProvider
from ordessa_harness_codex.server_plugin import CodexServerPlugin
from ordessa_server_plugin_api import ServerPluginContext

# Test fixture digest only — NOT a real implementation digest. Production
# digests are injected by the deployment fingerprint gate.
DIGEST = "sha256:" + "a" * 64
ENVIRONMENT_ID = "env-codex-fixture"
DEFINITION = {"environmentNamespace": ENVIRONMENT_ID, "definitionId": "codex", "revision": "1"}
POINT_ID = "execution.harness.definitions"


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


def live_provider(view):
    """The retired factory product: a live provider wired to one owner view."""
    return CodexRuntimeProvider(definition_ref=DEFINITION, implementation_digest=DIGEST,
                                unit_records=view.records, projection=ready_projection(),
                                verifier=view.verifier,
                                channel_factory=SimpleNamespace(open=lambda *a, **k: None))


class Policy:
    """Catalog access policy: registration may read, never invoke."""

    def admit_object_access(self, principal, obj, permission):
        return True

    def admit_invoke(self, *args):
        raise AssertionError("registration cannot mint authority")


def catalog():
    return HarnessCatalog(ENVIRONMENT_ID, policy=Policy(), principal_scope="controlled")


def context(*, bound=True):
    """One catalog binding; `bound=False` states an absent catalog explicitly."""
    return ServerPluginContext(
        plugin_id="codex", data_root=None,
        ports={"execution.harness.catalog": catalog() if bound else None})


def declaration(*, observer=None):
    """The frozen definition the deployment binds; never a live owner."""
    if observer is None:
        def observer(installation_ref):
            return HarnessInstallationObservation("present")
    return HarnessDefinitionDeclaration(HarnessDefinitionDescriptor(
        "codex",
        {"environmentNamespace": ENVIRONMENT_ID, "definitionId": "codex", "revision": "1"},
        DIGEST, "acp/v1", "reviewed-adapter", backend_version="reviewed-native"), observer)


def registration_payload(registration):
    """The one contribution's frozen declaration, at the host definition point."""
    (contribution,) = registration.contributions.contributions
    assert contribution.point_id == POINT_ID
    assert contribution.api_version == HARNESS_DEFINITION_VERSION
    assert contribution.required is True
    return contribution.payload


def test_registration_carries_the_frozen_declaration_metadata():
    frozen = declaration()
    registration = CodexServerPlugin(frozen).build(context())
    payload = registration_payload(registration)
    # The native host contribution carries the frozen declaration opaquely.
    assert type(payload) is tuple and payload == (frozen,)
    descriptor = frozen.descriptor
    assert descriptor.provider_id == "codex"
    assert dict(descriptor.definition_ref) == DEFINITION
    assert descriptor.implementation_digest == DIGEST
    assert descriptor.protocol_id == "acp/v1"
    assert descriptor.adapter_version == "reviewed-adapter"
    assert descriptor.backend_version == "reviewed-native"


def test_registration_never_carries_a_live_owner_or_provider():
    """Only frozen declarations travel; a provider/records/verifier never does."""
    frozen = declaration()
    payload = registration_payload(CodexServerPlugin(frozen).build(context()))
    view = fresh_view()
    provider = live_provider(view)
    assert all(isinstance(item, HarnessDefinitionDeclaration) for item in payload)
    assert not any(hasattr(item, "records") or hasattr(item, "verifier") for item in payload)
    assert payload[0] not in (provider, view, view.records, view.verifier)


def test_registration_does_not_require_a_live_owner():
    assert CodexServerPlugin(declaration()).build(context()).contributions is not None


@pytest.mark.parametrize("field", ["records", "verifier"])
def test_substituted_owner_records_or_verifier_is_refused(field):
    view = fresh_view()
    setattr(view, field, object())
    with pytest.raises(TypeError, match="frozen Codex Harness definition"):
        CodexServerPlugin(view)


def test_live_owner_or_old_provider_factory_cannot_register_as_a_definition():
    view = fresh_view()
    provider = live_provider(view)
    for value in (provider, view, lambda *a, **k: provider):
        with pytest.raises(TypeError, match="frozen Codex Harness definition"):
            CodexServerPlugin(value)


def test_non_declaration_is_refused():
    for value in (None, object(), lambda *a, **k: None):
        with pytest.raises(TypeError, match="frozen Codex Harness definition"):
            CodexServerPlugin(value)


def test_missing_original_catalog_refuses_before_registration():
    with pytest.raises(GuaranteeUnavailableError, match="original Harness catalog"):
        CodexServerPlugin(declaration()).build(context(bound=False))
    with pytest.raises(GuaranteeUnavailableError, match="original Harness catalog"):
        CodexServerPlugin(declaration()).build(
            ServerPluginContext(plugin_id="codex", data_root=None, ports={}))
