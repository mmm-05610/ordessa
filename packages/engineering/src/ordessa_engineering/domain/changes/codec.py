"""Closed Proposal codec, using the common canonical encoding and parsers."""
from dataclasses import asdict
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.domain.common.mechanisms.codec import (require_object, decode_tuple, decode_digest, decode_actor, decode_selector)
from ordessa_engineering.domain.artifacts.method_codec import (decode_method_ref, decode_exact_method_resource)
from ordessa_engineering.domain.artifacts.ref_codec import (decode_artifact_ref)
from ordessa_engineering.domain.artifacts.provenance_codec import (decode_source, decode_claim_ref)
from ordessa_engineering.domain.changes.ref_codec import (decode_proposal_ref)
from ordessa_engineering.domain.reviews.ref_codec import (decode_review_ref)
from ordessa_engineering.domain.changes.baseline_codec import (decode_repository_ref)
from ..common.models.identity import (Scope)
from ..common.outcomes.diagnostics import (ReferenceError)
from ..common.mechanisms.codec import (canonical_value)
from ..approvals.scope import PathRule, RepositoryScope, EnvironmentRef, EffectLimit, ActionScope
from ..reviews.models import (CriterionSetRef)
from ..reviews.requirements import (SubjectSelector,ExactArtifactRevisionSelector,TemplateTarget,TemplateCheck,
    ReviewRequirementTemplate,ReviewRequirementTemplateRef)
from .intent import ImplementationIntentSpec
from .models import Proposal, Mutation, ProposalEvidenceLink, ProposalControl, SourceChange, MAX_PROPOSAL_BYTES


def _scope(value):
    require_object(value,{'realm_id','project_id'}, code='INVALID_REVISION')
    return Scope(**value)


def _path(value):
    require_object(value,{'root','match','operations'}, code='INVALID_REVISION')
    return PathRule(value['root'],value['match'],decode_tuple(value['operations'],lambda x:x, code='INVALID_REVISION'))


def _repo(value):
    require_object(value,{'repository_id','path_rules'}, code='INVALID_REVISION')
    return RepositoryScope(value['repository_id'],decode_tuple(value['path_rules'],_path, code='INVALID_REVISION'))


def _env(value):
    require_object(value,{'environment_id','profile_id','profile_digest'}, code='INVALID_REVISION')
    return EnvironmentRef(value['environment_id'],value['profile_id'],decode_digest(value['profile_digest']))


def _limit(value):
    require_object(value,{'action','target_id','constraint_digest'}, code='INVALID_REVISION')
    return EffectLimit(value['action'],value['target_id'],decode_digest(value['constraint_digest']))


def _action_scope(value):
    require_object(value,{'project_id','repository_scopes','environment_refs','effect_limits','exclusions','implementation_intent_id'}, code='INVALID_REVISION')
    return ActionScope(value['project_id'],decode_tuple(value['repository_scopes'],_repo, code='INVALID_REVISION'),
        decode_tuple(value['environment_refs'],_env, code='INVALID_REVISION'),decode_tuple(value['effect_limits'],_limit, code='INVALID_REVISION'),
        decode_tuple(value['exclusions'],_path, code='INVALID_REVISION'),value['implementation_intent_id'])


def _template_ref(value):
    require_object(value,{'scope','template_id','template_version','digest'}, code='INVALID_REVISION')
    return ReviewRequirementTemplateRef(_scope(value['scope']),value['template_id'],value['template_version'],decode_digest(value['digest']))


