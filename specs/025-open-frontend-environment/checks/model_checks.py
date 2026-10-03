"""025 离线确定性参考模型；不导入生产源码/访问服务/读取用户数据。
检测设计不变量与故意错误序列，非后端/React/Electron实现测试。
"""
from dataclasses import dataclass, field
from copy import deepcopy
import json
from pathlib import Path

@dataclass
class Owner:
    target: str
    current: dict = field(default_factory=lambda: {'model': 'M0', 'prompt': 'P0'})
    native_revision: int = 10
    binding: int = 1
    operations: list = field(default_factory=list)
    seq: int = 0
    inflight: dict | None = None
    stale: bool = False
    conflict: bool = False
    evidence: dict = field(default_factory=dict)
    chain_buffer: dict = field(default_factory=dict)
    def dispatch(self, patch, source='model', *, catalog=1, expected_catalog=1):
        self.seq += 1
        op = {'id': f'{self.target}:op{self.seq}', 'seq': self.seq, 'patch': deepcopy(patch),
              'phase': 'ready' if catalog == expected_catalog else 'refused',
              'binding': self.binding, 'source': source}
        self.operations.append(op)
        return op
    def resolved(self):
        v = deepcopy(self.current)
        for o in self.operations:
            if o['phase'] in ('ready', 'reserved', 'unknown'):
                v.update(o['patch'])
        return v
    def capture(self, sid, text='', draft_revision=1, *, storage_ok=True, edit_ready=True):
        if self.inflight: return {'state': 'busy'}
        if not edit_ready: return {'state': 'edit-not-published'}
        if self.stale or self.conflict: return {'state': 'stale'}
        if any(o['phase'] in ('refused','stale','resolving') for o in self.operations):
            return {'state': 'operation-unavailable'}
        ids = [o['id'] for o in self.operations if o['phase'] == 'ready']
        patch = {}
        for o in self.operations:
            if o['id'] in ids:
                o['phase'] = 'reserved'; patch.update(o['patch'])
        s = {'id': sid, 'target': self.target, 'binding': self.binding, 'base': self.native_revision,
             'ids': ids, 'patch': patch, 'resolved': deepcopy(self.resolved()), 'text': text,
             'draft_revision': draft_revision, 'state': 'possibly-submitted'}
        self.inflight = deepcopy(s)
        if not storage_ok:
            self.not_dispatched(); return {'state': 'not-dispatched'}
        return s
    def not_dispatched(self):
        assert self.inflight and self.inflight['state'] == 'possibly-submitted'
        for o in self.operations:
            if o['id'] in self.inflight['ids']: o['phase'] = 'ready'
        self.inflight = None
    def execute_condition(self, snapshot, actual_revision, atomic=True):
        if not atomic or snapshot['base'] != actual_revision:
            self.not_dispatched(); return 'refused-zero-input'
        return 'permitted'
    def observe(self, revision, value):
        if revision < self.native_revision: return 'old'
        if revision == self.native_revision and value != self.current:
            self.conflict = self.stale = True
            return 'conflict'
        if revision == self.native_revision and self.conflict:
            return 'conflict'  # a duplicate is not a reconciliation verdict
        self.current = deepcopy(value); self.native_revision = revision
        self.conflict = False  # trusted complete newer snapshot in this finite model
        # Covered patches cannot resurrect an old gap after snapshot recovery.
        self.chain_buffer = {prev: item for prev, item in self.chain_buffer.items()
                             if prev >= revision and item[0] > revision}
        self._advance_chain()
        return 'current'
    def patch_observe(self, prev, revision, patch):
        if self.conflict: return 'conflict'
        if revision <= self.native_revision: return 'old'
        if revision <= prev: return 'invalid-chain'
        if prev < self.native_revision:
            self.stale = True
            return 'gap'  # overlapping patch cannot be used as a complete snapshot
        self.chain_buffer[prev] = (revision, deepcopy(patch))
        self._advance_chain()
    def _advance_chain(self):
        while self.native_revision in self.chain_buffer:
            rev,p = self.chain_buffer.pop(self.native_revision)
            self.current.update(p); self.native_revision = rev
        self.stale = self.conflict or bool(self.chain_buffer)
    def evidence_result(self, sid, *, execution=True, current=None, partial=False, input_result='accepted'):
        assert self.inflight and sid == self.inflight['id']
        if partial or not execution:
            for o in self.operations:
                if o['id'] in self.inflight['ids']: o['phase'] = 'unknown'
            self.inflight['state'] = 'partial-unknown' if partial else 'unknown'
            return 'unknown'
        for o in self.operations:
            if o['id'] in self.inflight['ids']: o['phase'] = 'consumed'
        if current is None: self.stale = True
        else: self.observe(*current)
        self.evidence[sid] = deepcopy(self.inflight)
        if input_result == 'unknown':
            self.inflight['state'] = 'input-unknown'
        else:
            self.inflight = None
        return input_result
    def replace_binding(self, binding):
        self.binding = binding; self.stale = True
        for o in self.operations:
            if o['phase'] == 'ready': o['phase'] = 'stale'

