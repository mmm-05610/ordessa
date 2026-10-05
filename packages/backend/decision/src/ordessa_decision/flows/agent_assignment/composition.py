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
MAX_SCHEMA_DEPTH = 32
MAX_SCHEMA_NODES = 4096


def _finite_json_tree(value):
    """Bound the complete declaration, including absent branches and enum data."""
    active = set(); remaining = MAX_SCHEMA_NODES
    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        if depth > MAX_SCHEMA_DEPTH or remaining < 0: return False
        if item is None or type(item) in (str, bool, int): return True
        if type(item) is float: return math.isfinite(item)
        if not isinstance(item, (Mapping, tuple, list)): return False
        identity = id(item)
        if identity in active: return False
        active.add(identity)
        try:
            if isinstance(item, Mapping):
                return all(type(key) is str and visit(child, depth + 1) for key, child in item.items())
            return all(visit(child, depth + 1) for child in item)
        finally: active.remove(identity)
    return visit(value, 0)


def _supported_schema(schema):
    """Validate declaration support without relying on which values are present."""
    if not isinstance(schema, Mapping) or schema.get('$schema', DIALECT) != DIALECT: return False
    common = {'$schema', 'type', 'enum', 'description', 'title'}
    specific = {'object': {'properties', 'required', 'additionalProperties', 'minProperties', 'maxProperties'},
        'array': {'items', 'minItems', 'maxItems'}, 'number': {'minimum', 'maximum'},
        'integer': {'minimum', 'maximum'}, 'string': {'minLength','maxLength'}, 'boolean': set(), 'null': set()}
    kind = schema.get('type')
    if kind is None:
        if 'enum' not in schema or set(schema)-common: return False
    elif type(kind) is not str or kind not in specific or set(schema) - (common | specific[kind]): return False
    if any(type(schema[key]) is not str for key in ('title', 'description') if key in schema): return False
    if 'enum' in schema and (not isinstance(schema['enum'], (tuple, list)) or not schema['enum']): return False
    for key in ('minLength','maxLength','minProperties','maxProperties'):
        if key in schema and (type(schema[key]) is not int or schema[key]<0): return False
    if kind in ('number', 'integer'):
        if any(type(schema[key]) not in (int, float) or not math.isfinite(schema[key]) for key in ('minimum', 'maximum') if key in schema): return False
    if kind == 'object':
        properties = schema.get('properties', {}); required = schema.get('required', ())
        if not isinstance(properties, Mapping) or not isinstance(required, (tuple, list)) or any(type(key) is not str for key in required): return False
        if type(schema.get('additionalProperties', True)) is not bool: return False
        if any(not _supported_schema(child) for child in properties.values()): return False
    if kind == 'array':
        if 'items' not in schema or not _supported_schema(schema['items']): return False
        if any(type(schema[key]) is not int or schema[key] < 0 for key in ('minItems', 'maxItems') if key in schema): return False
    return True


def _json_equal(a,b):
    """JSON numbers compare numerically; booleans remain a distinct type."""
    if type(a) in (int,float) and type(b) in (int,float): return a==b
    if isinstance(a,Mapping) and isinstance(b,Mapping):
        return set(a)==set(b) and all(_json_equal(a[k],b[k]) for k in a)
    if isinstance(a,(tuple,list)) and isinstance(b,(tuple,list)):
        return len(a)==len(b) and all(_json_equal(x,y) for x,y in zip(a,b))
    return type(a) is type(b) and a==b


def check_schema(value, schema):
    """Return valid/invalid/unverifiable; this is structural, never owner approval."""
    try:
        if not _finite_json_tree(schema) or not _supported_schema(schema): return 'unverifiable'
        return _check_value(value,schema)
    except (RecursionError, TypeError, ValueError, OverflowError):
        return 'unverifiable'


def _check_value(value, schema):
    """Validate values only after the complete declaration has been checked."""
    kind = schema.get('type')
    types = {'object': lambda v: isinstance(v, Mapping), 'array': lambda v: isinstance(v, (tuple, list)),
             'string': lambda v: type(v) is str, 'number': lambda v: type(v) in (int, float) and math.isfinite(v),
             'integer': lambda v: type(v) is int, 'boolean': lambda v: type(v) is bool, 'null': lambda v: v is None}
    if kind is not None and not types[kind](value): return 'invalid'
    if 'enum' in schema:
        if not isinstance(schema['enum'], (tuple,list)) or not schema['enum']: return 'unverifiable'
        if not any(_json_equal(value,v) for v in schema['enum']): return 'invalid'
    if kind == 'string':
        if len(value)<schema.get('minLength',0) or len(value)>schema.get('maxLength',len(value)): return 'invalid'
    if kind in ('number','integer'):
        for key, op in (('minimum', lambda v,b: v < b), ('maximum', lambda v,b: v > b)):
            if key in schema:
                if type(schema[key]) not in (int,float) or not math.isfinite(schema[key]): return 'unverifiable'
                if op(value, schema[key]): return 'invalid'
    if kind == 'object':
        if len(value)<schema.get('minProperties',0) or len(value)>schema.get('maxProperties',len(value)): return 'invalid'
        props = schema.get('properties', {})
        required = schema.get('required', ())
        additional = schema.get('additionalProperties', True)
        if not isinstance(props, Mapping) or not isinstance(required, (tuple,list)) or any(type(k) is not str for k in required):
            return 'unverifiable'
        if type(additional) is not bool: return 'unverifiable'
        if set(required)-set(value): return 'invalid'
        if not additional and set(value)-set(props): return 'invalid'
        for key in set(props)&set(value):
            status = _check_value(value[key], props[key])
            if status != 'valid': return status
    if kind == 'array':
        for key, op in (('minItems', lambda n,b:n<b), ('maxItems', lambda n,b:n>b)):
            if key in schema:
                if type(schema[key]) is not int or schema[key]<0: return 'unverifiable'
                if op(len(value),schema[key]): return 'invalid'
        if 'items' not in schema: return 'unverifiable'
        for item in value:
            status=_check_value(item,schema['items'])
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
