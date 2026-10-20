"""Server consumes the active Engineering75 review-check owner seam."""
import pytest

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.check_capabilities import mechanical_review_check_capabilities
from ordessa_engineering.application.usecases.reviews.admission import EngineeringReviewAdmission
from ordessa_server.composition.engineering import EngineeringServerPlugin
from ordessa_server.composition import engineering_capability_catalog as catalog_module
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_system_access_bindings.engineering_wire import EngineeringApplicationPorts


def test_catalog_passes_current_factory_access_scope_and_publishes_owner_checks(tmp_path, monkeypatch):
    authority = InstanceAccessAuthority(lambda: "catalog-token", principal_id="catalog-user",
        legacy_principal=None, grants=())
    path = tmp_path / "catalog.sqlite"
    library = EngineeringLibrary.create(path.resolve(), library_id="catalog-amendment75", schema_version=10)
    library.close()
    scope = Scope("r", "p")
    seen = []
    check_capabilities = mechanical_review_check_capabilities()

    def ports_factory(factory, access, selected_scope):
        methods = SQLiteMethodControl(factory, SQLiteSnapshotStore(factory.library))
        admission = EngineeringReviewAdmission(factory, methods, None, object())
        return EngineeringApplicationPorts(review_admission=admission)

    def read_checks(admission, *, expected_factory, expected_access, expected_scope):
        seen.append((admission, expected_factory, expected_access, expected_scope))
        return check_capabilities

    monkeypatch.setattr(catalog_module, "bound_review_check_capabilities", read_checks)
    plugin = EngineeringServerPlugin(path=path, library_id="catalog-amendment75", scope=scope,
        authority_resolver=lambda: authority, application_ports_factory=ports_factory)
    registration = plugin.build(None)
    try:
        result = plugin.capability_catalog().read_current()
        binding = plugin._binding_for(authority)
        assert len(seen) == 1
        assert seen[0] == (binding.ports.review_admission, binding.factory, binding.access, scope)
        assert set(d.capability_id for d in result.capabilities) >= {
            d.capability_id for d in check_capabilities.capabilities
        }
        assert all(d in result.capabilities for d in check_capabilities.capabilities)
        assert result.trust_class == "host"
    finally:
        registration.disposal()
