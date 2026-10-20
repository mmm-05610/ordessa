"""Actual plugin registration reads original finite descriptors; no fixture promotion."""
from pathlib import Path
import json
import pytest
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.method_bridge import command_capabilities
from ordessa_server.composition.engineering import EngineeringServerPlugin
from ordessa_server.composition.engineering_capability_catalog import RegisteredEngineeringCommandCatalog
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary


def test_unregistered_and_disposed_catalog_refuses(tmp_path):
    authority=InstanceAccessAuthority(lambda:'synthetic-token',principal_id='synthetic-registry',legacy_principal=None,grants=())
    path=tmp_path/'library.sqlite';library=EngineeringLibrary.create(path.resolve(),library_id='catalog-fixture',schema_version=10);library.close()
    plugin=EngineeringServerPlugin(path=path,library_id='catalog-fixture',scope=Scope('r','p'),authority_resolver=lambda:authority)
    reader=plugin.capability_catalog()
    with pytest.raises(ApplicationError,match='CAPABILITY_AUTHORITY_UNAVAILABLE'):reader.read_current()
    registration=plugin.build(None)
    try:
        actual=reader.read_current();original={d.capability_id:d for d in command_capabilities().capabilities}
        assert actual.trust_class=='host' and actual.registry_snapshot_ref.startswith('sha256:')
        assert {d.capability_id for d in actual.capabilities}=={'engineering.artifacts.create','engineering.artifacts.append_revision','engineering.proposals.create'}
        assert all(d==original[d.capability_id] for d in actual.capabilities)
        # Real finite catalog remains incompatible with the exact full2.4 requires.
        root=Path(__file__).resolve().parents[3]
        from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
        from ordessa_engineering.methods.loading.loader import load_method
        from ordessa_engineering.methods.definitions.models import MethodSource
        from ordessa_engineering.methods import compile_method
        candidate=root/'methods/incremental-engineering/candidates/2.4.0'
        assert json.loads((candidate/'contracts/capability-catalog.json').read_bytes())['fixture_only'] is True
        loaded=load_method(MethodSource(candidate),FileResourceReader());assert loaded.ok
        compiled=compile_method(loaded.value,actual,'ordessa.methods/v2')
        assert not compiled.ok  # No invented missing capabilities or version rewriting.
    finally:registration.disposal()
    with pytest.raises(ApplicationError,match='CAPABILITY_AUTHORITY_UNAVAILABLE'):reader.read_current()


def test_catalog_consumes_bound_owner_reader_and_intersects_installed_callables(tmp_path,monkeypatch):
    from ordessa_engineering.application.api import EngineeringService

    authority=InstanceAccessAuthority(lambda:'bound-reader-token',principal_id='bound-reader',legacy_principal=None,grants=())
    path=tmp_path/'bound-reader.sqlite'
    library=EngineeringLibrary.create(path.resolve(),library_id='bound-reader-fixture',schema_version=10)
    library.close()
    plugin=EngineeringServerPlugin(path=path,library_id='bound-reader-fixture',scope=Scope('r','p'),
        authority_resolver=lambda:authority)
    original=EngineeringService.bound_operation_capabilities
    observations=[]

    def observed_bound_reader(service):
        result=original(service)
        observations.append((service,result))
        return result

    monkeypatch.setattr(EngineeringService,'bound_operation_capabilities',observed_bound_reader)
    registration=plugin.build(None)
    try:
        actual=plugin.capability_catalog().read_current()
        binding=plugin._binding_for(authority)
        assert len(observations)>=2
        assert all(service is binding.service for service,_ in observations)
        installed={method.method_id for method in registration.methods
            if method.owner=='ordessa.engineering' and callable(method.handler)}
        expected=tuple(descriptor for descriptor in observations[-1][1].capabilities
            if descriptor.capability_id in installed)
        assert actual.capabilities==expected
        assert {descriptor.capability_id for descriptor in actual.capabilities}=={
            'engineering.artifacts.create','engineering.artifacts.append_revision',
            'engineering.proposals.create'}
        assert actual.trust_class=='host'
    finally:
        registration.disposal()