def _spec(value):
    if value is None:
        return None
    require_object(value,{'implementation_intent_id','requested_actions','scope','expected_baselines',
        'acceptance_requirement_refs','instruction_constraints','digest'}, code='INVALID_REVISION')
    spec=ImplementationIntentSpec(value['implementation_intent_id'],decode_tuple(value['requested_actions'],lambda x:x, code='INVALID_REVISION'),
        _action_scope(value['scope']),decode_tuple(value['expected_baselines'],decode_repository_ref, code='INVALID_REVISION'),
        decode_tuple(value['acceptance_requirement_refs'],_template_ref, code='INVALID_REVISION'),decode_tuple(value['instruction_constraints'],lambda x:x, code='INVALID_REVISION'))
    if decode_digest(value['digest'])!=spec.digest:
        raise ReferenceError('INVALID_IMPLEMENTATION_INTENT')
    return spec


def _template_target(value):
    require_object(value,{'role','selector'}, code='INVALID_REVISION')
    selector=value['selector']
    if type(selector) is dict and selector.get('kind')=='exact_artifact_revision':
        require_object(selector,{'kind','artifact_revision_ref'}, code='INVALID_REVISION')
        parsed=ExactArtifactRevisionSelector(decode_artifact_ref(selector['artifact_revision_ref']))
    else:
        require_object(selector,{'kind','index','implementation_intent_id','schema_version'}, code='INVALID_REVISION')
        parsed=SubjectSelector(**selector)
    return TemplateTarget(value['role'],parsed)


def _template_check(value):
    require_object(value,{'target','criterion_id','claim_id'}, code='INVALID_REVISION')
    return TemplateCheck(_template_target(value['target']),value['criterion_id'],value['claim_id'])


def _template(value):
    require_object(value,{'scope','template_id','template_version','purpose','expected_targets','method_ref',
        'criterion_set_ref','required_check_keys','eligible_reviewer_roles','phase_key','digest'}, code='INVALID_REVISION')
    criterion=value['criterion_set_ref']
    require_object(criterion,{'criterion_set_id','version','digest'}, code='INVALID_REVISION')
    template=ReviewRequirementTemplate(_scope(value['scope']),value['template_id'],value['template_version'],value['purpose'],
        decode_tuple(value['expected_targets'],_template_target, code='INVALID_REVISION'),decode_method_ref(value['method_ref']),
        CriterionSetRef(criterion['criterion_set_id'],criterion['version'],decode_digest(criterion['digest'])),
        decode_tuple(value['required_check_keys'],_template_check, code='INVALID_REVISION'),decode_tuple(value['eligible_reviewer_roles'],lambda x:x, code='INVALID_REVISION'),value['phase_key'])
    if decode_digest(value['digest'])!=template.digest:
        raise ReferenceError('INVALID_REVIEW_TEMPLATE')
    return template


def _mutation(value):
    require_object(value,{'artifact_id','operation','base_ref','proposed_ref'}, code='INVALID_REVISION')
    return Mutation(value['artifact_id'],value['operation'],None if value['base_ref'] is None else decode_artifact_ref(value['base_ref']),
                    decode_artifact_ref(value['proposed_ref']))


def _link(value):
    require_object(value,{'claim_ref','source_ref','source_selector','relation','rationale'}, code='INVALID_REVISION')
    return ProposalEvidenceLink(decode_claim_ref(value['claim_ref']),decode_source(value['source_ref']),decode_selector(value['source_selector']),value['relation'],value['rationale'])


def _source_change(value):
    require_object(value, {'baseline', 'candidate', 'method_resource_refs', 'review_refs'}, 'INVALID_SOURCE_CHANGE')
    return SourceChange(decode_source(value['baseline']), decode_source(value['candidate']),
        decode_tuple(value['method_resource_refs'], decode_exact_method_resource, code='INVALID_SOURCE_CHANGE'),
        decode_tuple(value['review_refs'], decode_review_ref, code='INVALID_SOURCE_CHANGE'))


DRAFT_FIELDS=frozenset({'intent','rationale','mutations','basis_sources','claim_refs','evidence_links','method_ref',
    'review_requirement_templates','implementation_intent','supersedes_refs'})


