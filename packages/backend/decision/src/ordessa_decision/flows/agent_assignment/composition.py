"""Bounded external template composition; no inference or schema enumeration.

Registered handlers own configuration semantics and complete proposal construction.
The conservative schema checker supports a declared subset of draft 2020-12;
unsupported dialects/keywords produce named gaps, never a guessed valid schema.
"""
from collections.abc import Mapping
from dataclasses import dataclass
import math
from ordessa_decision.contracts import ProposalCandidateBatch, ProposalDraft, ContractError, freeze, plain

DIALECT = 'https://json-schema.org/draft/2020-12/schema'


def check_schema(value, schema):
    """Return valid/invalid/unverifiable; this is structural, never owner approval."""
    if not isinstance(schema, Mapping): return 'unverifiable'
    allowed = {'$schema', 'type', 'properties', 'required', 'additionalProperties',
               'enum', 'minimum', 'maximum', 'items', 'minItems', 'maxItems', 'description', 'title'}
    if set(schema)-allowed or schema.get('$schema', DIALECT) != DIALECT:
        return 'unverifiable'
    kind = schema.get('type')
    types = {'object': lambda v: isinstance(v, Mapping), 'array': lambda v: isinstance(v, (tuple, list)),
             'string': lambda v: type(v) is str, 'number': lambda v: type(v) in (int, float) and math.isfinite(v),
             'integer': lambda v: type(v) is int, 'boolean': lambda v: type(v) is bool, 'null': lambda v: v is None}
    if kind not in types: return 'unverifiable'
    if not types[kind](value): return 'invalid'
    common={'$schema','type','enum','description','title'}
    specific={'object':{'properties','required','additionalProperties'},
        'array':{'items','minItems','maxItems'},'number':{'minimum','maximum'},'integer':{'minimum','maximum'}}
    if set(schema)-(common|specific.get(kind,set())): return 'unverifiable'
    if 'enum' in schema:
        if not isinstance(schema['enum'], (tuple,list)) or not schema['enum']: return 'unverifiable'
        if plain(value) not in [plain(v) for v in schema['enum']]: return 'invalid'
    if kind in ('number','integer'):
        for key, op in (('minimum', lambda v,b: v < b), ('maximum', lambda v,b: v > b)):
            if key in schema:
                if type(schema[key]) not in (int,float) or not math.isfinite(schema[key]): return 'unverifiable'
                if op(value, schema[key]): return 'invalid'
    if kind == 'object':
        props = schema.get('properties', {})
        required = schema.get('required', ())
        additional = schema.get('additionalProperties', True)
        if not isinstance(props, Mapping) or not isinstance(required, (tuple,list)) or any(type(k) is not str for k in required):
            return 'unverifiable'
        if type(additional) is not bool: return 'unverifiable'
        if set(required)-set(value): return 'invalid'
        if not additional and set(value)-set(props): return 'invalid'
        for key in set(props)&set(value):
            status = check_schema(value[key], props[key])
            if status != 'valid': return status
    if kind == 'array':
        for key, op in (('minItems', lambda n,b:n<b), ('maxItems', lambda n,b:n>b)):
            if key in schema:
                if type(schema[key]) is not int or schema[key]<0: return 'unverifiable'
                if op(len(value),schema[key]): return 'invalid'
        if 'items' not in schema: return 'unverifiable'
        for item in value:
            status=check_schema(item,schema['items'])
            if status!='valid': return status
    return 'valid'


@dataclass(frozen=True)
class RegisteredTemplate:
    template_id: str
    handler: object
    # The template registers a kind and known schema. No kind-specific graph code.
    configuration_kind: str
    schema: Mapping
    def __post_init__(self):
        if not self.template_id or not self.configuration_kind or not callable(self.handler):
            raise ContractError('template_invalid')
        object.__setattr__(self,'schema',freeze(plain(self.schema)))


class DeterministicProposalSource:
    """Host registry is fixed at construction, never chosen by arbitrary task import.

    Handler signature: async handler(task, candidate_refs, configuration_offer_refs,
    constraints, read_context) -> tuple[ProposalDraft,...]. Configuration payloads
    are supplied by explicit templates; fields/values are never enumerated here.
    A handler's schema applies to payload['configuration']; unknown structural
    semantics or absent handlers are returned as composition gaps.
    """
    def __init__(self, templates, *, max_combinations=64, max_proposals_per_round=8):
        self.templates = tuple(templates)
        if (any(not isinstance(t,RegisteredTemplate) for t in self.templates)
            or len({t.template_id for t in self.templates}) != len(self.templates)
            or type(max_combinations) is not int or not 0<=max_combinations<=64
            or type(max_proposals_per_round) is not int or not 0<=max_proposals_per_round<=8):
            raise ContractError('composition_settings_invalid')
        self.max_combinations=max_combinations; self.max_proposals_per_round=max_proposals_per_round

    async def compose(self, task, candidate_refs, configuration_offer_refs, constraints, cursor, read_context):
        if cursor is not None: raise ContractError('composition_cursor_unsupported')
        limit = constraints['selection_policy']['limits']
        max_calls = min(self.max_combinations, limit['max_combinations'])
        max_proposals = min(self.max_proposals_per_round, limit['max_proposals_per_round'])
        result=[]; issues=[]; complete=True
        if not self.templates:
            return ProposalCandidateBatch((),False,issues=({'code':'registered_templates_missing'},))
        for index, template in enumerate(self.templates):
            if index>=max_calls or len(result)>=max_proposals:
                complete=False; issues.append({'code':'composition_limit'}); break
            proposals=await template.handler(task,candidate_refs,configuration_offer_refs,constraints,read_context)
            if not isinstance(proposals,tuple) or any(not isinstance(p,ProposalDraft) for p in proposals):
                raise ContractError('template_result_invalid')
            if len(proposals)>max_proposals:
                raise ContractError('template_result_limit')
            for proposal in proposals:
                configuration=proposal.payload.get('configuration')
                if not isinstance(configuration,Mapping) or proposal.payload.get('configuration_kind')!=template.configuration_kind:
                    issues.append({'code':'template_configuration_gap'}); complete=False; continue
                status=check_schema(configuration,template.schema)
                if status!='valid':
                    issues.append({'code':'configuration_schema_'+status}); complete=False; continue
                if len(result)>=max_proposals:
                    complete=False; issues.append({'code':'composition_limit'}); break
                result.append(proposal)
        return ProposalCandidateBatch(tuple(result),complete,issues=tuple(issues))
