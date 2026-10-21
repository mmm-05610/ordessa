"""Compose a selected ACP Unit on the original deployment-owned records.

Applications select concrete environment/Harness capabilities here, once.
They do not construct Unit internals or receive another store/issuer/ledger.
"""
from ordessa_agents.profiles import decode_revision_ref
from ordessa_units.admission.owner_selection import FreshUnitFactory, AgentOwnerUnavailable
from ordessa_units.admission.owner_ports import AgentProviderView
from ordessa_units.management import UnitInstance
from ordessa_units.lifecycle.unit_lifecycle import same_reference


def build_fresh_acp_unit_factory(*, agent_id, profile_revision, descriptor,
                                environment_instance, environment_reference,
                                environment_sharing, preparation, materializer,
                                evidence, lease_port, timeout=10,
                                callback_approval=None, effect_write_guard_factory=None,
                                process_binding_factory=None,
                                defer_effect_write_guard_factory=False,
                                acp_turn_opt_in=False):
    """Return the existing FreshUnitFactory for one explicit fixed selection.

    ``evidence`` is the deployment's original session/termination evidence;
    it is attached to original records by the existing owner composition.
    ``lease_port`` is the existing deployment authority's connection owner.
    Neither is constructed, granted or replaced by this builder.

    An optional trusted ``process_binding_factory(instance, agent_id, sharing)``
    supplies the product's neutral capability/attach/fix_start/close port for
    transient process inputs. Units never reads a credential source or imports
    the application implementing that port. No ambient credential fallback.
    """
    from ordessa_units.definitions import UnitDefinition
    selection = UnitDefinition(agent_id, preparation.harness_id, profile_revision,
                               environment_reference)
    if (type(environment_sharing) is not bool or not callable(materializer)
            or not callable(getattr(environment_instance, 'acquire', None))
            or not callable(getattr(lease_port, 'bind', None))
            or process_binding_factory is not None and not callable(process_binding_factory)
            or type(defer_effect_write_guard_factory) is not bool
            or type(acp_turn_opt_in) is not bool):
        raise AgentOwnerUnavailable('Explicit fixed ACP environment and provider ports required')
    if defer_effect_write_guard_factory and (effect_write_guard_factory is not None or not acp_turn_opt_in):
        raise AgentOwnerUnavailable('Deferred effect-write factory requires opted-in ACP and an unbound initial factory')
    guard_factory_state = {
        'factory': effect_write_guard_factory,
        'finalized': not defer_effect_write_guard_factory,
    }
    if (selection.environment_reference is None
            or selection.environment_reference.get('environmentId') != getattr(environment_instance, 'identity', None)
            or not isinstance(getattr(environment_instance, 'identity', None), str)):
        raise AgentOwnerUnavailable('Selected Environment reference and original instance differ')
    if descriptor.definition_ref.get('environmentNamespace') != profile_revision.environment_namespace:
        raise AgentOwnerUnavailable('Harness definition namespace is invalid')

    def create(environment_id, plan, provider_view):
        if not guard_factory_state['finalized']:
            raise AgentOwnerUnavailable('Effect-write factory must be finalized before Unit construction')
        snapshot = plan.get('profileSnapshot', {})
        revision = decode_revision_ref(dict(snapshot.get('ref', {})))
        definition_ref = snapshot.get('manifest', {}).get('harnessDefinitionRef')
        if (type(provider_view) is not AgentProviderView
                or getattr(environment_id, 'value', None) != selection.profile_revision.environment_namespace
                or revision != selection.profile_revision
                or not same_reference(definition_ref, descriptor.definition_ref)):
            raise AgentOwnerUnavailable('Factory requires its exact selected Profile and Harness')
        records, verifier = provider_view.records, provider_view.verifier
        from ordessa_units.records import UnitRecords
        if (type(records) is not UnitRecords or records.verifier is not verifier or records.native_evidence is not evidence
                or records.termination_evidence is not evidence or getattr(evidence, 'records', None) is not records):
            raise AgentOwnerUnavailable('Factory must retain original evidence/records/verifier')
        binding = None
        instance = environment_instance
        if process_binding_factory is not None:
            binding = process_binding_factory(instance, selection.agent_id, environment_sharing)
            if (any(not callable(getattr(binding, name, None))
                    for name in ('attach', 'fix_start', 'close'))
                    or not callable(getattr(getattr(binding, 'capability', None), 'acquire', None))
                    or getattr(binding.capability, 'identity', None) != environment_instance.identity):
                raise AgentOwnerUnavailable('Explicit fixed process capability binding required')
            instance = binding.capability
        unit = UnitInstance(descriptor=descriptor, agent_id=selection.agent_id,
            profile_revision=selection.profile_revision, environment_instance=instance,
            environment_sharing=environment_sharing,
            environment_reference=selection.environment_reference,
            preparation=preparation, materializer=materializer,
            records=records, projection=evidence, verifier=verifier,
            lease_port=lease_port, termination_evidence=evidence, timeout=timeout,
            callback_approval=callback_approval,
            effect_write_guard_factory=guard_factory_state['factory'],
            process_binding=binding)
        if binding is not None:
            binding.attach(unit)
        return unit

    def finalize_effect_write_guard_factory(factory):
        if (not defer_effect_write_guard_factory or guard_factory_state['finalized']
                or guard_factory_state['factory'] is not None or not callable(factory)):
            raise AgentOwnerUnavailable('Deferred effect-write factory can be finalized exactly once')
        guard_factory_state['factory'] = factory
        guard_factory_state['finalized'] = True

    return FreshUnitFactory(
        create,
        finalize_effect_write_guard_factory=(
            finalize_effect_write_guard_factory if defer_effect_write_guard_factory else None
        ),
    )


__all__ = ['build_fresh_acp_unit_factory']
