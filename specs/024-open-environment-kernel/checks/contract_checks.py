#!/usr/bin/env python3
"""Finite normative examples for spec024; no product imports or external I/O.

These checks demonstrate that the written safety rules have executable
positive/counterexamples. They are not an implementation or concurrency proof.
Only the named files under the task directory are read; stdout is the report.
"""
import hashlib
import hmac
import itertools
import json
from pathlib import Path


class Refusal(Exception):
    pass


def require(condition, code):
    if not condition:
        raise Refusal(code)


def refused(fn, code=None):
    try:
        fn()
    except Refusal as exc:
        require(code is None or str(exc) == code, 'WRONG_REFUSAL')
        return
    raise AssertionError('counterexample did not refuse')


class Gate:
    """Serialized reference transition relation, NOT a threaded runtime."""
    def __init__(self, env='E', generation=1, instance_id='I'):
        self.env, self.generation, self.instance_id = env, generation, instance_id
        self.state, self.store_readable = 'active', True
        self.objects, self.usages, self.pins, self.unknown = {}, {}, set(), set()
        self.owed, self.issued, self.claims = {}, {}, set()
        self.db_calls = self.acquire_calls = 0

    def ref(self, obj):
        return (self.env, 'Object', self.instance_id, self.generation, obj)

    def validate(self, ref):
        require(isinstance(ref, tuple) and len(ref) == 5, 'STALE_OR_FOREIGN')
        require(ref[:4] == (self.env, 'Object', self.instance_id, self.generation), 'STALE_OR_FOREIGN')
        require(ref[4] in self.objects, 'MISSING_OBJECT')

    def create_object(self, obj, owned=True):
        self.objects[obj] = {'state': 'available', 'owned': owned}

    def use(self, ref, subject, rights=('use',), caller='alice'):
        self.validate(ref)
        require(subject == caller and set(rights) <= {'use', 'read'}, 'NO_GRANT')
        require(self.state == 'active', 'DRAINING')
        require(self.objects[ref[4]]['state'] == 'available', 'CLOSING')
        key = (ref[4], subject)
        self.usages[key] = tuple(rights)
        return key

    def release(self, usage, caller):
        require(usage[1] == caller, 'NOT_HOLDER')
        self.usages.pop(usage, None)

    def begin_destroy(self, ref, manager=True):
        self.validate(ref)
        obj = ref[4]
        require(manager, 'NO_DESTROY_RIGHT')
        require(self.objects[obj]['owned'], 'BORROWED')
        require(not any(key[0] == obj for key in self.usages), 'BUSY')
        require(not self.pins, 'BUSY')
        require(self.objects[obj]['state'] == 'available', 'CLOSING')
        self.objects[obj]['state'] = 'closing'
        self.unknown.add('destroy:' + obj)

    def finish_destroy(self, obj, proven):
        self.objects[obj]['state'] = 'released' if proven else 'unknown'
        if proven:
            self.unknown.discard('destroy:' + obj)

    def drain(self):
        self.state = 'draining'

    def admit(self, target, closure=False):
        require(self.state == 'active' or closure, 'DRAINING')
        if closure:
            require(target in self.unknown or target in self.objects, 'NOT_EXISTING_OBLIGATION')
        pin = 'pin:' + target
        self.pins.add(pin)
        return pin

    def retire(self):
        require(self.store_readable, 'FACTS_UNREADABLE')
        require(not self.pins and not self.usages and not self.unknown and not self.owed, 'BUSY')
        require(not any(v['owned'] and v['state'] != 'released' for v in self.objects.values()), 'LIVE_OWNED')
        self.state = 'retired'

    def reserve(self, key, payload, binding='g1', store=True, effect=True):
        require(store or not effect, 'DURABLE_REQUIRED')
        digest = hashlib.sha256((payload + ':' + binding).encode()).hexdigest()
        if key in self.issued:
            require(self.issued[key]['digest'] == digest, 'DIGEST_CONFLICT')
            return False
        self.issued[key] = {'digest': digest, 'phase': 'intent', 'result': None}
        self.unknown.add('activity:' + key)
        return True

    def issue(self, key):
        require(key not in self.claims, 'CLAIM_SPENT')
        self.claims.add(key)
        self.issued[key]['phase'] = 'issue_possible'

    def lookup_request(self, key, history_read=False):
        # Permission is checked before presence, including an absent key.
        require(history_read, 'HISTORY_READ_REQUIRED')
        return self.issued.get(key)

    def invoke_request(self, key, payload, *, invoke=False, history_read=False):
        if key in self.issued:
            self.lookup_request(key, history_read=history_read)
            self.reserve(key, payload)  # same binding/input only; zero new issue
            return 'replay'
        require(invoke, 'INVOKE_REQUIRED')
        self.reserve(key, payload)
        self.issue(key)
        return 'issued'


