"""Same live core claim revalidation; actual SQLite, controlled authority/state.

No native transport/Harness/models. Revalidation is not a writer IO barrier.
"""
import copy
from pathlib import Path
import sys
import pytest
from agent_tools_fixtures.invocation_authority import setup, issue, verify
from ordessa_units.admission.invocation import InvocationIssuer, InvocationAuthorityRefused, InvocationVerifier
from ordessa_units.errors import UnitOperationUnknown


def continued(parts, context, **fields):
    binding = parts[2].context_ref['invocationBindings']['work']
    args = dict(action=context.facts['action'],provider_ref=parts[2].steps[0].pinned_provider_ref,
        target_ref=binding['targetRef'],input_digest='fixed-input')
    args.update(fields)
    return parts[6].verifier().verify_continuation(context,**args)


def test_same_successfully_consumed_claim_rechecks_without_new_claim_or_context(tmp_path):
    p=setup(tmp_path)
    try:
        c=issue(p); initial=verify(p,c)
        calls=p[3].revalidate_calls
        assert continued(p,c)==initial and continued(p,c)==initial
        assert p[3].revalidate_calls==calls+4
        assert p[6].verified_consumption(c) is True
        claim=p[0].read_operation_step(p[1],'work')
        assert claim.revision==1 and claim.outcome=='possibly-dispatched'
        assert p[0]._conn.execute('SELECT count(*) FROM env_request_steps').fetchone()[0]==1
        with pytest.raises(UnitOperationUnknown): issue(p)
        with pytest.raises(UnitOperationUnknown): verify(p,c)
    finally: p[0].close()


def test_not_yet_consumed_context_cannot_continue(tmp_path):
    p=setup(tmp_path)
    try:
        c=issue(p)
        with pytest.raises(InvocationAuthorityRefused,match='successful verification'): continued(p,c)
        assert verify(p,c)==c.facts
    finally: p[0].close()


@pytest.mark.parametrize('field',['authority','revision','expiry','activation','directory','epoch'])
def test_revocation_or_current_state_change_poison_original_effect(tmp_path,field):
    p=setup(tmp_path)
    try:
        c=issue(p);verify(p,c)
        if field=='authority': p[3].allowed=False
        elif field=='revision': p[3].revision='changed'
        elif field=='expiry': p[5][0]=101
        elif field=='activation': p[4].active=False
        elif field=='directory': p[4].permitted=False
        else: p[4].epoch=1
        with pytest.raises(InvocationAuthorityRefused): continued(p,c)
        p[3].allowed=True;p[3].revision='rev-1';p[5][0]=50
        p[4].active=True;p[4].permitted=True;p[4].epoch=0
        with pytest.raises(InvocationAuthorityRefused,match='successful verification'): continued(p,c)
        assert p[6].verified_consumption(c) is False
        assert p[0].read_operation_step(p[1],'work').outcome=='possibly-dispatched'
    finally:p[0].close()


@pytest.mark.parametrize('field',['action','provider_ref','target_ref','input_digest'])
def test_continuation_cannot_change_fixed_effect_identity(tmp_path,field):
    p=setup(tmp_path)
    try:
        c=issue(p);verify(p,c)
        wrong='wrong' if field in {'action','input_digest'} else {'environmentNamespace':'env','id':'wrong'}
        with pytest.raises(InvocationAuthorityRefused):continued(p,c,**{field:wrong})
        assert p[6].verified_consumption(c) is False
    finally:p[0].close()


@pytest.mark.parametrize('outcome',['unknown','concluded'])
def test_core_recorded_outcome_cannot_continue_effect_dispatch(tmp_path,outcome):
    p=setup(tmp_path)
    try:
        c=issue(p);verify(p,c)
        p[0].record_operation_step(p[1],'digest','work','fixed-input',1,outcome,
            {'evidenceRef':'controlled-conclusion'} if outcome=='concluded' else {})
        with pytest.raises(InvocationAuthorityRefused,match='claim'):continued(p,c)
    finally:p[0].close()


def test_only_original_live_issuer_and_object_are_allowed(tmp_path):
    p=setup(tmp_path)
    try:
        c=issue(p);verify(p,c)
        with pytest.raises(InvocationAuthorityRefused):continued(p,copy.copy(c))
        other=InvocationIssuer(p[0],p[3],p[4],clock=lambda:50)
        other_parts=(*p[:6],other)
        with pytest.raises(InvocationAuthorityRefused):continued(other_parts,c)
        assert continued(p,c)==c.facts
    finally:p[0].close()


