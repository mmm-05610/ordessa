"""One assignment round. The native graph, not this helper, owns repair routing.

Required external selection policy keys are illustrated by selection_policy.json.
All limits are intersected with host RunLimits. Candidate sources provide immutable
capability_claims containing action, cost_status, and hard_checks. Each named check
must include status='passed', a comparable source_version, nonempty evidence_refs,
subject_ref, checker_id and checker_version. Policy required_validation lists exact
mandatory owner validator kind/version pairs for each action.
These claims must come from the composed trusted source, never task text or a model.
"""
from dataclasses import dataclass
import re
from datetime import datetime, timezone
from collections.abc import Mapping
from ordessa_decision.definitions import (
    CandidateBatch, ProposalCandidateBatch, DecisionQuestion, BusinessOutcome,
    ValidationReceipt, PolicyRef, ExternalRef, ContractError, freeze, plain, digest,
)
from .proposals import main_agent_proposal, ready_outcome, check_proposal_basis


@dataclass(frozen=True)
class AssignmentRound:
    outcome: BusinessOutcome
    repair_feedback: Mapping | None = None
    progress_digest: str | None = None


def validate_policy(policy):
    required = {'version', 'priorities', 'required_checks', 'limits',
        'create_requires_complete', 'allow_unknown_cost', 'rank_instructions',
        'rejection_options', 'tie_disposition', 'none_suitable_disposition',
        'insufficient_evidence_disposition', 'no_delegation', 'required_validation'}
    if not isinstance(policy, Mapping) or not required <= set(policy):
        raise ContractError('selection_policy_invalid')
    actions = tuple(policy['priorities'])
    if len(actions) != 6 or len(set(actions)) != 6 or set(policy['required_checks']) != set(actions):
        raise ContractError('selection_policy_invalid')
    # Action semantics are fixed; ordering, check catalog and bounds are external.
    if set(actions) != {'continue', 'reuse', 'restore', 'wait', 'reconfigure', 'create'}:
        raise ContractError('selection_policy_invalid')
    if not isinstance(policy['required_validation'],Mapping) or set(policy['required_validation'])!=set(actions):
        raise ContractError('selection_policy_invalid')
    for action in actions:
        requirements=policy['required_validation'][action]
        if not isinstance(requirements,(tuple,list)) or not requirements:
            raise ContractError('selection_policy_invalid')
        for v in requirements:
            if (not isinstance(v,Mapping) or set(v)!={'validator_kind','version_constraint'}
                or any(type(v[key]) is not str or not v[key] for key in v)):
                raise ContractError('selection_policy_invalid')
        checks = policy['required_checks'][action]
        if not checks or any(type(v) is not str or not v for v in checks):
            raise ContractError('selection_policy_invalid')
    for key in ('max_business_candidates', 'max_candidate_pages', 'candidate_page_size',
                'max_combinations', 'max_proposals_per_round', 'max_repair_rounds'):
        if type(policy['limits'].get(key)) is not int or policy['limits'][key] < 0:
            raise ContractError('selection_policy_invalid')
    if set(policy['rejection_options']) != {'none_suitable', 'insufficient_evidence'}:
        raise ContractError('selection_policy_invalid')
    if policy['tie_disposition'] != 'clarify' or any(policy[k] not in ('clarify', 'blocked')
        for k in ('none_suitable_disposition', 'insufficient_evidence_disposition')):
        raise ContractError('selection_policy_invalid')
    for key in ('create_requires_complete', 'allow_unknown_cost'):
        if type(policy[key]) is not bool: raise ContractError('selection_policy_invalid')
    nd = policy['no_delegation']
    if not isinstance(nd, Mapping) or type(nd.get('enabled')) is not bool or not isinstance(nd.get('boundary'), str):
        raise ContractError('selection_policy_invalid')
    if not isinstance(policy['rank_instructions'], str) or not policy['rank_instructions']:
        raise ContractError('selection_policy_invalid')
    return freeze(plain(policy))


def _limit(ctx, policy, key):
    return min(getattr(ctx.limits, key), policy['limits'][key])


def _issue(code, **details):
    return BusinessOutcome('clarify', issues=({'code': code, **details},))


