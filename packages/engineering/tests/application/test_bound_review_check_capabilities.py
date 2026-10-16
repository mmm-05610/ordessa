"""Bound capability descriptions come only from typed original review routes.

The DB/method-control owner is real SQLite. Unit reviewer authority, records,
and bindings below are explicit synthetic constructor guards: this tests route
selection, not production registration, reviewer qualification, or a Grant.
"""
from types import SimpleNamespace

import pytest

from test_invariant_checks import invariant_source
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.api import bound_review_check_capabilities
from ordessa_engineering.application.orchestration.check_capabilities import (
    invariant_review_check_capabilities,
    mechanical_review_check_capabilities,
)
from ordessa_engineering.application.orchestration.decision_checks import (
    GenericDecisionCheckSource, generic_decision_check_capability,
)
from ordessa_engineering.application.orchestration.unit_review import UnitReviewCheckSource
from ordessa_engineering.application.usecases.reviews.admission import EngineeringReviewAdmission
from ordessa_engineering.application.usecases.reviews.mechanical import MechanicalReviewCheckSource
from ordessa_engineering.application.usecases.reviews.mixed import MixedReviewerSource
from ordessa_engineering.application.usecases.reviews.invariants import (
    DeclaredInvariantReviewCheckSource,
)
from test_proposal_usecases import SCOPE


def _routes(source, *, mapping_mutation=None, authority=True, wrong_factory=False):
    factory, controls, blobs = source.factory, source.methods, source.blobs
    mechanical = MechanicalReviewCheckSource(factory, controls, blobs)
    invariant = source
    records = SimpleNamespace(acp_turn_query_digest=lambda *args: None,
        query_acp_turn=lambda *args, **kwargs: None)
    bindings = SimpleNamespace(resolve_unit_review=lambda *args, **kwargs: None,
        decode_response=lambda *args, **kwargs: None,
        resolve_record_request=lambda *args, **kwargs: None)
    unit_authority = SimpleNamespace(guard_unit_reviewer=lambda *args, **kwargs: None)
    unit = UnitReviewCheckSource(factory, controls, records, blobs,
        bindings=bindings, reviewer_authority=unit_authority)
    generic = GenericDecisionCheckSource(unit)
    if wrong_factory:
        mechanical = object.__new__(MechanicalReviewCheckSource)
        mechanical.factory = object()

    descriptors = (
        mechanical_review_check_capabilities().capabilities
        + invariant_review_check_capabilities().capabilities
        + (generic_decision_check_capability(),)
    )
    ids = {'mechanical': mechanical, 'invariant': invariant, 'generic': generic}
    mapping = {}
    for descriptor in descriptors:
        source_id = ('mechanical' if descriptor in mechanical_review_check_capabilities().capabilities
                     else 'invariant' if descriptor in invariant_review_check_capabilities().capabilities
                     else 'generic')
        mapping[(descriptor.capability_id, descriptor.interface_version)] = source_id
    if mapping_mutation == 'unmapped':
        mapping[(descriptors[0].capability_id, descriptors[0].interface_version)] = 'absent-source'
    elif mapping_mutation == 'wrong-kind':
        schema = next(item for item in descriptors
                      if item.capability_id == 'ordessa.schema.validate')
        mapping[(schema.capability_id, schema.interface_version)] = 'mechanical'
    access = SimpleNamespace(authority=SimpleNamespace(principal_id='selected-principal'))
    reviewer = (SimpleNamespace(access=access, principal_id='selected-principal',
        scope=SCOPE, guard_verification=lambda *args, **kwargs: None)
        if authority else None)
    mixed = MixedReviewerSource(factory, controls, blobs, sources=ids,
        source_for_capability=mapping, reviewer_authority=reviewer)
    admission = EngineeringReviewAdmission(factory, controls, None, mixed)
    return admission, descriptors, access


def _bound(admission, access):
    return bound_review_check_capabilities(admission,
        expected_factory=admission.factory, expected_access=access,
        expected_scope=SCOPE)