def decode_draft(scope, proposal_id, created_at, created_by, change_id, value, schema_version=1):
    expected = DRAFT_FIELDS if schema_version == 1 else DRAFT_FIELDS | {'source_change'}
    require_object(value,expected,'INVALID_PROPOSAL')
    try:
        return Proposal(scope,proposal_id,created_at,created_by,change_id,value['intent'],value['rationale'],
            decode_tuple(value['mutations'],_mutation, code='INVALID_REVISION'),decode_tuple(value['basis_sources'],decode_source, code='INVALID_REVISION'),decode_tuple(value['claim_refs'],decode_claim_ref, code='INVALID_REVISION'),
            decode_tuple(value['evidence_links'],_link, code='INVALID_REVISION'),decode_method_ref(value['method_ref']),decode_tuple(value['review_requirement_templates'],_template, code='INVALID_REVISION'),
            _spec(value['implementation_intent']),decode_tuple(value['supersedes_refs'],decode_proposal_ref, code='INVALID_REVISION'),
            schema_version, None if schema_version == 1 else _source_change(value['source_change']))
    except (KeyError,TypeError,ValueError,AttributeError,OverflowError,RecursionError):
        raise ReferenceError('INVALID_PROPOSAL') from None


def encode_proposal(value):
    if type(value) is not Proposal:
        raise ReferenceError('INVALID_PROPOSAL')
    raw=canonical_bytes(value.projection())
    if len(raw)>MAX_PROPOSAL_BYTES:
        raise ReferenceError('PROPOSAL_TOO_LARGE')
    return raw


def decode_proposal(raw):
    try:
        value=canonical_value(raw,maximum=MAX_PROPOSAL_BYTES)
        if type(value) is not dict or type(value.get('schema_version')) is not int or value['schema_version'] not in {1, 2}:
            raise ReferenceError('INVALID_PROPOSAL')
        draft_fields = DRAFT_FIELDS if value['schema_version'] == 1 else DRAFT_FIELDS | {'source_change'}
        require_object(value,draft_fields|{'realm_id','project_id','proposal_id','created_at','created_by','schema_version','change_id','digest'}, code='INVALID_REVISION')
        record=decode_draft(Scope(value['realm_id'],value['project_id']),value['proposal_id'],value['created_at'],
            decode_actor(value['created_by']),value['change_id'],{k:value[k] for k in draft_fields},
            schema_version=value['schema_version'])
        if record.digest!=decode_digest(value['digest']) or encode_proposal(record)!=raw:
            raise ReferenceError('INVALID_PROPOSAL')
        return record
    except (KeyError,TypeError,ValueError,AttributeError,OverflowError,RecursionError):
        raise ReferenceError('INVALID_PROPOSAL') from None


def encode_control(value):
    if type(value) is not ProposalControl:
        raise ReferenceError('INVALID_PROPOSAL_CONTROL')
    return canonical_bytes(asdict(value))


def decode_control(raw):
    try:
        value=canonical_value(raw)
        require_object(value,{'proposal_ref','disposition','replacement_ref','control_evidence','version'}, code='INVALID_REVISION')
        result=ProposalControl(decode_proposal_ref(value['proposal_ref']),value['disposition'],
            None if value['replacement_ref'] is None else decode_proposal_ref(value['replacement_ref']),
            decode_tuple(value['control_evidence'],decode_digest, code='INVALID_REVISION'),value['version'])
        if encode_control(result)!=raw:
            raise ReferenceError('INVALID_PROPOSAL_CONTROL')
        return result
    except (KeyError,TypeError,ValueError,AttributeError,OverflowError,RecursionError):
        raise ReferenceError('INVALID_PROPOSAL_CONTROL') from None


def decode_implementation_spec(value):
    """Closed original Proposal spec decoder, shared by its authorization owner."""
    result = _spec(value)
    if result is None:
        raise ReferenceError('INVALID_IMPLEMENTATION_INTENT')
    return result


def decode_action_scope(value):
    return _action_scope(value)
