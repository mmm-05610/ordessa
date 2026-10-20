"""Product-selected catalogs and original Unit store close ordering."""
from threading import RLock
from ordessa_units.errors import UnitGuaranteeUnavailable
from ordessa_execution_agents.harness.providers.registry import HarnessCatalog
from ordessa_units.admission.context import UnitAdmissionContext
from ordessa_units.admission.material_registration import MaterialCatalog


def create_unit_admission(namespace, *, store, policy, fingerprint_port, context_type=UnitAdmissionContext):
    lock = RLock()
    holder = {}
    def retirement_guard(owner, generation):
        return holder['context'].provider_retirement_guard(owner, generation)
    def harness_retirement_guard(owner, generation):
        return holder['context'].harness_provider_retirement_guard(owner, generation)
    harness = HarnessCatalog(namespace, policy=policy, admission_lock=lock,
                             retirement_guard=harness_retirement_guard)
    material = MaterialCatalog(namespace, admission_lock=lock,
                               retirement_guard=retirement_guard)
    context = context_type(namespace, store=store, policy=policy,
                           fingerprint_port=fingerprint_port, harness_catalog=harness,
                           material_catalog=material, admission_lock=lock)
    holder['context'] = context
    return context


def close_unit_admission(context):
    context.drain()
    if any(context.pending().values()):
        raise UnitGuaranteeUnavailable('Unit pending records retain the original store and root owner')
    # Root contribution handlers must retire their exact generations first.
    # Catalog close refuses remaining staged/active registrations.
    if not getattr(context, '_root_harness_closed', False):
        context.harness_catalog.close()
        context._root_harness_closed = True
    if not getattr(context, '_root_material_closed', False):
        context.material_catalog.close()
        context._root_material_closed = True
    UnitAdmissionContext.close(context)
