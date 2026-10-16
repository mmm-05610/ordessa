"""The public export surface is an explicit, frozen contract.

This replaces the previous `__all__ = [name for name in globals() ...]`, which
leaked stdlib/typing names (`Any`, `Mapping`, `Protocol`, `dataclass`, `field`,
`datetime`, `time`) and submodule names into the public surface. A counter-example
below pins that the leak does not come back, and a compatibility test pins that
every name real consumers import still resolves.
"""
from __future__ import annotations

import importlib.util

import decision_runtime as d

# Exact intentional surface: the four group entries plus the real API names.
EXPECTED = {
    'definitions', 'validation', 'runtime', 'evidence',
    'ContractError', 'CODEC_VERSION', 'canonical', 'decode', 'digest', 'freeze',
    'name', 'plain', 'revision', 'json_schema',
    'DTO', 'ExternalRef', 'FlowRef', 'PolicyRef', 'TaskBrief', 'RunLimits',
    'DecisionRequest', 'VersionedObservation', 'ObservationBatch', 'ConfigurationOffer',
    'DecisionQuestion', 'DecisionAnswer', 'Precondition', 'ValidationObligation',
    'ProposalDraft', 'ObligationResult', 'ValidationReceipt', 'validate_ready',
    'CandidateOffer', 'CandidateBatch', 'ProposalCandidateBatch', 'CheckBatch',
    'BusinessOutcome', 'RunManifest', 'DecisionResult',
    'ReadContext', 'CallPermit', 'ModelCallContext', 'DurabilityAck',
    'ObservationPort', 'CandidateSource', 'ProposalSource', 'ProposalValidationPort',
    'PreconditionChecker', 'DecisionProvider', 'DecisionGateway', 'EvidenceSink',
    'EvidenceReader', 'DecisionServices',
    'construct', 'decode_request',
    'TrustedFlow', 'flow_digest', 'reviewed_code_digest', 'RunContext', 'NodeServices',
    'immutable_queries', 'run_decision', 'read_result', 'BudgetExhausted',
    'EvidenceUnknown', 'RuntimeFailure', 'ExplicitCancellation',
    'DecisionManager', 'DecisionManagerError', 'DecisionRun',
    'EvidenceError', 'FileEvidenceReader', 'FileEvidenceSink', 'MemoryEvidenceSink',
}

# Names the old globals()-based surface wrongly exposed; none may reappear.
FORMER_LEAK = {'Any', 'Mapping', 'Protocol', 'dataclass', 'field', 'datetime', 'time',
               'models', 'ports', 'values', 'errors', 'schemas'}


def test_export_surface_is_exactly_the_declared_set():
    assert set(d.__all__) == EXPECTED
    assert len(d.__all__) == len(EXPECTED), 'no duplicate exports'


def test_former_export_leak_counter_example():
    assert FORMER_LEAK & set(d.__all__) == set()
    for name in sorted(FORMER_LEAK):
        assert not hasattr(d, name), name


def test_every_exported_name_resolves():
    missing = sorted(n for n in d.__all__ if not hasattr(d, n))
    assert missing == []


def test_public_api_compatibility_for_real_consumer_import_forms():
    # `from decision_runtime.definitions import *`
    ns: dict = {}
    exec('from decision_runtime.definitions import *', ns)  # noqa: S102 - explicit star surface
    for name in ('DecisionRequest', 'DecisionResult', 'TaskBrief', 'PolicyRef',
                 'DecisionQuestion', 'DecisionAnswer', 'ReadContext', 'CallPermit',
                 'ContractError', 'canonical', 'digest', 'freeze', 'plain', 'json_schema'):
        assert name in ns, name
    # explicit owner submodule imports
    from decision_runtime.definitions.errors import BudgetExhausted, EvidenceUnknown  # noqa: F401
    from decision_runtime.definitions.models import DecisionRequest  # noqa: F401
    from decision_runtime.definitions.ports import ModelCallContext  # noqa: F401
    from decision_runtime.definitions.values import canonical  # noqa: F401
    from decision_runtime.runtime import run_decision  # noqa: F401
    from decision_runtime.validation import construct, decode_request  # noqa: F401
    from decision_runtime.evidence import EvidenceError, FileEvidenceSink  # noqa: F401
    assert callable(decode_request) and callable(construct) and callable(run_decision)


def test_group_entries_expose_their_owner_names():
    entries = {
        'definitions': (d.definitions, {'DecisionRequest', 'DecisionResult', 'json_schema', 'canonical'}),
        'validation': (d.validation, {'construct', 'decode_request'}),
        'runtime': (d.runtime, {'run_decision', 'read_result', 'TrustedFlow'}),
        'evidence': (d.evidence, {'EvidenceError', 'FileEvidenceSink', 'MemoryEvidenceSink'}),
    }
    for label, (module, names) in entries.items():
        missing = sorted(n for n in names if not hasattr(module, n))
        assert missing == [], f'{label} missing {missing}'


def test_retired_contracts_path_is_absent():
    assert importlib.util.find_spec('decision_runtime.contracts') is None