def test_nonbound_grant_and_run_ports_do_not_promote_routes(tmp_path):
    from ordessa_system_access_bindings.engineering_wire import EngineeringApplicationPorts
    authority=InstanceAccessAuthority(lambda:'synthetic-token',principal_id='partial-registry',legacy_principal=None,grants=())
    path=tmp_path/'library.sqlite';library=EngineeringLibrary.create(path.resolve(),library_id='partial-catalog-fixture',schema_version=10);library.close()
    def ports_factory(factory, access, scope):
        from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
        from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
        from ordessa_engineering.application.usecases.reviews.admission import EngineeringReviewAdmission
        methods=SQLiteMethodControl(factory,SQLiteSnapshotStore(factory.library))
        admission=EngineeringReviewAdmission(factory,methods,object(),None)
        return EngineeringApplicationPorts(conversation_admission=object(), review_admission=admission,
            current_wait_bindings=object())
    plugin=EngineeringServerPlugin(path=path,library_id='partial-catalog-fixture',scope=Scope('r','p'),
        authority_resolver=lambda:authority,application_ports_factory=ports_factory)
    registration=plugin.build(None)
    try:
        actual=plugin.capability_catalog().read_current()
        ids={descriptor.capability_id for descriptor in actual.capabilities}
        assert ids=={'engineering.artifacts.create','engineering.artifacts.append_revision','engineering.proposals.create'}
        assert actual.trust_class=='host'
    finally:registration.disposal()


def _review_catalog_plugin(tmp_path, *, library_id, authority, foreign_authority):
    from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
    from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
    from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
    from ordessa_engineering.application.usecases.reviews.admission import EngineeringReviewAdmission
    from ordessa_engineering.application.usecases.reviews.mechanical import MechanicalReviewCheckSource
    from ordessa_engineering.application.usecases.reviews.mixed import MixedReviewerSource
    from ordessa_server.composition.engineering_mixed_review import OriginalCompositeReviewerAuthority
    from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
    from ordessa_system_access_bindings.engineering_wire import EngineeringApplicationPorts

    path=tmp_path/f'{library_id}.sqlite'
    library=EngineeringLibrary.create(path.resolve(),library_id=library_id,schema_version=10);library.close()

    def make_ports(*,foreign_authority=False):
        def ports_factory(factory, access, scope):
            methods=SQLiteMethodControl(factory,SQLiteSnapshotStore(factory.library))
            blobs=SQLiteBlobStore(factory.library)
            source_access=access
            if foreign_authority:
                source_access=EngineeringCommandAccess(InstanceAccessAuthority(
                    lambda:'foreign-token',principal_id='foreign-reviewer',legacy_principal=None,grants=()))
            reviewer=OriginalCompositeReviewerAuthority(source_access,scope=scope,
                principal_id=source_access.authority.principal_id,roles=('reviewer',))
            mechanical=MechanicalReviewCheckSource(factory,methods,blobs)
            source=MixedReviewerSource(factory,methods,blobs,
                sources={'mechanical':mechanical},
                source_for_capability={('ordessa.sources.integrity','1.0.0'):'mechanical',
                    ('ordessa.claims.coverage','1.0.0'):'mechanical'},
                reviewer_authority=reviewer)
            admission=EngineeringReviewAdmission(factory,methods,None,source)
            return EngineeringApplicationPorts(review_admission=admission,blobs=blobs)
        return ports_factory

    return EngineeringServerPlugin(path=path,library_id=library_id,scope=Scope('r','p'),
        authority_resolver=lambda:authority,
        application_ports_factory=make_ports(foreign_authority=foreign_authority))