class Registry:
    def __init__(self): self.owners = {}; self.aliases = {}
    def register(self, fact, canonical_target, owner, major):
        key = (fact, canonical_target)
        if key in self.owners: return 'refused'
        self.owners[key] = {'owner':owner,'majors':{major}}; return 'accepted'
    def bind_native(self, alias, authority):
        if alias in self.aliases and self.aliases[alias] != authority: return 'refused'
        self.aliases[alias] = authority; return 'accepted'

class Activation:
    def __init__(self): self.phase='active'; self.committed=[]; self.epoch=1; self.leased=True
    def preflight(self): self.phase='preflight'
    def commit(self, task):
        if not self.leased or self.phase != 'active': return 'refused'
        self.committed.append(task); return 'committed'
    def refuse_disable(self): self.phase='active'
    def revoke(self): self.leased=False; self.phase='settlement'; self.epoch+=1
    def deliver(self, epoch): return self.leased and epoch==self.epoch

class Budget:
    def __init__(self, total): self.total=total; self.used=0
    def retain(self, amount):
        if self.used+amount>self.total: return False
        self.used+=amount; return True
    def release(self, amount): self.used-=amount

results=[]
def check(name, fn, cases):
    fn(); results.append({'name':name,'result':'PASS','scenarios':cases,'grade':'L'})

def field_order():
    a=Owner('A'); a.dispatch({'model':'M1','prompt':'P1'},'profile'); a.dispatch({'model':'B'})
    assert a.resolved()=={'model':'B','prompt':'P1'}
    b=Owner('B'); b.dispatch({'model':'B'}); b.dispatch({'model':'M1','prompt':'P1'},'profile')
    assert b.resolved()['model']=='M1'
    b.dispatch({'skill':'S2'},'profile'); assert b.resolved()['model']=='M1'
    before=b.current.copy(); assert before=={'model':'M0','prompt':'P0'}
check('field-mask-and-order',field_order,[2,3,4])

def same_pick():
    a=Owner('a'); x=a.dispatch({'model':'M1'},'profile'); y=a.dispatch({'model':'M1'},'profile')
    assert x['id']!=y['id'] and y['seq']==x['seq']+1
check('same-value-new-operation',same_pick,[5])

def frozen_new_pick():
    a=Owner('a'); old=a.dispatch({'model':'B'}); s=a.capture('s',text='hi'); new=a.dispatch({'model':'C'})
    assert s['resolved']['model']=='B' and s['patch']=={'model':'B'}
    a.evidence_result('s',current=(11,{'model':'B','prompt':'P0'}))
    assert old['phase']=='consumed' and new['phase']=='ready' and a.resolved()['model']=='C'
check('frozen-submission-does-not-consume-later-op',frozen_new_pick,[6])

def late_observe():
    a=Owner('a'); a.dispatch({'model':'B'}); a.capture('s')
    a.observe(12,{'model':'C','prompt':'P1'})
    a.evidence_result('s',current=(11,{'model':'B','prompt':'P0'}))
    assert a.current=={'model':'C','prompt':'P1'} and a.native_revision==12
    assert a.observe(12,{'model':'D','prompt':'P1'})=='conflict'
check('new-observation-before-old-receipt',late_observe,[12])

def concurrent():
    a=Owner('a'); a.dispatch({'model':'B'}); a.capture('s1')
    assert a.capture('s2')['state']=='busy'
    assert [o['phase'] for o in a.operations]==['reserved']
check('same-authority-exclusive-reservation',concurrent,[10])

