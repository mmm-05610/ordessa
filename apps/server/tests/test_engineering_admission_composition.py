"""Original assembly identity and refusal; no synthetic reviewer qualification."""
from pathlib import Path
import hashlib

import pytest
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.consent import ConsentPolicyRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.models.identity import Scope as EngineeringScope
from ordessa_server.composition.engineering_admission import assemble_engineering_admission
from ordessa_interfaces.system_access.access_control.authentication import AccessGrant, InstanceAccessAuthority
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess

SCOPE = Scope('assembly-realm', 'assembly-project')
OPERATION = 'engineering.notices.publish'


class UnavailableOwner:
    """Deliberate refusal, never an admitted review or management permission."""
    def guard_management(self, *args):
        raise ApplicationError('METHOD_MANAGEMENT_UNAVAILABLE')
    def resolve_bindings(self, *args):
        raise ApplicationError('METHOD_TARGET_BINDINGS_UNAVAILABLE')
    def verify_response(self, *args, **kwargs):
        raise ApplicationError('REVIEW_SOURCE_AUTHORITY_UNAVAILABLE')


def inputs():
    raw = (Path(__file__).resolve().parents[3]/'methods/incremental-engineering/policies/product-chat-confirmation.v1.yaml').read_bytes()
    policy = ConsentPolicyRef('ordessa.product.v1.chat-attested-confirmation', 1,
        Digest('sha256', hashlib.sha256(raw).hexdigest()))
    refusal = UnavailableOwner()
    def intent_factory(controls, bindings):
        def unavailable(*args):
            raise ApplicationError('CONFIRMATION_AUTHORITY_UNAVAILABLE')
        return unavailable
    return dict(management=refusal, bindings=refusal, reviewer_source=refusal,
        policy_bytes=raw, policy_ref=policy, intent_guard_factory=intent_factory)


@pytest.mark.parametrize('missing,code', [
    ('management','METHOD_MANAGEMENT_UNAVAILABLE'),
    ('bindings','METHOD_TARGET_BINDINGS_UNAVAILABLE'),
    ('reviewer_source','REVIEW_SOURCE_AUTHORITY_UNAVAILABLE'),
    ('intent_guard_factory','CONFIRMATION_AUTHORITY_UNAVAILABLE'),
])
def test_missing_owner_refuses_before_any_state_or_permission(missing, code, tmp_path):
    arguments = inputs()
    arguments[missing] = (lambda controls, bindings: None) if missing == 'intent_guard_factory' else None
    with pytest.raises(ApplicationError, match=code):
        if missing == 'intent_guard_factory':
            # A supplied owner factory must produce a complete usable guard.
            library = EngineeringLibrary.create((tmp_path/'original.sqlite').resolve(),
                library_id='controlled-negative', schema_version=10)
            try:
                assemble_engineering_admission(SQLiteUoWFactory(library), None, SCOPE, **arguments)
            finally:
                library.close()
        else:
            assemble_engineering_admission(None, None, SCOPE, **arguments)


def test_original_library_composed_without_automatic_adoption_or_grants(tmp_path):
    library = EngineeringLibrary.create((tmp_path/'original.sqlite').resolve(),
        library_id='controlled-assembly', schema_version=10)
    try:
        factory = SQLiteUoWFactory(library)
        authority = InstanceAccessAuthority(lambda: 'controlled-temporary-token',
            principal_id='registered-main-agent', legacy_principal=None,
            grants=(AccessGrant(SCOPE, (OPERATION,)),))
        access = EngineeringCommandAccess(authority)
        caller = authority.authenticate('Bearer controlled-temporary-token')
        arguments = inputs()
        assembly = assemble_engineering_admission(factory, access, SCOPE, **arguments)
        assert assembly.methods.factory is factory
        assert assembly.methods.snapshots.library is library
        assert assembly.method_control.factory is factory
        assert assembly.application_ports.review_admission.factory is factory
        assert assembly.application_ports.review_admission.methods is assembly.method_control
        acceptance = assembly.application_ports.acceptance_admission
        assert acceptance.factory is factory
        assert acceptance.methods is assembly.method_control
        assert acceptance.bindings is arguments['bindings']
        assert callable(assembly.application_ports.conversation_admission.guard_intent)
        assert assembly.application_ports.blobs.library is library
        with factory.begin(EngineeringScope(SCOPE.realm_id, SCOPE.project_id), 'read') as uow:
            with pytest.raises(ApplicationError, match='METHOD_SELECTION_UNAVAILABLE'):
                uow.methods.selected()
        with access.admit(caller, SCOPE, OPERATION, request_id='read', trace_id='read') as context:
            with pytest.raises(ApplicationError, match='METHOD_SELECTION_UNAVAILABLE'):
                with assembly.method_control.guard_selected(context):
                    pytest.fail('assembly selected a method')
            with pytest.raises(ApplicationError, match='ACCESS_AUTHORITY_UNAVAILABLE'):
                access.require(context, 'engineering.methods.adopt')
    finally:
        library.close()
