"""HarnessCatalog owns definition metadata without Kernel or plugin aggregates."""

from contextlib import contextmanager
from dataclasses import replace
from threading import RLock

import pytest

from ordessa_agents.harness.providers.registry.errors import (
    CatalogAdmissionRefused,
    CatalogUnavailable,
    CatalogIdentityConflict,
)
from ordessa_agents.harness.providers.registry import (
    AdmittedHarnessDefinition,
    HarnessAdmission,
    HarnessCatalog,
    HarnessDefinitionDeclaration,
    HarnessDefinitionDescriptor,
    HarnessInstallationObservation,
    harness_registration_snapshot,
)
from ordessa_units.admission.context import UnitAdmissionContext
from ordessa_agents.harness.definitions.errors import CoreDTOError


class Policy:
    allowed = True

    def admit_object_access(self, principal, obj, permission):
        assert (principal, obj, permission) == ("controlled", "env:agents.runtime", "read")
        return self.allowed

    def admit_invoke(self, *_args):
        raise AssertionError("metadata admission must not invoke Harness providers")


class MaterialCatalog:
    environment_namespace = "env"


class UsageStore:
    def __init__(self, *, held=False, available=True):
        self.held = held
        self.available = available

    @contextmanager
    def transaction(self):
        yield self

    def unresolved_provider_usages(self, namespace, owner_id, generation):
        assert (namespace, owner_id, generation) == ("env", "brand", 3)
        if not self.available:
            raise CatalogUnavailable("original provider Usage ledger unavailable")
        return ("usage-1",) if self.held else ()


def setup(*, observer=None, store=None):
    policy = Policy()
    calls = []

    def inspect(installation_ref):
        calls.append(installation_ref)
        assert dict(installation_ref) == {
            "environmentNamespace": "env",
            "installationId": "brand-installation",
            "sourceRevision": "b" * 64,
        }
        return HarnessInstallationObservation("present", native_version="1", version_verified=False)

    descriptor = HarnessDefinitionDescriptor(
        "brand",
        {"environmentNamespace": "env", "definitionId": "brand", "revision": "1"},
        "sha256:" + "a" * 64,
        "acp/v1",
        "reviewed-adapter",
        capabilities=("existingChannel",),
    )
    declaration = HarnessDefinitionDeclaration(descriptor, observer or inspect)
    store = store or UsageStore()
    lock = RLock()
    context_ref = {}
    catalog = HarnessCatalog(
        "env",
        policy=policy,
        principal_scope="controlled",
        admission_lock=lock,
        retirement_guard=lambda owner_id, generation: context_ref["context"].harness_provider_retirement_guard(
            owner_id, generation
        ),
    )
    context = UnitAdmissionContext(
        "env",
        store=store,
        policy=policy,
        fingerprint_port=object(),
        harness_catalog=catalog,
        material_catalog=MaterialCatalog(),
        principal_scope="controlled",
        admission_lock=lock,
    )
    context_ref["context"] = context
    return context, policy, declaration, calls, catalog, store


def stage(catalog, declaration, *, owner_id="brand", generation=3):
    return catalog.stage(
        owner_id,
        generation,
        "brand-installation",
        "b" * 64,
        (declaration,),
    )


def test_declaration_admission_uses_catalog_without_runtime_dispatch():
    context, _policy, declaration, calls, catalog, _store = setup()
    admission = HarnessAdmission(context)
    registration = stage(catalog, declaration)
    assert admission.list() == () and calls == []

    committed = registration.commit()
    assert len(committed) == 1 and type(committed[0]) is AdmittedHarnessDefinition
    with pytest.raises(CatalogAdmissionRefused):
        registration.commit()
    admitted = admission.describe(declaration.descriptor.definition_ref)
    assert admitted == committed[0] and admission.list() == (admitted,)
    assert admitted.provider_ref["contractVersion"] == "agent-runtime/2"
    assert admitted.provider_ref["generation"] == 3

    observed = admission.inspect_installation(declaration.descriptor.definition_ref)
    assert observed["installationState"] == "present"
    assert observed["runtimeReady"] == "unknown"
    assert observed["versionVerified"] is False and len(calls) == 1
    with pytest.raises(TypeError):
        admitted.descriptor.definition_ref["revision"] = "changed"


def test_missing_context_catalog_binding_refuses_discovery():
    with pytest.raises(CatalogUnavailable, match="context HarnessCatalog binding required"):
        HarnessAdmission(object())


def test_registration_rollback_releases_only_its_staged_batch():
    _context, _policy, declaration, _calls, catalog, _store = setup()
    registration = stage(catalog, declaration)
    registration.rollback()
    assert registration.state == "rolled_back" and catalog.list() == ()
    with pytest.raises(CatalogAdmissionRefused):
        registration.commit()
    assert len(stage(catalog, declaration).commit()) == 1