def test_catalog_same_factory_review_source_positive_requires_expected_authority_api(tmp_path):
    authority=InstanceAccessAuthority(lambda:'synthetic-token',principal_id='review-catalog',legacy_principal=None,grants=())
    plugin=_review_catalog_plugin(tmp_path,library_id='review-catalog-fixture',authority=authority,
        foreign_authority=False)
    registration=plugin.build(None)
    try:
        ids={item.capability_id for item in plugin.capability_catalog().read_current().capabilities}
        assert {'ordessa.sources.integrity','ordessa.claims.coverage'} <= ids
        assert 'ordessa.decision.evaluate' not in ids
        assert 'ordessa.schema.validate' not in ids
        assert 'ordessa.submission.binding' not in ids
    finally:registration.disposal()


def test_catalog_foreign_review_authority_refuses_publication(tmp_path):
    authority=InstanceAccessAuthority(lambda:'synthetic-token',principal_id='review-catalog',legacy_principal=None,grants=())
    foreign_plugin=_review_catalog_plugin(tmp_path,library_id='foreign-review-catalog-fixture',
        authority=authority,foreign_authority=True)
    foreign_registration=foreign_plugin.build(None)
    try:
        with pytest.raises(ApplicationError,match='REVIEW_SOURCE_AUTHORITY_MISMATCH'):
            foreign_plugin.capability_catalog().read_current()
    finally:foreign_registration.disposal()


def test_wire_descriptor_or_fixture_dictionary_is_not_owner_catalog():
    with pytest.raises(ApplicationError,match='CAPABILITY_AUTHORITY_UNAVAILABLE'):
        RegisteredEngineeringCommandCatalog({'trust_class':'host','fixture_only':False})


def test_host_aggregation_keeps_registered_owner_contracts_and_refuses_fixtures(tmp_path):
    from ordessa_server.composition.engineering_capability_catalog import RegisteredHostCapabilityCatalog
    authority=InstanceAccessAuthority(lambda:'synthetic-token',principal_id='synthetic-registry',legacy_principal=None,grants=())
    path=tmp_path/'library.sqlite';library=EngineeringLibrary.create(path.resolve(),library_id='aggregate-fixture',schema_version=10);library.close()
    plugin=EngineeringServerPlugin(path=path,library_id='aggregate-fixture',scope=Scope('r','p'),authority_resolver=lambda:authority)
    registration=plugin.build(None)
    try:
        reader=plugin.capability_catalog();single=reader.read_current()
        aggregate=RegisteredHostCapabilityCatalog((reader,reader)).read_current()
        assert tuple(sorted(aggregate.capabilities,key=lambda d:d.capability_id))==tuple(sorted(single.capabilities,key=lambda d:d.capability_id)) and aggregate.trust_class=='host'
        with pytest.raises(ApplicationError,match='CAPABILITY_AUTHORITY_UNAVAILABLE'):
            RegisteredHostCapabilityCatalog(({'trust_class':'host'},))
    finally:registration.disposal()


def test_registered_publication_refuses_incomplete_real_catalog_without_selection(tmp_path):
    from ordessa_server.composition.engineering_method_management import RegisteredMethodPublication
    from ordessa_server.composition.engineering_capability_catalog import RegisteredHostCapabilityCatalog
    from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
    from ordessa_engineering.methods.definitions.models import MethodSource
    authority=InstanceAccessAuthority(lambda:'synthetic-token',principal_id='synthetic-registry',legacy_principal=None,grants=())
    path=tmp_path/'library.sqlite';library=EngineeringLibrary.create(path.resolve(),library_id='publication-fixture',schema_version=10);library.close()
    plugin=EngineeringServerPlugin(path=path,library_id='publication-fixture',scope=Scope('r','p'),authority_resolver=lambda:authority)
    registration=plugin.build(None)
    try:
        access=EngineeringCommandAccess(authority)
        publisher=RegisteredMethodPublication(plugin._factory,access,Scope('r','p'),
            RegisteredHostCapabilityCatalog((plugin.capability_catalog(),)))
        root=Path(__file__).resolve().parents[3]
        result=publisher.publish(MethodSource(root/'methods/incremental-engineering/candidates/2.4.0'),
            compiler_version='ordessa.methods/v2')
        assert not result.ok
        assert publisher.snapshots.get_digest('ordessa.incremental-engineering','2.4.0') is None
        from ordessa_engineering.domain.common.models.identity import Scope as EngineeringScope
        with plugin._factory.begin(EngineeringScope('r','p'),'read') as uow:
            with pytest.raises(ApplicationError,match='METHOD_SELECTION_UNAVAILABLE'):uow.methods.selected()
        with pytest.raises(ApplicationError,match='CAPABILITY_AUTHORITY_UNAVAILABLE'):
            RegisteredMethodPublication(plugin._factory,access,Scope('r','p'),{'trust_class':'host'})
    finally:registration.disposal()