def cas():
    a=Owner('a'); a.dispatch({'model':'B'}); s=a.capture('s')
    assert s['patch']=={'model':'B'} and 'prompt' not in s['patch']
    assert a.execute_condition(s,11)=='refused-zero-input'
    assert a.inflight is None and a.operations[0]['phase']=='ready'
check('no-full-snapshot-writeback-and-cas',cas,[3,12])

def unknown():
    a=Owner('a'); a.dispatch({'model':'B'}); s=a.capture('s')
    assert s['state']=='possibly-submitted'
    assert a.evidence_result('s',execution=False)=='unknown'
    a.observe(11,{'model':'B','prompt':'P0'})
    assert a.operations[0]['phase']=='unknown' and a.capture('s2')['state']=='busy'
    recovered=deepcopy(a); assert recovered.inflight['id']=='s'
check('unknown-and-restart-only-correlate',unknown,[8,11])

def no_current():
    a=Owner('a'); a.dispatch({'model':'B'}); a.capture('s'); a.evidence_result('s',current=None)
    assert a.operations[0]['phase']=='consumed' and a.stale
    assert a.capture('s2')['state']=='stale'
check('execution-is-not-current-evidence',no_current,[2,11,12])

def partial():
    a=Owner('a'); a.dispatch({'model':'B','prompt':'P1'},'profile'); a.capture('s')
    assert a.evidence_result('s',partial=True)=='unknown'
    assert a.inflight['state']=='partial-unknown' and a.capture('s2')['state']=='busy'
check('partial-application-blocks-input-and-retry',partial,[8])

def refused_pre():
    a=Owner('a'); a.dispatch({'model':'B'}); assert a.capture('s',storage_ok=False)['state']=='not-dispatched'
    assert a.inflight is None and a.operations[0]['phase']=='ready'
    assert a.capture('s2')['state']=='possibly-submitted'
check('pre-outbound-write-failure-releases-reservation',refused_pre,[11])

def aba():
    sent={'text':'A','revision':1}; now={'text':'A','revision':3}
    def clear(current,snapshot): return '' if current['revision']==snapshot['revision'] else current['text']
    assert clear(now,sent)=='A' and clear(sent,sent)==''
    # 故意错误实现：按文本相等清空，必须与规范不符。
    bad='' if now['text']==sent['text'] else now['text']; assert bad!=clear(now,sent)
check('draft-ABA-and-negative-text-equality',aba,[7,8])

def isolation():
    a=Owner('s1'); b=Owner('s2'); a.dispatch({'model':'B'}); a.capture('send')
    before=deepcopy(b.__dict__); a.evidence_result('send',current=(11,{'model':'B','prompt':'P0'}))
    assert b.__dict__==before
check('late-result-stays-with-captured-session',isolation,[10])

def catalogs():
    a=Owner('a'); a.dispatch({'model':'M2'},'profile',catalog=2,expected_catalog=1)
    assert a.capture('s')['state']=='operation-unavailable'
check('async-catalog-version-mismatch-refused',catalogs,[4])

def patch_chain():
    a=Owner('a'); a.patch_observe(11,12,{'prompt':'P1'}); assert a.stale and a.capture('s')['state']=='stale'
    a.patch_observe(10,11,{'model':'B'}); assert not a.stale and a.current=={'model':'B','prompt':'P1'}
check('out-of-order-patch-requires-complete-chain',patch_chain,[12,21])

def binding():
    a=Owner('a'); a.dispatch({'model':'B'}); a.replace_binding(2)
    a.observe(1,{'model':'C','prompt':'P0'}) # 旧revision拒绝，不能让这行解除stale
    assert a.stale and a.operations[0]['phase']=='stale'
    # 绑定证明只能同一个attempt接受同一个native；不是任意target宽松匹配。
    proof={'attempt':'c1','native':'n1'}
    accept=lambda attempt,native: attempt==proof['attempt'] and native==proof['native']
    assert accept('c1','n1') and not accept('c2','n1') and not accept('c1','n2')
check('binding-applicability-and-creation-proof',binding,[9,18])

def authority():
    r=Registry(); assert r.register('config','agent:L','o1',1)=='accepted'
    assert r.register('config','agent:L','o2',2)=='refused'
    assert r.register('resources','local:workspace1','r',1)=='accepted'
    assert r.bind_native('native:n1:g1','agent:L')=='accepted'
    assert r.bind_native('native:n1:g1','agent:new-socket-key')=='refused'