def test_absent_continuation_port_refuses_without_using_initial_verifier():
    calls=[]
    v=InvocationVerifier(lambda *args:calls.append(args))
    with pytest.raises(InvocationAuthorityRefused,match='unavailable'):
        v.verify_continuation(object(),'apply',{}, {},'digest')
    assert calls==[]


def test_verified_query_continuation_stays_readonly_even_when_original_unknown(tmp_path):
    p=setup(tmp_path)
    try:
        c=issue(p);verify(p,c)
        p[0].record_operation_step(p[1],'digest','work','fixed-input',1,'unknown',{})
        q=p[6].issue_query(p[1],'digest','work')
        with pytest.raises(InvocationAuthorityRefused):continued(p,q)
        facts=p[6].verifier().verify_and_consume(q,'query',q.facts['providerRef'],q.facts['targetRef'],'fixed-input')
        assert continued(p,q)==facts and continued(p,q)['query'] is True
        assert p[6].verified_observation(q) is True
        with pytest.raises(InvocationAuthorityRefused):continued(p,q,action='apply')
        assert p[0].read_operation_step(p[1],'work').outcome=='unknown'
    finally:p[0].close()


def test_reentrant_continuation_is_refused_during_trusted_state_check(tmp_path):
    p=setup(tmp_path)
    try:
        c=issue(p);verify(p,c)
        original=p[4].inspect;attempts=[]
        def reentrant(*args):
            with pytest.raises(InvocationAuthorityRefused,match='successful verification'):
                continued(p,c)
            attempts.append(True)
            return original(*args)
        p[4].inspect=reentrant
        assert continued(p,c)==c.facts and attempts==[True]
    finally:p[0].close()


def test_unrelated_read_issuance_retains_active_effect_continuation(tmp_path):
    p=setup(tmp_path)
    try:
        c=issue(p);verify(p,c)
        q=p[6].issue_query(p[1],'digest','work')
        assert p[6].verified_consumption(c) is True
        assert continued(p,c)==c.facts
        assert len(p[6]._issued)==2
        assert p[0].read_operation_step(p[1],'work').revision==1
        assert q is not c
    finally:p[0].close()


def test_failed_initial_verification_cannot_become_continuation_after_restore(tmp_path):
    p=setup(tmp_path)
    try:
        c=issue(p);p[3].allowed=False
        with pytest.raises(InvocationAuthorityRefused):verify(p,c)
        p[3].allowed=True
        with pytest.raises(InvocationAuthorityRefused,match='successful verification'):continued(p,c)
    finally:p[0].close()


def test_continuation_and_core_admission_current_state_locks_do_not_invert(tmp_path):
    from threading import RLock, Event, Thread, get_ident
    p=setup(tmp_path)
    try:
        c=issue(p);verify(p,c)
        admission=RLock();entered=Event();worker_id=[];errors=[]
        original=p[4].inspect
        def current(*args):
            if worker_id and get_ident()==worker_id[0]:entered.set()
            if not admission.acquire(timeout=1):raise RuntimeError('deployment admission deadlock')
            try:return original(*args)
            finally:admission.release()
        p[4].inspect=current
        def worker():
            worker_id.append(get_ident())
            try:continued(p,c)
            except Exception as error:errors.append(error)
        with admission:
            thread=Thread(target=worker,daemon=True);thread.start()
            assert entered.wait(1)
            # Another core admission already owns the deployment lock. The
            # verifying thread must not retain the issuer lock while waiting.
            q=p[6].issue_query(p[1],'digest','work')
        thread.join(2)
        assert not thread.is_alive() and errors==[]
        assert continued(p,c)==c.facts and q.facts['query'] is True
    finally:p[0].close()


@pytest.mark.parametrize('changed',['revocation','expiry','concluded'])
def test_change_during_current_state_observation_is_rechecked_before_return(tmp_path,changed):
    p=setup(tmp_path)
    try:
        c=issue(p);verify(p,c)
        original=p[4].inspect
        def mutate(*args):
            state=original(*args)
            if changed=='revocation':p[3].allowed=False
            elif changed=='expiry':p[5][0]=101
            else:p[0].record_operation_step(p[1],'digest','work','fixed-input',1,'concluded',{'evidenceRef':'late'})
            return state
        p[4].inspect=mutate
        with pytest.raises(InvocationAuthorityRefused):continued(p,c)
        assert p[6].verified_consumption(c) is False
    finally:p[0].close()
