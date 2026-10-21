"""Small real Units owner for Profile storage/CAS tests."""
from threading import RLock

from ordessa_agents.harness.providers.registry import HarnessCatalog
from ordessa_units.admission.fingerprint import ProtectedFingerprintHmac
from ordessa_units.admission.material_registration import MaterialCatalog
from ordessa_units.public import UnitAdmissionContext


def make_profile_unit_owner(store, policy, namespace):
    """Bind Profiles to one Units context and the same SQLite store."""
    lock = RLock()
    harness_catalog = HarnessCatalog(
        namespace, policy=policy, principal_scope="synthetic", admission_lock=lock,
    )
    material_catalog = MaterialCatalog(namespace, admission_lock=lock)
    context = UnitAdmissionContext(
        namespace,
        store=store,
        policy=policy,
        fingerprint_port=ProtectedFingerprintHmac(
            {"test": b"synthetic-profile-history-test"}, active_key_id="test",
        ),
        harness_catalog=harness_catalog,
        material_catalog=material_catalog,
        principal_scope="synthetic",
        admission_lock=lock,
    )
    return context, harness_catalog, material_catalog


def close_profile_unit_owner(context, harness_catalog, material_catalog, store):
    """Close only the test's empty catalogs, context, and SQLite store."""
    context.close()
    harness_catalog.close()
    material_catalog.close()
    store.close()
