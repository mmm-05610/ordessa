"""Pre-Proposal data ingress on original Profile/Environment owners.

The fingerprint/installation in selection_inputs are controlled test inputs.
These cases read native configuration; no Unit, model, method or Work is run.
"""
from ordessa_units.bindings.profile_admission import UnitProfileAdmission
import pytest

from ordessa_agents.profiles import ProfileService, encode_revision_ref
from ordessa_units.public import composed_profile_service
from ordessa_server.composition.product_runtime import build_product_runtime
from ordessa_server.composition.product_user_configuration import (
    ProductUserConfigurationError, resolve_unbound_product_user_configuration,
)
from test_pi_execution_selection import selection_inputs


def _configuration(selection):
    return {
        "version": 1,
        "piSelection": {
            "agentId": selection.agent_id,
            "profileRevision": encode_revision_ref(selection.profile_revision),
            "environment": {"id": selection.environment_id,
                            "provider": selection.environment_provider,
                            "isolation": selection.environment_isolation,
                            "sharing": selection.sharing},
            "model": {"declarationId": selection.model_declaration_id,
                      "provider": selection.provider, "model": selection.model},
        },
        "engineering": {"proposalRef": None, "phases": None, "materialSubmissions": []},
    }


def _launch(selection):
    return {key: getattr(selection, key) for key in
            ("bridge_executable", "bridge_sha256", "pi_executable", "credential_source")}


def test_unbound_ingress_reads_persisted_original_native_selection_before_method_or_proposal(selection_inputs):
    selection, ports, calls, instance, root = selection_inputs
    runtime = build_product_runtime(root, pi_selection=selection, pi_ports=ports)
    try:
        context = runtime.unit_runtime.context
        profiles = composed_profile_service(context)
        before = profiles.get_revision(selection.profile_revision)
        resolved = resolve_unbound_product_user_configuration(
            _configuration(selection), profile_service=profiles,
            environments=ports.environments, runtime=runtime,
            project_id="test-project", model_catalogue=ports.model_catalogue,
            trusted_launch=_launch(selection))
        assert resolved.pi_selection == selection
        assert resolved.proposal_ref is None and resolved.phases is None
        assert resolved.material_submissions == ()
        assert profiles.get_revision(selection.profile_revision) == before
        assert len(calls) == 1 and instance.snapshot.active_uses == 0
        assert runtime.units.list() == ()
    finally:
        runtime.stop()


@pytest.mark.parametrize("field,value", [("proposalRef", {}), ("phases", [])])
def test_bootstrap_reader_refuses_partial_null_without_selecting_native_owner(selection_inputs, field, value):
    selection, ports, calls, instance, root = selection_inputs
    runtime = build_product_runtime(root, pi_selection=selection, pi_ports=ports)
    try:
        document = _configuration(selection)
        document["engineering"][field] = value
        with pytest.raises(ProductUserConfigurationError, match="paired null"):
            resolve_unbound_product_user_configuration(
                document, profile_service=composed_profile_service(runtime.unit_runtime.context),
                environments=ports.environments, runtime=runtime,
                project_id="test-project", model_catalogue=ports.model_catalogue,
                trusted_launch=_launch(selection))
        assert len(calls) == 1 and instance.snapshot.active_uses == 0
        assert runtime.units.list() == ()
    finally:
        runtime.stop()


def test_bootstrap_reader_keeps_profile_namespace_guard(selection_inputs):
    selection, ports, calls, instance, root = selection_inputs
    runtime = build_product_runtime(root, pi_selection=selection, pi_ports=ports)
    try:
        document = _configuration(selection)
        document["piSelection"]["profileRevision"]["environmentNamespace"] = "another-realm"
        with pytest.raises(ProductUserConfigurationError, match="another original Environment"):
            resolve_unbound_product_user_configuration(
                document, profile_service=composed_profile_service(runtime.unit_runtime.context),
                environments=ports.environments, runtime=runtime,
                project_id="test-project", model_catalogue=ports.model_catalogue,
                trusted_launch=_launch(selection))
        assert len(calls) == 1 and instance.snapshot.active_uses == 0
    finally:
        runtime.stop()


def test_bootstrap_reader_rejects_separate_profile_view_even_with_same_namespace(selection_inputs):
    selection, ports, calls, instance, root = selection_inputs
    runtime = build_product_runtime(root, pi_selection=selection, pi_ports=ports)
    try:
        context = runtime.unit_runtime.context
        other_view = ProfileService(UnitProfileAdmission(context))
        assert other_view.environment_namespace == context.environment_namespace
        with pytest.raises(ProductUserConfigurationError, match="differs from the original Product owner"):
            resolve_unbound_product_user_configuration(
                _configuration(selection), profile_service=other_view,
                environments=ports.environments, runtime=runtime,
                project_id="test-project", model_catalogue=ports.model_catalogue,
                trusted_launch=_launch(selection))
        assert len(calls) == 1 and instance.snapshot.active_uses == 0
    finally:
        runtime.stop()
