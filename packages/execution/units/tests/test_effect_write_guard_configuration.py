"""Exact real Unit guard configuration preflight; no ACP prompt or model."""
from contextlib import asynccontextmanager
from pathlib import Path
import sys

import pytest

support=Path(__file__).resolve().parents[2]/'agents'/'tests'/'support'
if str(support) not in sys.path: sys.path.insert(0,str(support))
from agent_tools_fixtures.manager_joint import build_joint_owner
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.bindings.publication import decode_node_ref
from ordessa_agents.harness.transport import EffectWriteGuard, EffectWriteRefused


@asynccontextmanager
async def acquire(identity, deadline):
    yield  # Controlled test only; no production approval/control claim.


def factory(unit, operation, digest, params):
    return EffectWriteGuard(unit, operation, digest, params, acquire)


def prepared(j):
    operation=j.services.assembly.prepare(RequestKey('env','principal','prepare'),j.profile,{},{})
    assert operation.status == 'published'
    ref=j.services.nodes.read(decode_node_ref(operation.intent.node_ref))['binding']['harnessUnitRef']
    return ref, j.manager.find(ref)


def turn_count(j):
    with j.records.journal._connect() as db:
        return db.execute('SELECT COUNT(*) FROM harness_acp_turn_attempts').fetchone()[0]


@pytest.mark.parametrize('configuration',['exact','missing','foreign_factory'])
def test_public_preflight_exact_factory_before_any_turn_reserve(configuration,tmp_path):
    with build_joint_owner(tmp_path,acp_turn_opt_in=True,
            effect_write_guard_factory=None if configuration=='missing' else factory) as j:
        ref, unit=prepared(j)
        assert turn_count(j)==0
        expected=factory if configuration!='foreign_factory' else lambda *args:factory(*args)
        if configuration=='exact':
            assert unit.require_effect_write_guard(expected) is None
        else:
            with pytest.raises(EffectWriteRefused): unit.require_effect_write_guard(expected)
        assert turn_count(j)==0 and j.events.count('spawn')==1


@pytest.mark.parametrize('change',['cleared_factory','changed_factory','owner_seal','factory_owner','sdk_owner','sdk_required'])
def test_actual_factory_and_sdk_binding_drift_refuses_before_reserve(change,tmp_path,monkeypatch):
    with build_joint_owner(tmp_path,acp_turn_opt_in=True,effect_write_guard_factory=factory) as j:
        ref, unit=prepared(j); channel_factory=unit.channel_factory; entry=channel_factory.owned_record.entry
        with monkeypatch.context() as patch:
            if change=='cleared_factory': patch.setattr(unit,'_effect_write_guard_factory',None)
            if change=='changed_factory': patch.setattr(unit,'_effect_write_guard_factory',lambda *a:factory(*a))
            if change=='owner_seal': patch.setattr(unit,'_effect_write_owner',object())
            if change=='factory_owner': patch.setattr(channel_factory,'_effect_write_owner',object())
            if change=='sdk_owner': patch.setattr(entry,'_effect_write_owner',object())
            if change=='sdk_required': patch.setattr(entry,'_require_effect_write_guard',False)
            with pytest.raises(EffectWriteRefused): unit.require_effect_write_guard(factory)
            lease=unit.lease_port.grant(ref)
            with pytest.raises(EffectWriteRefused):
                unit.prompt(ref,lease,operation_ref='preflight-refused',prompt=[])
            assert turn_count(j)==0
        assert unit.require_effect_write_guard(factory) is None
        assert j.events.count('spawn')==1
