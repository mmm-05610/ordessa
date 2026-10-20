from __future__ import annotations
from typing import Any
from ordessa_engineering.domain.artifacts.library_materials import MaterialRef
from ordessa_engineering.domain.artifacts.library_material_codec import content_digest, material_ref_to_dict
from ordessa_engineering.application.orchestration.steps.workflow import EngineeringWorkflow
'Synthetic, non-user C09 material fixture for local mechanism exercises.'
BASELINE_TEXT = 'REQ-TRACE-01: Each implementation package includes a manifest.\nINV-EXPORT-01: Package export does not modify the source DID.\n'
AFTER_TEXT = 'Each implementation package includes a manifest that lists every generated output path and content digest, maps every output to one or more in-scope requirements and exact source materials, and maps every in-scope requirement to at least one generated output.'

def install_c09_materials(workflow: EngineeringWorkflow, *, method_ref: MaterialRef, missing_source: bool=False, missing_standard: bool=False, malformed_summary: bool=False) -> dict[str, Any]:
    """Import only explicit synthetic source materials and pinned method inputs."""
    library = workflow.library

    def put(kind: str, stable_id: str, body: Any) -> MaterialRef:
        return workflow.import_material(kind=kind, stable_id=stable_id, body=body)
    did = put('did', 'SYN-DID-01', {'fixture': 'synthetic', 'revision': 1, 'text': BASELINE_TEXT, 'source_status': 'synthetic-local'})
    decision = put('decision', 'SYN-DEC-01', {'fixture': 'synthetic', 'kind': 'explicit_delegation', 'scope': 'exercise package manifest traceability', 'authorization_claim': False, 'source_status': 'fixture-only'})
    source_fact = put('source-fact', 'FACT-EXPORT-01', {'fixture': 'synthetic', 'version': 'fixture/1', 'claims': {'manifest-omits-trace': {'locator': 'claims/manifest-omits-trace', 'manifest_has_traceability': False}}, 'manifest_paths': ['spec.md', 'plan.md', 'tasks.md']})
    quote = {'locator': 'claims/manifest-omits-trace', 'field': 'manifest_has_traceability', 'value': False}
    source_map = put('source-map', 'MAP-TRACE-01', {'claim_id': 'manifest-omits-trace', 'change_id': 'NOR-TRACE-01', 'source_ref': material_ref_to_dict(source_fact), 'field': 'manifest_has_traceability', 'expected_value': False, 'relation': 'supports-change', 'source_locator': 'claims/manifest-omits-trace', 'quote_digest': content_digest(quote), 'asserted_fact': {'predicate': 'manifest_has_traceability', 'expected_value': False}})
    standards_source = put('source-fact', 'FACT-LOCAL-TRACE-STANDARD', {'fixture': 'synthetic', 'version': 'local-profile-source/1', 'profile_id': 'ORDESSA-LOCAL-PROTOTYPE-TRACE/1', 'phase_clause_ids': {'proposal': ['LP-TRACE-01', 'LP-TRACE-02', 'LP-RETAIN-01'], 'package': ['LP-TRACE-01', 'LP-TRACE-02', 'LP-RETAIN-01']}, 'external_conformance': 'INDETERMINATE'})
    clauses = [{'criterion_id': 'LP-TRACE-01', 'phase': 'proposal', 'condition': 'each planned output binds path, requirement, source-map and digest rule', 'predicate': 'outputs_have_trace_fields'}, {'criterion_id': 'LP-TRACE-02', 'phase': 'proposal', 'condition': 'requirements map back to one or more generated outputs', 'predicate': 'requirements_reverse_mapped'}, {'criterion_id': 'LP-RETAIN-01', 'phase': 'proposal', 'condition': 'retained constraints stay present', 'predicate': 'retained_constraints_present'}, {'criterion_id': 'LP-TRACE-01', 'phase': 'package', 'condition': 'generated outputs carry verified content digests', 'predicate': 'package_outputs_digest_indexed'}, {'criterion_id': 'LP-TRACE-02', 'phase': 'package', 'condition': 'package trace is bidirectional', 'predicate': 'package_bidirectional_trace'}, {'criterion_id': 'LP-RETAIN-01', 'phase': 'package', 'condition': 'manifest retains every declared constraint', 'predicate': 'package_retains_constraints'}]
    if missing_standard:
        clauses = [row for row in clauses if row['criterion_id'] != 'LP-TRACE-02']
    standards = put('standards-profile', 'ORDESSA-LOCAL-PROTOTYPE-TRACE/1', {'fixture': 'synthetic', 'source_ref': material_ref_to_dict(standards_source), 'source_digest': standards_source.digest, 'scope': 'local-mechanism-only', 'external_conformance': 'INDETERMINATE', 'clauses': clauses})
    policy = put('review-policy', 'c09-review-policy', {'schema_version': 'review-policy/1', 'revision': 1, 'precedence': ['CONFLICT', 'INDETERMINATE', 'REVISION_REQUIRED', 'CLEAR'], 'rules': {'conflict': 'CONFLICT', 'unknown': 'INDETERMINATE', 'gap': 'REVISION_REQUIRED', 'all_checks_pass': 'CLEAR'}})
    source_maps = () if missing_source else (source_map,)
    proposal = put('proposal', 'SYN-ECP-01', {'fixture': 'synthetic', 'origin': {'kind': 'explicit-import', 'agent_generated': False, 'fixture': 'synthetic'}, 'change_id': 'NOR-TRACE-01', 'baseline_ref': material_ref_to_dict(did), 'decision_refs': [material_ref_to_dict(decision)], 'standards_profile_ref': material_ref_to_dict(standards), 'source_map_refs': [material_ref_to_dict(ref) for ref in source_maps], 'method_ref': material_ref_to_dict(method_ref), 'review_policy_ref': material_ref_to_dict(policy), 'changes': [{'change_id': 'NOR-TRACE-01', 'did_locator': 'REQ-TRACE-01', 'operation': 'modify', 'before_text': 'REQ-TRACE-01: Each implementation package includes a manifest.', 'after_text': 'REQ-TRACE-01: ' + AFTER_TEXT}], 'retained_constraints': [{'constraint_id': 'INV-EXPORT-01', 'did_locator': 'INV-EXPORT-01', 'exact_text': 'INV-EXPORT-01: Package export does not modify the source DID.'}], 'scope': ['NOR-TRACE-01'], 'planned_outputs': [{'path': path, 'requirement_id': 'NOR-TRACE-01', 'source_map_id': 'MAP-TRACE-01', 'digest_strategy': 'sha256-of-exported-bytes'} for path in ('spec.md', 'plan.md', 'tasks.md')], 'risks': ['fixture-only mechanism proof'], 'unresolved_items': ['external conformance remains indeterminate'], 'next_action': 'did.apply'})
    summary_body = {'included_change_ids': ['NOR-TRACE-01'], 'additions': [], 'modifications': ['NOR-TRACE-01'], 'deletions': [], 'retained_constraints': [{'constraint_id': 'INV-EXPORT-01', 'did_locator': 'INV-EXPORT-01', 'exact_text': 'INV-EXPORT-01: Package export does not modify the source DID.'}], 'risks': ['fixture-only mechanism proof'], 'unresolved_items': ['external conformance remains indeterminate'], 'next_action': 'did.apply'}
    if malformed_summary:
        summary_body['deletions'] = ['NOR-TRACE-01']
    summary_body['proposal_ref'] = material_ref_to_dict(proposal)
    summary = put('conversation-summary', 'SYN-SUMMARY-01', summary_body)
    source_maps_for_inputs = tuple(source_maps)
    return {'did': did, 'decision': decision, 'proposal': proposal, 'source_maps': source_maps_for_inputs, 'standards_profile': standards, 'summary': summary, 'review_policy': policy}

def import_c09_methods(workflow: EngineeringWorkflow, *, methods: dict[str, dict]) -> dict[str, MaterialRef]:
    """Caller supplies synthetic external prototype policies explicitly."""
    return {name: workflow.import_method(body) for name, body in methods.items()}