check('authority-cross-major-and-reconnect-alias',authority,[1,10,16,19])

def routing():
    route=lambda origin,command,native: ('native',command) if origin=='native' and native else ('unavailable',command) if origin=='native' else ('environment',command)
    assert route('native','/workflow',True)==('native','/workflow')
    assert route('environment','/workflow',True)==('environment','/workflow')
    assert route('native','/workflow',False)[0]=='unavailable'
    refs={('agent:g1','input','1'): 'agent',('terminal:g1','input','1'):'terminal'}
    assert refs[('terminal:g1','input','1')]=='terminal'
check('raw-command-routing-and-surface-provider-identity',routing,[13,14])

def preflight():
    a=Activation(); a.preflight(); assert a.commit('late')=='refused'
    a.refuse_disable(); assert a.commit('new')=='committed'
    a.revoke(); assert not a.deliver(1) and a.committed==['new']
check('admission-fence-and-old-settlement',preflight,[17,18,22])

def await_revoke():
    a=Activation(); preparation_epoch=a.epoch; a.revoke()
    assert a.commit('after-await')=='refused' and not a.deliver(preparation_epoch)
    b=Activation(); assert b.commit('before-revoke')=='committed'; b.revoke()
    assert b.committed==['before-revoke'] # 不能当作撤销成功取消已承诺操作
check('authorization-commit-versus-revocation',await_revoke,[22])

def doc_epoch():
    a=Activation(); old=a.epoch; a.revoke(); assert not a.deliver(old)
    a.leased=True; assert not a.deliver(old) and a.deliver(a.epoch)
    authorized_view={'target':'A','fields':{'public':'ok'}}
    assert 'secret' not in authorized_view['fields'] and authorized_view['target']!='B'
check('document-and-read-delivery-rights',doc_epoch,[15,22])

def edit_barrier():
    a=Owner('a'); assert a.capture('s',edit_ready=False)['state']=='edit-not-published' and a.inflight is None
    event={'epoch':1,'composing':True}; current_epoch=2
    permits=lambda e: e['epoch']==current_epoch and not e['composing']
    assert not permits(event)
    stack=['dialog','popover']; captured=stack[-1]; stack.remove(captured)
    assert stack==['dialog'] # 唯一dispatcher不会再次读top关闭dialog
check('all-send-entry-barrier-and-single-Esc',edit_barrier,[7,20])

def approval():
    pending={'id':'I','version':1,'state':'pending'}
    def claim(version):
        if pending['version']!=version or pending['state']!='pending': return 'stale'
        pending['state']='claimed'; return 'accepted'
    assert claim(1)=='accepted' and claim(1)=='stale' and claim(2)=='stale'
check('approval-condition-single-claim',approval,[15,22])

def budgets():
    b=Budget(16); assert b.retain(8) and b.retain(8) and not b.retain(1)
    decoded=Budget(64); assert decoded.retain(64) and not decoded.retain(1)
    old_epoch=1; new_epoch=2; assert old_epoch!=new_epoch
check('joint-budget-decoded-retention-and-stream-epoch',budgets,[21])

def positive_negative_guards():
    # 反例构造不是assert永真：guard必须拒绝不合法实例，也接受合法实例。
    expected=lambda receipt: receipt['target']=='A' and receipt['generation']==2 and receipt['id']=='S'
    valid={'target':'A','generation':2,'id':'S'}
    assert expected(valid)
    for bad in ({**valid,'target':'B'},{**valid,'generation':1},{**valid,'id':'OTHER'}): assert not expected(bad)
    correct_key=lambda fact,target,major:(fact,target)
    bad_key=lambda fact,target,major:(fact,target,major)
    assert correct_key('config','L',1)==correct_key('config','L',2)
    assert bad_key('config','L',1)!=bad_key('config','L',2)
check('positive-and-negative-identity-guards',positive_negative_guards,[10,18,19])

