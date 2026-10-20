"""Formal product construction with original selected owners, no native/model call."""
import hashlib
import time
from pathlib import Path

import pytest
import yaml

from ordessa_engineering.application.api import ApplicationError, EXECUTION_DISPATCH
from ordessa_engineering.adapters.review_sources import ConfiguredReviewPhase
from ordessa_engineering.domain.approvals.consent import ConsentPolicyRef
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_interfaces.system_access.access_control.authentication import AccessGrant
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_server.composition.engineering import (
    DEFAULT_MACHINE_CAPABILITIES, EngineeringServerPlugin,
)
from ordessa_server.composition.engineering_capability_catalog import RegisteredHostCapabilityCatalog
from ordessa_server.composition.engineering_chat_confirmation import MainAgentChatConfirmation
from ordessa_server.composition.product_runtime import build_product_runtime
from ordessa_units.assembly import UnitRunPermission
from test_pi_execution_selection import selection_inputs


@pytest.mark.parametrize('report_selected', [False, True])
def test_formal_method_unit_callback_binds_actual_service_review_work_and_chat(tmp_path, report_selected):
    from dataclasses import replace
    selection, ports, _calls, environment, product_root = selection_inputs.__wrapped__(tmp_path)
    scope = Scope(selection.profile_revision.environment_namespace, "test-project")
    machine_capabilities = DEFAULT_MACHINE_CAPABILITIES
    actions = frozenset({"prepare", "start", "interaction", "stop", "release"})
    selected_permission = {}

    def permission_factory(*, runtime, admission_context, selection, environment_instance):
        authority = runtime.wire.identity_authority
        authority.replace_grants((AccessGrant(scope, tuple(dict.fromkeys((
            *("execution.units." + action for action in sorted(actions)),
            *machine_capabilities,
        )))),))
        principal = authority.authenticate("Bearer " + runtime.token)
        permission = UnitRunPermission(
            access_authority=authority, principal=principal, scope=scope,
            agent_id=selection.agent_id, profile_revision=selection.profile_revision,
            environment_identity=environment_instance.identity,
            root_directory=str(tmp_path / "local"), actions=actions,
            expires_at=time.time() + 120,
        )
        selected_permission['value'] = permission
        return permission

    def unavailable(*_args, **_kwargs):
        raise ApplicationError("UNIT_REVIEW_SOURCE_UNAVAILABLE")

    policy_path = Path(__file__).resolve().parents[3] / "methods/incremental-engineering/policies/product-chat-confirmation.v1.yaml"
    policy_bytes = policy_path.read_bytes()
    policy = yaml.safe_load(policy_bytes)
    policy_ref = ConsentPolicyRef(policy["policy_id"], policy["revision"],
        Digest("sha256", hashlib.sha256(policy_bytes).hexdigest()))
    proposal_ref = ProposalRef(scope.realm_id, scope.project_id,
        "selected-change", "selected-proposal", Digest("sha256", "a" * 64))
    method_options = {
        "proposal_ref": proposal_ref,
        "phases": (ConfiguredReviewPhase("source_review", ("reviewer",),
            workflow_node_id="source_review"),),
        "author_unit_resolver": unavailable,
        "invocation_resolver": unavailable,
        "unit_query_factory": unavailable,
        "confirmation_options": {
            "policy_bytes": policy_bytes, "policy_ref": policy_ref,
            "conversation_locator": "chat://controlled-formal-construction",
        },
    }
    if report_selected:
        # This explicit test node has no published Method. Construction only
        # binds the original reader; it does not invent a report declaration.
        method_options['report_phase_key'] = 'explicit-unpublished-report-node'
    runtime = build_product_runtime(
        product_root, pi_selection=selection,
        pi_ports=replace(ports, permission_factory=permission_factory,
            acp_turn_opt_in=report_selected),
        library_path=(tmp_path / "engineering.sqlite").resolve(),
        library_id="formal-method-unit-construction", scope=scope,
        create_library=True, schema_version=15,
        machine_capabilities=machine_capabilities,
        method_unit_options=method_options,
    )
    try:
        runtime.start()
        plugins = tuple(plugin for plugin in runtime.plugin_selection
            if type(plugin) is EngineeringServerPlugin)
        assert len(plugins) == 1
        plugin = plugins[0]
        binding = plugin._binding_for(runtime.wire.identity_authority)
        assert binding.access.authority is runtime.unit_execution_owner.permission.access_authority
        assert binding.ports.reviewer_assignments.records is runtime.unit_execution_owner.records
        assert binding.ports.review_admission.methods is binding.ports.current_wait_bindings.methods
        assert binding.ports.review_admission.bindings is binding.ports.current_wait_bindings.source.review_bindings
        assert binding.ports.blobs is binding.ports.current_wait_bindings.source.blobs
        # The formal graph has no real method-selected native prompt producer;
        # the canonical dispatch binder therefore stays absent.
        assert binding.ports.execution_dispatch_binder is None
        assert type(binding.ports.conversation_admission) is MainAgentChatConfirmation
        assert binding.ports.conversation_admission.factory is plugin._factory
        ids = {item.capability_id for item in RegisteredHostCapabilityCatalog(
            (plugin.capability_catalog(),)).read_current().capabilities}
        assert {
            "engineering.reviews.request", "engineering.reviews.record",
            "engineering.reviews.assign_reviewer", "engineering.reviews.revoke_reviewer",
            "engineering.work.start", "engineering.work.bind_inputs", "engineering.runs.resume",
            "engineering.notices.publish", "engineering.approvals.prepare_intent",
            "engineering.approvals.request", "engineering.approvals.record_conversation",
            "engineering.changes.apply", "engineering.packages.freeze",
            "ordessa.claims.coverage", "ordessa.sources.integrity", "ordessa.schema.validate",
            "ordessa.submission.binding", "ordessa.decision.evaluate",
        } <= ids
        assert 'engineering.executions.dispatch' not in ids
        assert ('engineering.acceptance.adopt' in ids) is report_selected
        assert ('engineering.submissions.record_report' in ids) is report_selected
        authorship = binding.ports.reviewer_assignments.authorship_source
        assert authorship.review_bindings is binding.ports.review_admission.bindings
        if report_selected:
            report = binding.ports.submission_report_source
            assert report.factory is plugin._factory
            assert report.methods is binding.ports.current_wait_bindings.methods
            assert report.blobs is binding.ports.blobs
            assert report.bindings.phase_key == method_options['report_phase_key']
            assert binding.ports.execution_records is runtime.unit_execution_owner.records
            assert callable(binding.ports.execution_query_factory)
            assert (binding.ports.execution_query_factory
                is binding.ports.current_wait_bindings.source.execution_query_factory)
            assert binding.ports.acceptance_admission.bindings is binding.ports.review_admission.bindings
            source = binding.ports.submission_source
            assert source.factory is plugin._factory
            assert source.method_runs is binding.ports.current_wait_bindings
            assert source.report_source is report
            assert source.records is runtime.unit_execution_owner.records
            assert source.execution_query_factory is binding.ports.execution_query_factory
        assert runtime.units is runtime.unit_execution_owner.manager
        assert environment.snapshot.active_uses == 0
        # Construction/callable catalog does not authenticate a reviewer or
        # imply real business inputs; the deliberately unavailable test source
        # refuses, and this test creates no Unit or execution/acceptance record.
        with pytest.raises(ApplicationError, match="UNIT_REVIEW_SOURCE_UNAVAILABLE"):
            binding.ports.reviewer_assignments.unit_query_factory(None, None, None, None,
                purpose="author")
    finally:
        runtime.stop()
    assert environment.snapshot.active_uses == 0


