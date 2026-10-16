"""C: production owner projection reads only through ``owner_read_*`` reads.

Real temporary SQLite journal with the family's records owner; no invocation
is consumed by any projection read, no ticket issued, no effect permission
created. Unobserved start correlations and foreign contexts are typed-refused;
a copied reference never becomes a read permission.
"""
import pytest

import claude_production_fixture as fx
from ordessa_harness_claude_code.owner_projection import (
    ClaudeOwnerUnitProjection, ClaudeProjectionRefused,
)

UNIT_FIELDS = {"environmentNamespace", "unitId", "ownerProviderRef", "sourceRevision"}


def substrate(tmp_path):
    parts = fx.family_core_parts(tmp_path)
    projection = parts["projection"]
    unit = parts["unit"]
    return parts, projection, unit


def test_owner_reads_consume_no_invocation_and_binds_whole_identity(tmp_path):
    parts, projection, unit = substrate(tmp_path)
    before = len(parts["issuer"]._issued)
    read = projection.read_unit(unit.public_ref)
    assert fx.same_reference(read.public_ref, unit.public_ref)
    assert read.configuration_target_ref == unit.configuration_target_ref
    assert len(parts["issuer"]._issued) == before  # nothing consumable was touched
    session = projection.read_session(unit.public_ref)
    assert session.state == "notCreated"
    confirmation = projection.read_unit_confirmation(unit.public_ref)
    assert confirmation.state == "notCreated"


def test_mapped_reference_is_never_a_permission(tmp_path):
    parts, projection, unit = substrate(tmp_path)
    forged = dict(unit.public_ref, sourceRevision="forged-source")
    with pytest.raises(ClaudeProjectionRefused, match="differs from original owner source"):
        projection.read_unit(forged)


def test_moved_owner_or_environment_reference_refused(tmp_path):
    parts, projection, unit = substrate(tmp_path)
    moved = dict(unit.public_ref)
    moved["ownerProviderRef"] = dict(moved["ownerProviderRef"], providerId="pi")
    with pytest.raises(ClaudeProjectionRefused, match="differs from original owner source"):
        projection.read_unit(moved)


def test_verified_facts_mapping_is_never_an_opaque_context(tmp_path):
    parts, projection, unit = substrate(tmp_path)
    with pytest.raises(ClaudeProjectionRefused, match="opaque invocation"):
        projection.read_unit(unit.public_ref, {"query": True})


def test_unobserved_creation_correlation_is_never_resolved_from_latest_state(tmp_path):
    parts, projection, unit = substrate(tmp_path)
    with pytest.raises(ClaudeProjectionRefused, match="not observed by this projection owner"):
        projection.resolve_original_start("start-correlation", None)


def test_registered_start_correlation_resolves_the_same_unit(tmp_path):
    parts, projection, unit = substrate(tmp_path)
    projection.register_original_start(unit, '{"operationRef":"flow-operation"}')
    resolved = projection.resolve_original_start('{"operationRef":"flow-operation"}', None)
    assert fx.same_reference(resolved.public_ref, unit.public_ref)
    (tmp_path / "other").mkdir()
    other = fx.family_core_parts(tmp_path / "other")["unit"]
    with pytest.raises(ClaudeProjectionRefused, match="belongs to another unit"):
        projection.register_original_start(other, '{"operationRef":"flow-operation"}')


def test_publication_facts_require_the_owner_port_and_seal_references(tmp_path):
    parts, projection, unit = substrate(tmp_path)
    with pytest.raises(ClaudeProjectionRefused, match="publication owner is absent"):
        bare = ClaudeOwnerUnitProjection(parts["records"], verifier=parts["records"].verifier,
                                         publication_owner=None)
        bare.publication_facts(unit.public_ref)
    facts = projection.publication_facts(unit.public_ref)
    assert facts["managementEpoch"] == 0 and facts["ownership"] == "owned"
    assert fx.same_reference(facts["configurationTargetRef"], unit.configuration_target_ref)
    assert facts["sourceRevision"].startswith("native-owner-observation-")
    bad_owner = lambda unit_, binding: {"evidenceRef": "owner-x"}  # missing directory binding
    broken = ClaudeOwnerUnitProjection(parts["records"], verifier=parts["records"].verifier,
                                       publication_owner=bad_owner)
    with pytest.raises(ClaudeProjectionRefused, match="references differ"):
        broken.publication_facts(unit.public_ref)


def test_authority_hooks_require_explicit_deployment_composition(tmp_path):
    parts, projection, unit = substrate(tmp_path)
    facts = {"targetRef": fx.NODE}
    for name in ("start_authority", "configuration_authority"):
        bare = ClaudeOwnerUnitProjection(parts["records"], verifier=parts["records"].verifier,
                                         publication_owner=lambda *a: {})
        hook = getattr(bare, "revalidate_" + ("start" if name == "start_authority" else "configuration"))
        with pytest.raises(ClaudeProjectionRefused, match="owner is absent"):
            hook(unit, facts)
    with pytest.raises(ClaudeProjectionRefused, match="preparation authority owner is absent"):
        ClaudeOwnerUnitProjection(parts["records"], verifier=parts["records"].verifier,
                                  publication_owner=lambda *a: {}).verify_preparation({}, {})


def test_projection_requires_the_records_owner_reads(tmp_path):
    parts, projection, unit = substrate(tmp_path)
    class Idle:
        pass
    with pytest.raises(ClaudeProjectionRefused, match="owner reads"):
        ClaudeOwnerUnitProjection(Idle(), verifier=object())
    with pytest.raises(ClaudeProjectionRefused, match="records owner reads"):
        ClaudeOwnerUnitProjection(object(), verifier=parts["records"].verifier)