def test_instance_or_runtime_aggregate_cannot_be_a_declaration():
    for value in (object(), type("OldAggregate", (), {"start": lambda *args: None})()):
        with pytest.raises(CoreDTOError):
            harness_registration_snapshot(value)
    _context, _policy, declaration, _calls, catalog, _store = setup()
    object.__setattr__(declaration, "start", lambda *_args: None)
    with pytest.raises(CoreDTOError):
        stage(catalog, declaration)


def test_exact_definition_and_provider_identity_keep_original_batch_claims():
    _context, _policy, declaration, _calls, catalog, _store = setup()
    first = stage(catalog, declaration)
    # Same owner-generation is claimed at stage time, before either commit.
    with pytest.raises(CatalogAdmissionRefused):
        stage(catalog, declaration)

    # Changing provider identity or Mapping insertion order cannot evade the
    # exact definition claim while an earlier registration is staged.
    same_definition = HarnessDefinitionDeclaration(
        replace(declaration.descriptor, provider_id="another"), declaration.installation_observer
    )
    with pytest.raises(CatalogAdmissionRefused):
        stage(catalog, same_definition, owner_id="other")
    reordered = HarnessDefinitionDeclaration(
        replace(
            declaration.descriptor,
            provider_id="reordered",
            definition_ref=dict(reversed(list(declaration.descriptor.definition_ref.items()))),
        ),
        declaration.installation_observer,
    )
    with pytest.raises(CatalogAdmissionRefused):
        stage(catalog, reordered, owner_id="other-two")

    first.commit()
    assert catalog.list()[0].descriptor.provider_id == "brand"


def test_installation_owner_mutation_between_stage_and_commit_is_refused():
    _context, _policy, declaration, calls, catalog, _store = setup()
    registration = stage(catalog, declaration)
    object.__setattr__(declaration, "installation_observer", lambda _ref: HarnessInstallationObservation("unknown"))
    with pytest.raises(CatalogAdmissionRefused, match="declaration changed after staging"):
        registration.commit()
    assert registration.state == "unknown"
    with pytest.raises(CatalogAdmissionRefused):
        registration.commit()
    assert catalog.list() == () and calls == []


def test_foreign_namespace_and_revoked_observation_are_refused():
    context, policy, declaration, calls, catalog, _store = setup()
    foreign = HarnessDefinitionDeclaration(
        replace(
            declaration.descriptor,
            definition_ref={**dict(declaration.descriptor.definition_ref), "environmentNamespace": "foreign"},
        ),
        declaration.installation_observer,
    )
    with pytest.raises(CatalogIdentityConflict):
        stage(catalog, foreign)

    def revoke(_installation_ref):
        policy.allowed = False
        observed.append(True)
        return HarnessInstallationObservation("present")

    observed = []
    revoking = HarnessDefinitionDeclaration(declaration.descriptor, revoke)
    stage(catalog, revoking).commit()
    admission = HarnessAdmission(context)
    with pytest.raises(CatalogAdmissionRefused, match="discovery refused"):
        admission.inspect_installation(revoking.descriptor.definition_ref)
    assert observed == [True] and calls == []  # permission was revoked by the native observation


def test_draining_excludes_new_admission_and_preserves_retirement_usage_gate():
    store = UsageStore(held=True)
    context, _policy, declaration, calls, catalog, _store = setup(store=store)
    admitted, = stage(catalog, declaration).commit()
    admission = HarnessAdmission(context)
    catalog.drain("brand", 3)
    assert admission.list() == ()
    with pytest.raises(CatalogAdmissionRefused):
        admission.describe(declaration.descriptor.definition_ref)
    assert admission.describe_for_cleanup(
        declaration.descriptor.definition_ref, admitted.provider_ref
    ) == admitted

    with pytest.raises(CatalogUnavailable, match="Usage remains held"):
        catalog.retire("brand", 3)
    store.held = False
    catalog.retire("brand", 3)
    with pytest.raises(CatalogAdmissionRefused):
        admission.describe_for_cleanup(declaration.descriptor.definition_ref, admitted.provider_ref)
    assert calls == []
    catalog.close()


def test_missing_durable_usage_guarantee_refuses_retirement():
    store = UsageStore(available=False)
    context, _policy, declaration, calls, catalog, _store = setup(store=store)
    admitted, = stage(catalog, declaration).commit()
    catalog.drain("brand", 3)
    with pytest.raises(CatalogUnavailable, match="Usage ledger unavailable"):
        catalog.retire("brand", 3)
    assert HarnessAdmission(context).list() == ()
    assert HarnessAdmission(context).describe_for_cleanup(
        declaration.descriptor.definition_ref, admitted.provider_ref
    ) == admitted
    assert calls == []
