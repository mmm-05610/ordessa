"""One ACP session option write per original UnitRecords attempt.

No Profile mutation, multi-setter batching, retry, recovery write or native CAS
claim. Confirmation needs the original same-channel owner and actual readback.
"""
import hashlib
from collections.abc import Mapping

from ordessa_infrastructure.encoding.immutable_json import safe_json, sealed_mapping
from ordessa_units.lifecycle.unit_lifecycle import UnitLifecycleRefused, plain, same_reference


def current(unit_instance, unit, context, expected):
    facts = unit_instance.projection.revalidate_configuration(unit, context)
    if (not isinstance(facts, Mapping) or facts.get('query') is not False
            or facts.get('action') != 'applyConfiguration'
            or not same_reference(facts, expected)
            or not same_reference(facts.get('providerRef'),unit.facts['providerRef'])
            or not same_reference(facts.get('targetRef'),unit.configuration_target_ref)
            or type(facts.get('managementEpoch')) is not int
            or facts.get('managementEpoch') != unit.facts['managementEpoch']):
        raise UnitLifecycleRefused('Current original configuration authority changed')
    return facts


def ready(instance):
    owner = instance.projection
    if (instance.records.configuration_evidence is not owner
            or not callable(getattr(owner,'configuration_authority',None))):
        raise UnitLifecycleRefused('Original configuration/evidence owner unavailable')


def snapshot(instance, unit_ref, grant):
    ready(instance)
    unit = instance._unit_record(unit_ref)
    connection = instance.connect(unit_ref,grant)
    return sealed_mapping(instance.projection.observe_configuration(unit,connection))


def set_option(instance, unit_ref, grant, *, config_id, value, expected_revision, invocation_context):
    ready(instance)
    unit = instance._unit_record(unit_ref)
    with instance._lifecycle_lock:
        connection = instance.connect(unit_ref,grant)
        before = instance.projection.observe_configuration(unit,connection)
        selected = [o for o in before['configOptions'] if isinstance(o,dict) and o.get('id')==config_id]
        if len(selected)!=1 or selected[0].get('type')!='select':
            raise UnitLifecycleRefused('Configuration is not an exposed ACP select option; no rebuild fallback')
        values = {o.get('value') for o in selected[0].get('options',[]) if isinstance(o,dict) and isinstance(o.get('value'),str)}
        if type(value) is not str or value not in values:
            raise UnitLifecycleRefused('Configuration value is not negotiated by this session')
        if before['sourceRevision']!=expected_revision:
            raise UnitLifecycleRefused('Observed configuration revision differs before claim')
        facts = plain(invocation_context.facts)
        ticket = instance.records.begin_configuration_change(unit.unit_ref,invocation_context,
            input_digest=facts['inputDigest'],expected_revision=expected_revision)
        revision=1; request=None
        try:
            current(instance,unit,invocation_context,facts)
            # Native query under the canonical Unit owner lock, before frozen
            # dispatch. The bridge provides no cross-process native CAS.
            dispatch_before = instance.projection.observe_configuration(unit,connection)
            if dispatch_before['sourceRevision']!=expected_revision:
                raise UnitLifecycleRefused('Native configuration changed before dispatch')
            def guard(payload):
                nonlocal revision,request
                current(instance,unit,invocation_context,facts)
                # Called INSIDE the original transport writer barrier. Revoke
                # remains effective before actual bytes leave that barrier.
                connection._port._require_writable(connection)
                request = plain(payload)
                bound = instance.records.bind_configuration_dispatch(ticket,native_request_id=payload['id'],
                    native_request_digest='sha256:'+hashlib.sha256(safe_json(payload).encode()).hexdigest())
                revision=bound.source_revision
            connection.command('session/set_config_option',sessionId=before['sessionId'],configId=config_id,
                value=value,timeout=instance.channel_factory.timeout,before_write=guard)
            receipt = plain(instance.channel_factory.owned_record.entry._last_response)
            current(instance,unit,invocation_context,facts)
            after = instance.projection.observe_configuration(unit,connection)
            evidence=instance.projection.capture_configuration(unit,facts,request,receipt,before,after)
            current(instance,unit,invocation_context,facts)
            attempt=instance.records.record_configuration_change(ticket,expected_source_revision=revision,
                state='confirmed',evidence=evidence)
        except Exception:
            # Unknown owns the original attempt and fence; no new write ticket
            # and no assertion that a failed ACK means no native effect.
            instance.lease_port.revoke(unit_ref)  # retained unknown cuts every borrowed writer
            attempt=instance.records.record_configuration_change(ticket,expected_source_revision=revision,state='unknown')
            return {'state':attempt.state,'operationRef':facts['operationRef'],'temporary':True}

        return {'state':attempt.state,'operationRef':facts['operationRef'],'temporary':True,
                'profileRevision':instance.prepared_agent.profile_revision,'snapshot':after}