def _eligible(candidate, policy, complete):
    obs = candidate.observation
    claims = candidate.capability_claims
    action = claims.get('action')
    if action not in policy['priorities'] or obs.source_version is None or obs.freshness != 'current' or not obs.evidence_refs:
        return False
    if obs.valid_until is not None and datetime.fromisoformat(obs.valid_until.replace('Z','+00:00')) <= datetime.now(timezone.utc):
        return False
    if candidate.candidate_ref != obs.subject_ref:
        return False
    if action == 'create' and policy['create_requires_complete'] and not complete:
        return False
    if not policy['allow_unknown_cost'] and claims.get('cost_status') != 'known':
        return False
    checks = claims.get('hard_checks')
    if not isinstance(checks, Mapping): return False
    for key in policy['required_checks'][action]:
        value = checks.get(key)
        if (not isinstance(value, Mapping) or value.get('status') != 'passed'
            or type(value.get('source_version')) is not str or not value['source_version']
            or not isinstance(value.get('evidence_refs'), (tuple, list)) or not value['evidence_refs']):
            return False
        if (type(value.get('checker_id')) is not str or not value['checker_id']
            or type(value.get('checker_version')) is not str or not value['checker_version']):
            return False
        try:
            ExternalRef.from_dict(value.get('subject_ref'))
        except (ContractError,TypeError):
            return False
    return True


async def _candidates(task, ctx, policy, policy_ref, observation_refs):
    if ctx.services.candidate_source is None:
        return (), False, ({'code': 'candidate_source_missing'},)
    seen = set(); refs = set(); candidates = []; cursor = None; complete = False; issues = []
    max_total = _limit(ctx, policy, 'max_business_candidates')
    page_size = _limit(ctx, policy, 'candidate_page_size')
    for _ in range(_limit(ctx, policy, 'max_candidate_pages')):
        await ctx.enter_node('ReadCandidates')
        batch = await ctx.services.candidate_source.list_candidates(task, observation_refs, policy_ref,
            ctx.services.read_context, cursor=cursor)
        if not isinstance(batch, CandidateBatch): raise ContractError('candidate_protocol_invalid')
        if len(batch.candidates) > page_size: raise ContractError('candidate_page_limit')
        for c in batch.candidates:
            key = digest('descriptor', c.candidate_ref)
            if key in refs: raise ContractError('duplicate_candidate')
            refs.add(key)
        room = max_total-len(candidates)
        candidates.extend(batch.candidates[:max(0, room)])
        issues.extend(batch.excluded); issues.extend(batch.unsupported)
        if len(batch.candidates) > room:
            issues.append({'code': 'candidate_limit'}); break
        if batch.complete:
            if batch.cursor is not None: raise ContractError('candidate_cursor_invalid')
            complete = True; break
        if not batch.cursor:
            break
        if batch.cursor in seen: raise ContractError('candidate_cursor_repeated')
        seen.add(batch.cursor); cursor = batch.cursor
        if len(candidates) >= max_total: break
    return tuple(candidates), complete, tuple(issues)