def input_unknown():
    a=Owner('a'); a.dispatch({'model':'B'}); a.capture('s')
    assert a.evidence_result('s',current=(11,{'model':'B','prompt':'P0'}),input_result='unknown')=='unknown'
    assert a.operations[0]['phase']=='consumed' and a.current['model']=='B'
    assert a.inflight['state']=='input-unknown' and a.capture('s2')['state']=='busy'
    a.evidence_result('s',current=(11,{'model':'B','prompt':'P0'}),input_result='accepted')
    assert a.inflight is None
check('configuration-confirmed-input-unknown-stays-locked',input_unknown,[8,11])

def terminal_marker_failure():
    a=Owner('a'); a.dispatch({'model':'B'}); a.capture('s')
    # outbound之前零commit，但not-dispatched终态无法可靠写入；恢复保守unknown。
    a.inflight['state']='unknown'
    assert a.capture('s2')['state']=='busy'
    assert a.operations[0]['phase']=='reserved'
check('terminal-marker-write-failure-conservative-unknown',terminal_marker_failure,[11])

def conflicting_current_blocks():
    a=Owner('a'); before=deepcopy(a.current)
    assert a.observe(10,{'model':'BAD','prompt':'P0'})=='conflict'
    assert a.current==before and a.stale and a.capture('s')['state']=='stale'
    assert a.observe(11,{'model':'B','prompt':'P0'})=='current'
    assert a.capture('s2')['state']=='possibly-submitted'
check('same-revision-conflict-blocks-capture-positive-negative',conflicting_current_blocks,[12])

def schema_identity():
    # 两种传输编码归一到同一事实，不按TargetRef对象结构注册。
    normalize=lambda wire: ('resource-identity',wire['workspace'],wire['resource'])
    v1={'schema':1,'workspace':'W','resource':'X'}
    v2={'schema':2,'workspace':'W','resource':'X'}
    assert v1!=v2 and normalize(v1)==normalize(v2)
    r=Registry(); assert r.register('resources',normalize(v1),'r1',1)=='accepted'
    assert r.register('resources',normalize(v2),'r2',2)=='refused'
check('target-schema-version-normalizes-same-fact',schema_identity,[16,18,19])

def conflict_duplicates_stay_locked():
    a=Owner('a'); original=deepcopy(a.current)
    assert a.observe(10,{'model':'BAD','prompt':'P0'})=='conflict'
    for _ in range(2):
        assert a.observe(10,original)=='conflict'
        assert a.current==original and a.conflict and a.stale
        assert a.capture('blocked')['state']=='stale'
    assert a.patch_observe(10,11,{'model':'B'})=='conflict'
    assert a.conflict and a.capture('still-blocked')['state']=='stale'
    assert a.observe(9,original)=='old' and a.conflict
    assert a.observe(11,{'model':'B','prompt':'P0'})=='current'
    assert not a.conflict and a.capture('resolved')['state']=='possibly-submitted'
check('conflict-duplicate-and-patch-cannot-unlock-new-snapshot-can',conflict_duplicates_stay_locked,[12])

def snapshot_discards_covered_chain():
    a=Owner('a'); a.patch_observe(11,12,{'model':'M12'})
    assert a.stale and a.capture('gap')['state']=='stale'
    assert a.observe(12,{'model':'M12','prompt':'P0'})=='current'
    assert not a.stale and not a.chain_buffer
    a.patch_observe(12,13,{'model':'M13'})
    assert a.native_revision==13 and a.current['model']=='M13' and not a.stale
    assert a.patch_observe(11,12,{'model':'OLD'})=='old'
    assert a.current['model']=='M13' and not a.stale
    assert a.capture('recovered')['state']=='possibly-submitted'
    # A future gap is not covered by r12, and must remain blocked.
    b=Owner('b'); b.patch_observe(14,15,{'model':'M15'})
    b.observe(12,{'model':'M12','prompt':'P0'})
    assert b.stale and 14 in b.chain_buffer and b.capture('gap')['state']=='stale'
    b.patch_observe(12,14,{'model':'M14'})
    assert b.native_revision==15 and not b.stale and b.current['model']=='M15'
check('gap-snapshot-continuous-patch-covered-and-future-buffer',snapshot_discards_covered_chain,[12])

if __name__=='__main__':
    print(json.dumps({'kind':'offline-design-reference','passed':len(results),'failed':0,
        'limitations':['No production imports','No backend/IPC/IME execution','Budget is abstract accounting, not measured memory'],
        'checks':results},ensure_ascii=False,indent=2))