class Evidence:
    def __init__(self):
        self.revision, self.value, self.current = -1, None, 'pending'
        self.receipts = []

    def accept(self, revision, value, role='effect', enough=True):
        if role != 'effect' or not enough:
            return
        if revision < self.revision:
            return
        if revision == self.revision:
            if value != self.value:
                self.current = 'disputed'
            return
        self.revision, self.value, self.current = revision, value, value
        self.receipts.append((revision, value))


def dependency_order(graph):
    done, visiting = set(), set()
    def visit(node):
        require(node in graph, 'DEPENDENCY_MISSING')
        require(node not in visiting, 'CYCLE')
        if node in done:
            return
        visiting.add(node)
        for dep in graph[node]:
            visit(dep)
        visiting.remove(node)
        done.add(node)
    for node in graph:
        visit(node)
    return done


def cases():
    g = Gate()
    require(dependency_order({}) == set(), 'EMPTY_ENV')
    refused(lambda: dependency_order({'plugin': ['missing']}), 'DEPENDENCY_MISSING')
    yield 'S01', 'empty environment / dependency absence'

    a, b = Gate(generation=1), Gate(generation=2)
    a.drain(); b.create_object('O')
    b.use(b.ref('O'), 'alice')
    require(b.state == 'active', 'INSTANCE_LEAK')
    yield 'S02', 'independent instance generations'

    g.create_object('S'); receipt = 'create_success'; subscription = 'closed'
    require(receipt == 'create_success' and subscription == 'closed' and g.objects['S']['state'] == 'available', 'OBJECT_LIFETIME')
    yield 'S03', 'creation/detach does not end object'

    rounds = [('S', 'send1'), ('S', 'send2')]
    require(len({r[0] for r in rounds}) == 1, 'SESSION_MIRROR')
    yield 'S04', 'multiple ingress activities / one native session'

    unknown = b'{"command":"/workflow","vendorField":23}'
    sent = bytes(unknown)
    require(sent == unknown, 'OPAQUE_CROPPED')
    yield 'S05', 'unknown native payload preserved'
    refused(lambda: require(False, 'ADAPTER_GAP'), 'ADAPTER_GAP')
    yield 'S06', 'UI-only feature cannot claim reachability'

    e = Evidence(); e.accept(1, 'cancelled', role='opaque')
    require(e.current == 'pending', 'UNKNOWN_AS_TERMINAL')
    yield 'S07', 'opaque payload is not outcome evidence'

    observation_capacity, control_capacity = 2, 1
    obs, controls, gaps = [], [], 0
    for i in range(20):
        if len(obs) == observation_capacity:
            gaps += 1
        else:
            obs.append(i)
    controls.append('Q')
    refused(lambda: require(len(controls) < control_capacity, 'CONTROL_DELIVERY_FAILED'), 'CONTROL_DELIVERY_FAILED')
    require(len(obs) == 2 and gaps == 18 and controls == ['Q'], 'UNBOUNDED_OR_DROPPED_CONTROL')
    yield 'S08', 'bounded observation gap / independent control capacity'

    light = Gate(); pin = light.admit('query'); light.pins.remove(pin)
    require(light.db_calls == light.acquire_calls == 0, 'HEAVY_QUERY')
    refused(lambda: light.reserve('send', 'input', store=False), 'DURABLE_REQUIRED')
    yield 'S09', 'memory query pin / effect missing store refusal'

    d = Gate(); require(d.reserve('K', 'input'), 'FIRST_RESERVATION')
    require(not d.reserve('K', 'input'), 'DUPLICATE_DISPATCH')
    d.issue('K')
    refused(lambda: d.issue('K'), 'CLAIM_SPENT')
    refused(lambda: d.reserve('K', 'different'), 'DIGEST_CONFLICT')
    refused(lambda: d.reserve('K', 'input', binding='g2'), 'DIGEST_CONFLICT')
    yield 'S10', 'same key replay / conflict / spent claim'

    for crash in ('intent_before', 'intent_after', 'issue_possible', 'receipt_before_commit', 'result_after_commit'):
        may_send = crash not in ('intent_before', 'intent_after')
        current = 'success' if crash == 'result_after_commit' else ('unknown' if may_send else 'not_sent')
        require(not (may_send and current == 'not_sent'), 'CRASH_GUESSED_UNSENT')
    yield 'S11', 'five finite crash cuts; real process crashes remain future tests'

    e.accept(1, 'cancelled', enough=False)
    require(e.current == 'pending', 'CANCEL_ACK_AS_STOP')
    e.accept(2, 'success'); original = tuple(e.receipts)
    e.accept(2, 'cancelled')
    require(e.current == 'disputed' and tuple(e.receipts) == original, 'RECEIPT_REWRITE')
    e.accept(3, 'success')
    require(e.current == 'success', 'RECONCILIATION_FAILED')
    yield 'S12', 'cancel acknowledgement / conflict / immutable receipts'

    d.drain(); old_claims = set(d.claims)
    p = d.admit('activity:K', closure=True); d.pins.remove(p)
    require(d.claims == old_claims and 'activity:K' in d.unknown, 'RESTART_REISSUE')
    refused(d.retire, 'BUSY')
    yield 'S13', 'unknown preserved / closure admitted / no reissue'

    share = Gate(); share.create_object('O')
    u1 = share.use(share.ref('O'), 'alice')
    u2 = share.use(share.ref('O'), 'bob', caller='bob')
    share.release(u1, 'alice')
    require(u2 in share.usages, 'OTHER_USAGE_LOST')
    refused(lambda: share.begin_destroy(share.ref('O')), 'BUSY')
    refused(lambda: share.release(u2, 'alice'), 'NOT_HOLDER')
    yield 'S14', 'shared usage / destroy and release authority'

    refused(lambda: share.use(('F', 1, 'O'), 'alice'), 'STALE_OR_FOREIGN')
    refused(lambda: share.use(('E', 0, 'O'), 'alice'), 'STALE_OR_FOREIGN')
    refused(lambda: share.use(share.ref('O'), 'alice', rights=('destroy',)), 'NO_GRANT')
    yield 'S15', 'foreign/stale reference / self escalation refusal'

    refused(lambda: dependency_order({'A': ['B'], 'B': ['A']}), 'CYCLE')
    held, requested = 2, 1
    refused(lambda: require(requested > held, 'WOULD_BLOCK'), 'WOULD_BLOCK')
    result = {'children': ['success', 'failure'], 'primary': 'B_FAILED', 'cleanup': ['CLEANUP_FAILED']}
    require(result['children'][0] == 'success' and result['primary'] and result['cleanup'], 'PARTIAL_ERASED')
    yield 'S16', 'separate ordering counterexample / partial effects preserved'

    own = Gate(); own.create_object('J'); own.drain()
    refused(own.retire, 'LIVE_OWNED')
    pin = own.admit('J', closure=True)
    refused(lambda: own.admit('new'), 'DRAINING')
    own.pins.remove(pin); own.begin_destroy(own.ref('J')); own.finish_destroy('J', True); own.retire()
    hidden = Gate(); hidden.owed['unpublished-start'] = 'unknown'; refused(hidden.retire, 'BUSY')
    unreadable = Gate(); unreadable.store_readable = False; refused(unreadable.retire, 'FACTS_UNREADABLE')
    yield 'S17', 'drain / live and unpublished obligations / unreadable facts'

    snapshot = {'environment': 'r1', 'native': 'observed-only'}
    original = dict(snapshot)
    native_now = 'r2'
    require(snapshot == original and native_now != snapshot['environment'], 'NATIVE_FREEZE_FALSE_CLAIM')
    refused(lambda: require(snapshot['native'] == 'enforced', 'GUARANTEE_UNAVAILABLE'), 'GUARANTEE_UNAVAILABLE')
    yield 'S18', 'environment revision versus mutable native / required guarantee'

    history = {'kind': 'activity', 'result': 'unknown', 'decoder': 'unavailable', 'generation': 1}
    reinstall = Gate(generation=2); reinstall.create_object('O')
    refused(lambda: reinstall.validate(('E', history['generation'], 'O')), 'STALE_OR_FOREIGN')
    require(history['result'] == 'unknown' and history['decoder'] == 'unavailable', 'HISTORY_FAKE_RESTORE')
    yield 'S19', 'minimum history / reinstall cannot revive old handle'

    entry = Gate()
    for transport in ('http', 'cli', 'local'):
        entry.reserve('same-key', 'same-input')
    require(len(entry.issued) == 1, 'MULTIPLE_AUTHORITIES')
    yield 'S20', 'one reference admission table across ingress names'

    # Enumerate all two-operation gate orderings: safety is a transition rule,
    # not a lucky thread schedule. A threaded implementation needs its own I gate.
    for ordering in itertools.permutations(('use', 'destroy')):
        concurrent = Gate(); concurrent.create_object('O')
        for action in ordering:
            if action == 'use':
                if concurrent.objects['O']['state'] == 'closing':
                    refused(lambda: concurrent.use(concurrent.ref('O'), 'alice'), 'CLOSING')
                else:
                    concurrent.use(concurrent.ref('O'), 'alice')
            elif concurrent.usages:
                refused(lambda: concurrent.begin_destroy(concurrent.ref('O')), 'BUSY')
            else:
                concurrent.begin_destroy(concurrent.ref('O'))
        require(not (concurrent.usages and concurrent.objects['O']['state'] == 'closing'), 'GATE_RACE')
    yield 'X01', 'all two-operation use/destroy reference permutations'

    # Atomic handoff states: none of the allowed cuts lose the obligation.
    handoff_states = [({'startup'}, set()), ({'object:O'}, {'O'})]
    for obligations, output_objects in handoff_states:
        require('startup' in obligations or ('object:O' in obligations and 'O' in output_objects), 'HANDOFF_GAP')
    refused(lambda: require(False, 'HANDOFF_GAP'), 'HANDOFF_GAP')
    yield 'X02', 'obligation continuity across abstract create completion transaction'

    fixture_key = b'non-secret-offline-fixture-key'
    full_a, full_b = b'{"unknown":{"secret":"a","act":"deploy"}}', b'{"unknown":{"secret":"b","act":"delete"}}'
    def protected_fp(payload, port=True):
        require(port, 'FINGERPRINT_UNAVAILABLE')
        return hmac.new(fixture_key, b'E:alice:surface:' + payload, hashlib.sha256).digest()
    require(protected_fp(full_a) != protected_fp(full_b), 'OPAQUE_FALSE_EQUAL')
    refused(lambda: protected_fp(full_a, False), 'FINGERPRINT_UNAVAILABLE')
    yield 'X03', 'full-input keyed fixture comparison / absent fingerprint port'

    saved = {'K': {'binding': 'g1', 'receipt': 'success', 'current': 'success'}}
    active_bindings = set()
    require(saved['K']['receipt'] == 'success' and not active_bindings, 'HISTORY_NEEDS_ACTIVE_BINDING')
    refused(lambda: require(saved['K']['binding'] == 'g2', 'DIGEST_CONFLICT'), 'DIGEST_CONFLICT')
    yield 'X04', 'history lookup independent of active binding'

    obs1, obs2 = ('observer-g1', 40), ('observer-g2', 1)
    require(obs1[0] != obs2[0], 'SOURCE_EPOCH_COLLAPSE')
    refused(lambda: require(obs1[0] == obs2[0], 'LOCAL_SEQUENCES_INCOMPARABLE'), 'LOCAL_SEQUENCES_INCOMPARABLE')
    yield 'X05', 'observer sequence epochs cannot be ordered as native revisions'

    for winner, loser in itertools.permutations(('K1', 'K2')):
        slot, sends = {}, []
        def answer(key, input_fp):
            if 'Q' in slot:
                previous = slot['Q']
                require(previous == (key, input_fp), 'REPLY_SLOT_SPENT')
                return 'replay'
            slot['Q'] = (key, input_fp)
            sends.append(key)
            return 'issue'
        require(answer(winner, 'yes') == 'issue', 'NO_FIRST_REPLY')
        require(answer(winner, 'yes') == 'replay', 'REPLAY_NEEDS_HOLD')
        refused(lambda: answer(loser, 'no'), 'REPLY_SLOT_SPENT')
        require(sends == [winner], 'TWO_CONTROL_REPLIES')
    yield 'X06', 'response-slot unique across request keys / spent-hold read replay'

    admission_cut, roots, dependencies = 5, {'A': 4}, {('A', 'B-resource')}
    def closure(root, child, proof, dependency=None):
        require(root in roots and roots[root] <= admission_cut and proof, 'OUTSIDE_CLOSURE')
        require(dependency is None or (root, dependency) in dependencies, 'NEW_DEPENDENCY')
        return child
    require(closure('A', 'late-O', True) == 'late-O', 'LATE_OBJECT_REJECTED')
    require(closure('A', 'new-Q', True) == 'new-Q', 'CLOSURE_CONTROL_REJECTED')
    closure('A', 'read-B', True, 'B-resource')
    refused(lambda: closure('new-root', 'Q', True), 'OUTSIDE_CLOSURE')
    refused(lambda: closure('A', 'read-new', True, 'C-resource'), 'NEW_DEPENDENCY')
    refused(lambda: closure('A', 'forged-Q', False), 'OUTSIDE_CLOSURE')
    yield 'X07', 'late results / required control / existing dependency closure scope'

    unclear = Gate(); unclear.owed['scope:S'] = 'unclassified-delivery'
    refused(unclear.retire, 'BUSY')
    require(unclear.owed['scope:S'] == 'unclassified-delivery', 'GAP_DROPPED_OBLIGATION')
    yield 'X08', 'unknown delivery role produces a scope obligation'

    def retirement_scope(owned, scope_proven, own_links_clear):
        require(scope_proven if owned else own_links_clear, 'SCOPE_UNRESOLVED')
    refused(lambda: retirement_scope(True, False, True), 'SCOPE_UNRESOLVED')
    retirement_scope(True, True, True); retirement_scope(False, False, True)
    yield 'X09', 'owned scope evidence / borrowed relationship distinction'

    waits = {'X-held-A': ['Y-held-B'], 'Y-held-B': []}
    dependency_order(waits)
    refused(lambda: dependency_order({'X-held-A': ['Y-held-B'], 'Y-held-B': ['X-held-A']}), 'CYCLE')
    yield 'X10', 'asynchronous waits are still edges in the reference wait graph'

    static = Gate(); static.create_object('version')
    body = b'existing immutable content'
    snapshot_body = bytes(body)
    static.objects['version']['state'] = 'released'  # local projection relation, no external delete
    static.drain(); static.retire()
    require(body == snapshot_body and static.db_calls == 0, 'STATIC_RETIRE_DESTRUCTIVE')
    yield 'X11', 'memory static relationship retirement preserves content'

    decoder = Gate(); pin = decoder.admit('decode')
    decoder.drain(); refused(decoder.retire, 'BUSY')
    refused(lambda: require('codec-v1' in {'codec-v2'}, 'DECODER_UNAVAILABLE'), 'DECODER_UNAVAILABLE')
    decoder.pins.remove(pin); decoder.retire()
    yield 'X12', 'decoder version compatibility / pin until result encoding'

    i1, i2 = Gate(instance_id='I1'), Gate(instance_id='I2')
    i1.create_object('S'); i2.create_object('S')
    require(i1.ref('S') != i2.ref('S'), 'INSTANCE_ID_COLLISION')
    i1.validate(i1.ref('S')); i2.validate(i2.ref('S'))
    refused(lambda: i2.use(i1.ref('S'), 'alice'), 'STALE_OR_FOREIGN')
    refused(lambda: i1.use(i2.ref('S'), 'alice'), 'STALE_OR_FOREIGN')
    refused(lambda: i1.validate(('E', 1, 'S')), 'STALE_OR_FOREIGN')
    refused(lambda: i1.validate(('E', 'Activity', 'I1', 1, 'S')), 'STALE_OR_FOREIGN')
    yield 'X13', 'same-generation same-object-id / complete typed instance identity'

    replay = Gate()
    require(replay.invoke_request('K', 'payload', invoke=True) == 'issued', 'FIRST_INVOKE')
    before = (dict(replay.issued), set(replay.claims))
    refused(lambda: replay.invoke_request('K', 'payload', invoke=True), 'HISTORY_READ_REQUIRED')
    require(replay.invoke_request('K', 'payload', history_read=True) == 'replay', 'READ_ONLY_REPLAY')
    refused(lambda: replay.invoke_request('K', 'changed', history_read=True), 'DIGEST_CONFLICT')
    refused(lambda: replay.lookup_request('K'), 'HISTORY_READ_REQUIRED')
    refused(lambda: replay.lookup_request('absent'), 'HISTORY_READ_REQUIRED')
    refused(lambda: replay.invoke_request('new', 'payload', history_read=True), 'INVOKE_REQUIRED')
    require(before == (replay.issued, replay.claims), 'REPLAY_CHANGED_EFFECTS')
    yield 'X14', 'invoke permission cannot substitute for current history-read / zero reissue'


def main():
    root = Path(__file__).resolve().parents[1]
    require((root / 'scenarios.md').is_file(), 'SCENARIOS_ABSENT')
    scenario_text = (root / 'scenarios.md').read_text()
    results = list(cases())
    expected = {'S%02d' % i for i in range(1, 21)}
    require(expected <= {key for key, _ in results}, 'SCENARIOS_NOT_EXECUTED')
    require(all('| ' + key + ' /' in scenario_text for key in expected), 'SCENARIOS_UNDOCUMENTED')
    print(json.dumps({'verification_level': 'O: finite normative reference examples only',
                      'production_imports': False, 'service_or_model_calls': False,
                      'checks': [{'id': key, 'result': 'pass', 'claim': claim} for key, claim in results],
                      'count': len(results), 'implementation_tests': 'not run'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