def test_formal_product_dispatch_binds_one_original_owner_graph_without_sending(tmp_path):
    """Opt-in construction binds canonical dispatch but performs no native call."""
    from dataclasses import replace

    selection, ports, _calls, environment, product_root = selection_inputs.__wrapped__(tmp_path)
    scope = Scope(selection.profile_revision.environment_namespace, "test-project")
    machine_capabilities = tuple(dict.fromkeys((
        *DEFAULT_MACHINE_CAPABILITIES, EXECUTION_DISPATCH,
    )))
    actions = frozenset({"prepare", "start", "interaction", "stop", "release"})
    selected_permission = {}
    prompt_calls = []

    def permission_factory(*, runtime, admission_context, selection, environment_instance):
        authority = runtime.wire.identity_authority
        authority.replace_grants((AccessGrant(scope, tuple(dict.fromkeys((
            *("execution.units." + action for action in sorted(actions)),
            *machine_capabilities,
        )))),))
        principal = authority.authenticate("Bearer " + runtime.token)
        permission = UnitRunPermission(
            access_authority=authority, principal=principal, scope=scope,
            agent_id=selection.agent_id, profile_revision=selection.profile_revision,
            environment_identity=environment_instance.identity,
            root_directory=str(tmp_path / "local"), actions=actions,
            expires_at=time.time() + 120,
        )
        selected_permission['value'] = permission
        return permission

    def unavailable(*_args, **_kwargs):
        raise ApplicationError("UNIT_REVIEW_SOURCE_UNAVAILABLE")

    def prompt_parameters(*args, **kwargs):
        # A real method-selected ACP parameter producer is intentionally not
        # supplied by this construction-only scenario. If invoked without an
        # actual selected method/Unit, fail closed; construction must not call it.
        prompt_calls.append((args, kwargs))
        raise ApplicationError("METHOD_SELECTED_PROMPT_UNAVAILABLE")

    policy_path = Path(__file__).resolve().parents[3] / "methods/incremental-engineering/policies/product-chat-confirmation.v1.yaml"
    policy_bytes = policy_path.read_bytes()
    policy = yaml.safe_load(policy_bytes)
    policy_ref = ConsentPolicyRef(policy["policy_id"], policy["revision"],
        Digest("sha256", hashlib.sha256(policy_bytes).hexdigest()))
    proposal_ref = ProposalRef(scope.realm_id, scope.project_id,
        "selected-change", "selected-proposal", Digest("sha256", "a" * 64))
    method_options = {
        "proposal_ref": proposal_ref,
        "phases": (ConfiguredReviewPhase("source_review", ("reviewer",),
            workflow_node_id="source_review"),),
        "author_unit_resolver": unavailable,
        "invocation_resolver": unavailable,
        "unit_query_factory": unavailable,
        "report_phase_key": "explicit-unpublished-report-node",
        "dispatch_prompt_parameters": prompt_parameters,
        "confirmation_options": {
            "policy_bytes": policy_bytes, "policy_ref": policy_ref,
            "conversation_locator": "chat://controlled-formal-construction",
        },
    }
    runtime = build_product_runtime(
        product_root, pi_selection=selection,
        pi_ports=replace(ports, permission_factory=permission_factory,
            acp_turn_opt_in=True, defer_effect_write_guard_factory=True),
        library_path=(tmp_path / "engineering.sqlite").resolve(),
        library_id="formal-dispatch-construction", scope=scope,
        create_library=True, schema_version=15,
        machine_capabilities=machine_capabilities,
        method_unit_options=method_options,
    )
    try:
        runtime.start()
        plugins = tuple(plugin for plugin in runtime.plugin_selection
            if type(plugin) is EngineeringServerPlugin)
        assert len(plugins) == 1
        plugin = plugins[0]
        binding = plugin._binding_for(runtime.wire.identity_authority)
        dispatch_owner = binding.execution_dispatch
        assert dispatch_owner is not None
        dispatch = dispatch_owner.dispatch
        assert dispatch is not None
        assert dispatch.factory is plugin._factory
        assert dispatch.access is binding.access
        assert dispatch.method_runs is binding.ports.current_wait_bindings
        assert dispatch.execution.query_factory is binding.ports.execution_query_factory
        assert binding.ports.execution_query_factory is binding.ports.current_wait_bindings.source.execution_query_factory
        assert binding.ports.execution_query_factory is binding.ports.submission_source.execution_query_factory
        assert binding.ports.submission_source.method_runs is binding.ports.current_wait_bindings
        assert dispatch.source_snapshots is dispatch.history_sources
        assert dispatch.source_snapshots.services is dispatch.selection.services
        assert (dispatch.selection.services.unit_manager
            is runtime.unit_runtime.context.owner_ports.unit_manager)
        assert dispatch.execution.services is dispatch.selection.services
        assert dispatch.execution.records is runtime.unit_execution_owner.records
        assert dispatch.execution.blobs is binding.ports.blobs
        assert runtime.unit_execution_owner.effect_write_guard_factory is dispatch.execution.effect_write_guard_factory
        assert callable(runtime.unit_execution_owner.effect_write_guard_factory.guard_effect_handoff)
        assert dispatch.execution.deferred_effect_write_guard_factory is False
        ids = {item.capability_id for item in RegisteredHostCapabilityCatalog(
            (plugin.capability_catalog(),)).read_current().capabilities}
        assert EXECUTION_DISPATCH in ids
        assert selected_permission['value'].access_authority is runtime.wire.identity_authority
        assert selected_permission['value'].profile_revision == selection.profile_revision
        assert prompt_calls == []
        assert environment.snapshot.active_uses == 0
    finally:
        runtime.stop()
    assert environment.snapshot.active_uses == 0