def test_only_exactly_bound_typed_mechanical_invariant_and_generic_routes_are_described(
        invariant_source):
    source, *_ = invariant_source
    admission, expected, access = _routes(source)
    actual = _bound(admission, access)
    assert actual.capabilities == expected
    assert {item.capability_id for item in actual.capabilities} == {
        'ordessa.sources.integrity', 'ordessa.claims.coverage',
        'ordessa.schema.validate', 'ordessa.submission.binding',
        'ordessa.decision.evaluate',
    }


@pytest.mark.parametrize('mutation', ['unmapped', 'wrong-kind'])
def test_missing_or_wrong_kind_mapping_omits_unavailable_capability(invariant_source, mutation):
    source, *_ = invariant_source
    admission, descriptors, access = _routes(source, mapping_mutation=mutation)
    result = _bound(admission, access)
    if mutation == 'unmapped':
        missing = descriptors[0]
    else:
        missing = next(item for item in descriptors
                       if item.capability_id == 'ordessa.schema.validate')
    assert missing not in result.capabilities
    actual_keys = {(item.capability_id, item.kind, item.interface_version, item.contract_digest)
                   for item in result.capabilities}
    expected_keys = {(item.capability_id, item.kind, item.interface_version, item.contract_digest)
                     for item in descriptors}
    assert actual_keys <= expected_keys


def test_wrong_factory_on_a_typed_source_refuses(invariant_source):
    source, *_ = invariant_source
    admission, _, access = _routes(source, wrong_factory=True)
    with pytest.raises(ApplicationError, match='REVIEW_SOURCE_AUTHORITY_MISMATCH'):
        _bound(admission, access)


def test_missing_composite_authority_and_serialized_admission_refuse(invariant_source):
    source, *_ = invariant_source
    admission, _, access = _routes(source, authority=False)
    with pytest.raises(ApplicationError, match='MIXED_REVIEWER_AUTHORITY_UNAVAILABLE'):
        _bound(admission, access)

    typed, _, access = _routes(source)
    detached = SimpleNamespace(factory=typed.factory, source=typed.source)
    with pytest.raises(ApplicationError, match='REVIEW_SOURCE_AUTHORITY_MISMATCH'):
        _bound(detached, access)


def test_mixed_source_factory_must_match_original_admission(invariant_source):
    source, *_ = invariant_source
    admission, _, access = _routes(source)
    # Keep the genuine typed source objects and mapping, but mutate the mixed
    # wrapper's claimed factory to prove the public binder rechecks its owner.
    admission.source.factory = object()
    with pytest.raises(ApplicationError, match='REVIEW_SOURCE_AUTHORITY_MISMATCH'):
        _bound(admission, access)


@pytest.mark.parametrize('mutation', ['factory', 'access', 'scope', 'principal', 'guard'])
def test_bound_reader_refuses_foreign_active_selection(invariant_source, mutation):
    source, *_ = invariant_source
    admission, _, access = _routes(source)
    authority = admission.source.authority
    expected_factory = admission.factory
    expected_scope = SCOPE
    if mutation == 'factory':
        expected_factory = object()
    elif mutation == 'access':
        access = SimpleNamespace(authority=SimpleNamespace(principal_id='selected-principal'))
    elif mutation == 'scope':
        expected_scope = SimpleNamespace(realm_id='foreign-realm', project_id=SCOPE.project_id)
    elif mutation == 'principal':
        authority.principal_id = 'foreign-principal'
    else:
        authority.guard_verification = None
    with pytest.raises(ApplicationError, match='REVIEW_SOURCE_AUTHORITY_MISMATCH'):
        bound_review_check_capabilities(admission, expected_factory=expected_factory,
            expected_access=access, expected_scope=expected_scope)


def test_bound_reader_refuses_generic_route_with_missing_native_ports(invariant_source):
    source, *_ = invariant_source
    admission, _, access = _routes(source)
    admission.source.sources['generic'].source.records = object()
    with pytest.raises(ApplicationError, match='REVIEW_SOURCE_AUTHORITY_MISMATCH'):
        _bound(admission, access)
