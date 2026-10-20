"""Declarative render projections; the host never inspects domain types."""
from __future__ import annotations

import pytest

from ordessa_interfaces_contracts import ContractError, OperationDescriptor
from ordessa_interfaces.system_access.projections import project


def _descriptor(render):
    return OperationDescriptor(id='demo.run', input_schema={'type': 'object'},
                               output_schema={'type': 'object'},
                               cli={'command': 'demo', 'operation': 'run', 'render': render})


def test_json_and_default_projection_return_data_unchanged():
    data = {'a': 1, 'rows': [{'x': 1}]}
    assert project(_descriptor({'kind': 'json'}), data) is data
    plain = OperationDescriptor(id='demo.run', input_schema={'type': 'object'},
                                output_schema={'type': 'object'},
                                cli={'command': 'demo', 'operation': 'run'})
    assert project(plain, data) is data


def test_table_projection_uses_rows_or_items():
    assert project(_descriptor({'kind': 'table'}), {'rows': [{'a': 1}]}) == [{'a': 1}]
    assert project(_descriptor({'kind': 'table'}), {'items': [{'a': 2}]}) == [{'a': 2}]
    assert project(_descriptor({'kind': 'table'}), [{'a': 3}]) == [{'a': 3}]
    with pytest.raises(ContractError, match='table'):
        project(_descriptor({'kind': 'table'}), {'rows': 'not-a-list'})


def test_fields_projection_reads_dotted_paths():
    projected = project(_descriptor({'kind': 'fields', 'fields': ('a', 'nested.value', 'missing')}),
                        {'a': 1, 'nested': {'value': 2}})
    assert projected == {'a': 1, 'nested.value': 2, 'missing': None}
    with pytest.raises(ContractError, match='fields'):
        project(_descriptor({'kind': 'fields', 'fields': ('a',)}), ['not-a-mapping'])


def test_process_projection_maps_named_paths():
    descriptor = _descriptor({'kind': 'process',
                              'paths': {'exit': 'exitCode', 'stdout': 'stdout',
                                        'stderr': 'stderr'}})
    assert project(descriptor, {'exitCode': 3, 'stdout': 'o', 'stderr': 'e'}) == {
        'exit': 3, 'stdout': 'o', 'stderr': 'e'}
    with pytest.raises(ContractError, match='process'):
        project(_descriptor({'kind': 'process'}), {'exitCode': 0})


def test_unknown_render_kind_refuses_instead_of_guessing():
    with pytest.raises(ContractError, match='render kind'):
        project(_descriptor({'kind': 'python'}), {'a': 1})
