"""One controlled real-core/journal fixture shared by configuration and native tests."""
from agent_tools_fixtures.unit_records import parts, reserve, begin, PROVIDER, NODE, ROOT
from ordessa_units.records.unit_records import UnitRecordsRefused

DIGEST = 'sha256:' + 'a' * 64


NATIVE_DIGEST = 'sha256:' + 'b' * 64


class Evidence:
    def __init__(self):
        self.valid = True
        self.change = None

    def verify_configuration(self, unit, identity, native_id, native_digest, evidence):
        if not self.valid or evidence != 'original-native-receipt':
            raise UnitRecordsRefused('original native receipt unavailable')
        result = {key: identity[key] for key in ('operationRef', 'unitRef', 'scopeRef', 'requestDigest')}
        result.update(nativeRequestId=7, nativeRequestDigest=NATIVE_DIGEST, evidenceRef=evidence)
        if self.change:
            result.update(self.change)
        return result


def real_core_parts(tmp_path, *, start_native_session=True):
    from agent_tools_fixtures.invocation_authority import Authority, CurrentState
    from ordessa_infrastructure.identifiers import RequestKey
    from ordessa_units.definitions.operations import OperationIntent, StepIntent
    from ordessa_units.public import SqliteUnitStore
    from ordessa_units.bindings.contracts import DirectoryBindingRef
    from ordessa_units.admission.invocation import InvocationIssuer
    p = parts(tmp_path)
    target = p[3].scope.owner_ref(PROVIDER)
    request = RequestKey('env', 'controlled-principal', 'unit-flow')
    directory = DirectoryBindingRef('env', 'directory', 1, 'sha256:' + 'd' * 64)
    bindings = {
        'prepare': {'action':'prepare','targetRef':NODE,'delegationRef':None,'cleanup':False},
        'start': {'action':'start','targetRef':NODE,'delegationRef':None,'cleanup':False},
        'configuration': {'action':'applyConfiguration','targetRef':target,'delegationRef':None,'cleanup':False},
    }
    store = SqliteUnitStore(tmp_path / 'core.sqlite')
    intent = OperationIntent('flow-operation','controlled-unit-flow',None,
        {'environmentNamespace':'env','directoryBindingRef':directory.to_dict(),'invocationBindings':bindings},
        (StepIntent('prepare',PROVIDER,'input','prepare-correlation'),
         StepIntent('start',PROVIDER,'start-input','start-correlation'),
         StepIntent('configuration',PROVIDER,DIGEST,'config-correlation')))
    store.reserve_operation(request, 'flow-digest', intent)
    authority = Authority()
    current = CurrentState(PROVIDER, directory, target)
    issuer = InvocationIssuer(store, authority, current, clock=lambda:50)
    p[0].verifier = issuer.verifier()
    p[0].configuration_evidence = Evidence()
    def issued(step):
        binding = bindings[step]
        return issuer.issue(request, 'flow-digest', step, binding['action'], binding['targetRef'])
    unit, _ = p[0].reserve_unit(issued('prepare'), provider_ref=PROVIDER,node_ref=NODE,
        input_digest='input',private_root_facts=ROOT)
    store.record_operation_step(request,'flow-digest','prepare','input',1,'concluded',{'unitRef':unit.unit_ref})
    if start_native_session:
        session_ticket = p[0].begin_session(unit.unit_ref, issued('start'), input_digest='start-input')
        p[0].record_session(session_ticket, expected_source_revision=2,state='confirmed',evidence='real-native-owner-evidence')
        store.record_operation_step(request,'flow-digest','start','start-input',1,'concluded',{'evidenceRef':'real-native-owner-evidence'})
    return p, unit, store, request, issuer, authority, current, issued



def setup(tmp_path):
    p = parts(tmp_path)
    unit, _ = reserve(p)
    ticket = begin(p, unit)
    p[0].record_session(ticket, expected_source_revision=2, state='confirmed', evidence='real-native-owner-evidence')
    p[0].configuration_evidence = Evidence()
    return p, unit


def context(p, unit, action='applyConfiguration', step='configuration-apply', digest=DIGEST):
    return p[2].issue(action, step, digest, node=unit.configuration_target_ref)


def opening(p, unit):
    return p[0].begin_configuration_change(unit.unit_ref, context(p, unit), input_digest=DIGEST, expected_revision='native-version-1')


def bound(p, unit):
    ticket = opening(p, unit)
    value = p[0].bind_configuration_dispatch(ticket, native_request_id=7, native_request_digest=NATIVE_DIGEST)
    assert value.state == 'opening' and value.source_revision == 2
    return ticket


def query(p, unit, service=None):
    return (service or p[0]).query_configuration_change(unit.unit_ref, 'operation',
        context(p, unit, 'query'), input_digest=DIGEST)

