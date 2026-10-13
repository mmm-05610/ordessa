"""Finite description of the original current-condition query, not a catalog."""
from ...methods.definitions.models.capabilities import CapabilityDescriptor
from ...methods.definitions.models.identity import method_digest
from ..contracts.method_work import WAIT_EVENT, WORK_CONTRACT


def work_condition_capability():
    contract = {
        'input': {'type': 'object', 'additionalProperties': False,
                  'required': ['run_id'], 'properties': {'run_id': {'type': 'string'}}},
        'workflow_outcomes': ['ready'],
        'route': 'EngineeringService.query',
        'resume_contract': WORK_CONTRACT,
        'authority': 'original current business source and complete current predicates',
        'not_ready': 'query refuses; original run remains waiting',
        'read_permission': WAIT_EVENT,
        'resume_operation': 'engineering.runs.resume',
        'resume_requires': ['exact row digest', 'exact condition digest', 'next step ordinal',
                            'current method and source guards', 'original write transaction CAS'],
        'automatic_dispatch': False,
        'is_catalog': False,
    }
    return CapabilityDescriptor(WAIT_EVENT, 'operation', '1',
        method_digest('capability-contract', contract), contract)