async def assignment_round(task, ctx, policy, *, feedback=None, previous_progress_digest=None, observation_refs=()):
    policy = validate_policy(policy)
    observation_refs=tuple(observation_refs)
    read_observations=freeze(plain(observation_refs))
    refs = [r for r in ctx.services.policy_refs if r.policy_id == 'selection']
    if len(refs) != 1: raise ContractError('selection_policy_ref_missing')
    policy_ref = refs[0]
    if policy_ref.content_digest != digest('policy', policy):
        raise ContractError('selection_policy_digest_mismatch')
    await ctx.enter_node('DelegationGate')
    nd = policy['no_delegation']
    if nd['enabled'] and nd['boundary'] in task.boundaries:
        return AssignmentRound(main_agent_proposal(task, policy_ref))
    candidates, complete, source_issues = await _candidates(task, ctx, policy, policy_ref, observation_refs)
    await ctx.enter_node('HardFilter')
    eligible = tuple(c for c in candidates if _eligible(c, policy, complete))
    if not eligible:
        return AssignmentRound(_issue('no_evidenced_candidate' if complete else 'candidate_catalog_incomplete'))
    action = next(a for a in policy['priorities'] if any(c.capability_claims['action'] == a for c in eligible))
    eligible = tuple(c for c in eligible if c.capability_claims['action'] == action)
    if ctx.services.proposal_source is None:
        return AssignmentRound(_issue('proposal_source_missing'))
    await ctx.enter_node('ComposeProposal')
    offers = tuple(ref for c in eligible for ref in c.capability_claims.get('configuration_offer_refs', ()))
    composition_policy=plain(policy)
    composition_policy['limits']={key:_limit(ctx,policy,key) for key in policy['limits']}
    constraints = freeze({'selection_policy': composition_policy, 'catalog_complete': complete,
        'candidate_facts': [plain(c) for c in eligible], 'feedback': plain(feedback),
        'source_issues': plain(source_issues), 'read_observations':plain(read_observations)})
    batch = await ctx.services.proposal_source.compose(task,
        tuple(c.candidate_ref for c in eligible), offers, constraints, None,
        ctx.services.read_context)
    if not isinstance(batch, ProposalCandidateBatch): raise ContractError('proposal_protocol_invalid')
    maximum = min(_limit(ctx, policy, 'max_proposals_per_round'), _limit(ctx, policy, 'max_combinations'))
    if len(batch.proposals) > maximum: raise ContractError('proposal_limit')
    if not batch.proposals:
        return AssignmentRound(_issue('composition_gap'))
    mapping = {}; candidate_mapping = {}
    for i, proposal in enumerate(batch.proposals):
        matches = []
        for c in eligible:
            try: check_proposal_basis(proposal, c, task, policy['required_checks'][action], policy['required_validation'][action])
            except ContractError: continue
            matches.append(c)
        if len(matches) != 1: raise ContractError('proposal_basis_invalid')
        key = f'proposal_{i}'
        mapping[key] = proposal; candidate_mapping[key] = matches[0]
    if len({p.proposal_digest for p in mapping.values()}) != len(mapping):
        raise ContractError('duplicate_proposal')
    progress = digest('feedback', {'proposal_digests': sorted(p.proposal_digest for p in mapping.values()),
        'basis': [c.observation.to_dict() for c in eligible], 'read_observations':plain(read_observations), 'feedback': plain(feedback)})
    if any(not _eligible(c,policy,complete) for c in candidate_mapping.values()):
        return AssignmentRound(_issue('candidate_evidence_expired'),progress_digest=progress)
    if previous_progress_digest == progress:
        return AssignmentRound(_issue('selection_no_progress'), progress_digest=progress)
    if len(mapping) == 1:
        chosen = next(iter(mapping))
    else:
        await ctx.enter_node('Rank')
        if any(not _eligible(c,policy,complete) for c in candidate_mapping.values()):
            return AssignmentRound(_issue('candidate_evidence_expired'),progress_digest=progress)
        if len(mapping)+2 > min(ctx.limits.max_choice_options, 66):
            raise ContractError('choice_limit')
        options = {k: {'action': p.payload['action'], 'proposal_digest': p.proposal_digest}
            for k, p in mapping.items()}
        options.update(plain(policy['rejection_options']))
        question = DecisionQuestion('assignment.rank', policy['version'], 'choice',
            {'task': task.to_dict(), 'proposals': {k: p.to_dict() for k,p in mapping.items()},
             'catalog_complete': complete}, policy['rank_instructions'], options=options,
            allowed_answer_ids=tuple(options), policy_ref=policy_ref)
        answer = await ctx.gateway.decide(question)
        if answer.provider_receipt.get('selection_status') == 'tie':
            return AssignmentRound(_issue('choice_tie'), progress_digest=progress)
        chosen = answer.value
        if chosen in policy['rejection_options']:
            return AssignmentRound(BusinessOutcome(policy[f'{chosen}_disposition'],
                issues=({'code': chosen},)), progress_digest=progress)
        if chosen not in mapping: raise ContractError('selection_answer_invalid')
    proposal = mapping[chosen]
    if ctx.services.validator is None:
        return AssignmentRound(_issue('proposal_validator_missing'), progress_digest=progress)
    await ctx.enter_node('ValidateProposal')
    basis = freeze({'task_ref': {'id': task.task_id, 'revision': task.task_revision},
        'candidate': candidate_mapping[chosen].to_dict(), 'policy_ref': policy_ref.to_dict(),
        'catalog_complete': complete, 'read_observations':plain(read_observations)})
    receipt = await ctx.services.validator.validate(proposal, basis, ctx.services.read_context)
    if not isinstance(receipt, ValidationReceipt): raise ContractError('validation_protocol_invalid')
    if receipt.proposal_digest != proposal.proposal_digest: raise ContractError('validation_digest_mismatch')
    if receipt.status == 'valid':
        if not _eligible(candidate_mapping[chosen],policy,complete):
            return AssignmentRound(_issue('candidate_evidence_expired'),progress_digest=progress)
        return AssignmentRound(ready_outcome(proposal, receipt, ctx.services.policy_refs), progress_digest=progress)
    repair = None
    if receipt.status == 'invalid':
        # Only safe structured issue codes become feedback; no arbitrary owner text.
        codes = tuple(v['code'] for v in receipt.issues if isinstance(v, Mapping)
            and isinstance(v.get('code'), str) and re.fullmatch(r'[A-Za-z0-9_.:/-]{1,128}',v['code']))
        if codes:
            repair = freeze({'proposal_digest': proposal.proposal_digest,
                'basis_digest': digest('feedback', basis), 'issue_codes': codes})
    return AssignmentRound(_issue('proposal_invalid' if repair else 'proposal_unverifiable'), repair, progress)


async def decide_assignment(task, ctx, policy, *, observation_refs=()):
    return (await assignment_round(task, ctx, policy, observation_refs=observation_refs)).outcome
