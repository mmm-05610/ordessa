"""One Unit prompt, recorded by the original write lease and SQLite owner."""
from ordessa_units.records import acp_turns
from ordessa_units.lifecycle.unit_lifecycle import UnitLifecycleRefused
from ordessa_execution_agents.harness.protocols.acp import AcpRemoteError
from ordessa_execution_agents.harness.transport import EffectWriteGuard, EffectWriteRefused


def prompt(unit, unit_ref, lease, *, operation_ref, timeout, params, managed_input=None):
    if managed_input is not None:
        from ordessa_units.channels.acp_input import _ManagedAcpDispatch
        if type(managed_input) is not _ManagedAcpDispatch or managed_input.instance is not unit:
            raise UnitLifecycleRefused('Original managed ACP dispatch owner required')
    if any(key in params for key in ('on_request', 'before_write', 'on_observation',
                                   'effect_write_guard', 'effect_write_guard_factory', '_effect_write_owner')):
        raise UnitLifecycleRefused('Recorded prompt callbacks belong to original owner')
    with unit._lifecycle_lock:
        connection = unit.connect(unit_ref, lease)
        # Admission cannot reserve a durable hold using an already revoked
        # cached connection. The original per-write cut still runs again.
        unit.lease_port._require_writable(connection)
        session = unit.projection.read_session(unit_ref).native_facts['sessionId']
        if params.get('sessionId', session) != session:
            raise UnitLifecycleRefused('Recorded prompt belongs to another session')
        params = dict(params, sessionId=session)
        fields = {}
        factory = unit._effect_write_guard_factory
        if factory is not None or unit._fixed_effect_write_guard_factory is not None:
            unit.require_effect_write_guard(factory)
            from ordessa_infrastructure.encoding.immutable_json import sealed_mapping
            unit.records.validate_acp_prompt_capacity(unit_ref, params)
            input_digest = unit.records.acp_prompt_input_digest(unit_ref, params)
            guard = factory(sealed_mapping(unit_ref), operation_ref, input_digest,
                            sealed_mapping(params, max_bytes=acp_turns.MAX_PROMPT_BYTES))
            if type(guard) is not EffectWriteGuard or not guard.matches(unit_ref, operation_ref, input_digest, params):
                raise EffectWriteRefused('trusted factory returned a different operation write binding')
            fields['effect_write_guard'] = guard
            fields['_effect_write_owner'] = unit._effect_write_owner
        acp_turns.reserve(unit.records, unit_ref, operation_ref, params,
                         managed_input=None if managed_input is None else managed_input.binding)
        record = unit.channel_factory.owned_record

    # The active native-operation counter and selection fence retain the exact
    # Unit while the SDK loop waits. Holding the lifecycle lock here deadlocks
    # the SDK-thread effect guard, which must acquire the same original source
    # lock at the bounded write seam.
    def before_write(raw):
        unit._validate_selection_fences()
        if managed_input is not None:
            managed_input.before_write(unit)
        acp_turns.dispatch(unit.records, operation_ref, raw)

    try:
        connection.request('session/prompt', params,
            timeout=timeout,
            **fields,
            on_request=unit.callbacks.handle,
            before_write=before_write,
            on_observation=lambda raw:acp_turns.observe(unit.records, operation_ref, raw))
    except AcpRemoteError as error:
        try:
            return acp_turns.finish(unit.records, operation_ref, 'failed', record.entry._last_response)
        except Exception:
            acp_turns.finish(unit.records, operation_ref, 'unknown')
            raise
    except Exception:
        acp_turns.finish(unit.records, operation_ref, 'unknown')
        raise
    try:
        return acp_turns.finish(unit.records, operation_ref, 'completed', record.entry._last_response)
    except Exception:
        acp_turns.finish(unit.records, operation_ref, 'unknown')
        raise