def test_registered_publication_returns_original_domain_ref_and_same_store_can_read(tmp_path):
    import hashlib
    from ordessa_engineering.domain.artifacts.method_binding import MethodRef as DomainMethodRef
    from ordessa_engineering.methods.definitions.models import MethodSource, MethodRef as StoredMethodRef
    from ordessa_server.composition.engineering_method_management import RegisteredMethodPublication
    from ordessa_server.composition.engineering_capability_catalog import RegisteredHostCapabilityCatalog
    from ordessa_system_access_bindings.engineering import EngineeringCommandAccess

    authority=InstanceAccessAuthority(lambda:'publication-token',principal_id='publication-root',
        legacy_principal=None,grants=())
    path=tmp_path/'published.sqlite'
    library=EngineeringLibrary.create(path.resolve(),library_id='published-method-fixture',schema_version=10)
    library.close()
    scope=Scope('r','p')
    plugin=EngineeringServerPlugin(path=path,library_id='published-method-fixture',scope=scope,
        authority_resolver=lambda:authority)
    registration=plugin.build(None)
    try:
        catalog=RegisteredHostCapabilityCatalog((plugin.capability_catalog(),))
        actual=catalog.read_current()
        descriptor=next(item for item in actual.capabilities
            if item.capability_id=='engineering.artifacts.create')
        publisher=RegisteredMethodPublication(plugin._factory,EngineeringCommandAccess(authority),scope,catalog)
        source=tmp_path/'minimal-method'
        source.mkdir()
        workflow=json.dumps({"schema_version":1,"entry":"capture","context_slots":["kind","body"],
            "steps":[{"id":"capture","kind":"operation","operation":descriptor.capability_id,
                "inputs":{"kind":"kind","initial":"body"},
                "outcomes":{"completed":{"stop":"completed"},"rejected":{"stop":"rejected"}}}],
            "stop_outcomes":["completed","rejected"],"wait_kinds":[]}).encode()
        (source/'workflow.json').write_bytes(workflow)
        manifest={"schema_version":1,"method_id":"test.registered-publication",
            "release_version":"1.0.0","compiler_contract":"ordessa.methods/v1",
            "entry":{"resource":"workflow.main"},"resources":[{"id":"workflow.main",
                "kind":"workflow","path":"workflow.json","media_type":"application/json",
                "sha256":hashlib.sha256(workflow).hexdigest()}],"documents":[],
            "requires":[{key:getattr(descriptor,key) for key in
                ('capability_id','kind','interface_version','contract_digest')}]}
        (source/'method.yaml').write_text(json.dumps(manifest))

        result=publisher.publish(MethodSource(source),compiler_version='test.registered-publication/1')
        assert result.ok, result.error
        assert type(result.value) is DomainMethodRef
        assert result.value.method_id=='test.registered-publication'
        assert result.value.release_version=='1.0.0'
        stored_ref=StoredMethodRef(result.value.method_id,result.value.release_version,
            result.value.schema_version,result.value.snapshot_digest.hex)
        snapshot=publisher.snapshots.get(stored_ref)
        assert snapshot.ref==stored_ref
        assert publisher.snapshots.get_digest(result.value.method_id,result.value.release_version)==result.value.snapshot_digest.hex
    finally:
        registration.disposal()
