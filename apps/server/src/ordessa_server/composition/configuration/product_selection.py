"""Explicit test/deployment composition of the selected Product with Host ports."""
from ordessa_server_product.composition import create_composition as select_product_composition
from ordessa_server.bootstrap.migrations.legacy_source import register_legacy_migrations
from ordessa_server.bootstrap.storage.product_database import Database
from ordessa_units.assembly.runtime.assembler import assemble_runtime_composition
from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog
from ..runtime import build_runtime
from ordessa_system_access_bindings import agent_core_methods
from ..product_unit_admission import create_product_unit_admission, create_owned_product_unit_admission
from ordessa_units.public import (
    AgentOwnerUnavailable, validate_agent_owner_selection,
)
from ordessa_server.bootstrap.security import secret_service


def create_host_product_composition(*, pi_selection=None, pi_ports=None, **kwargs):
    selected_pi = None
    if pi_selection is not None or pi_ports is not None:
        if any(kwargs.get(name) is not None for name in
               ('agent_owner_inputs', 'fingerprint_port', 'pi_definition_declaration')):
            raise AgentOwnerUnavailable('Pi selection cannot replace another selected owner')
        from ..pi_selection import select_pi_execution
        selected_pi = select_pi_execution(pi_selection, pi_ports)
        kwargs.update(fingerprint_port=pi_ports.fingerprint,
                      pi_definition_declaration=pi_ports.declaration,
                      execution_selection=selected_pi.describe,
                      execution_configurer=selected_pi.bind_runtime)
    if kwargs.get("agent_owner_inputs") is not None:
        validate_agent_owner_selection(kwargs.get("fingerprint_port"), kwargs["agent_owner_inputs"])
    supplied_validator = kwargs.get("agent_owner_validator")
    if supplied_validator is not None and supplied_validator is not validate_agent_owner_selection:
        raise AgentOwnerUnavailable("Agent owner validator override is unavailable")
    kwargs["agent_owner_validator"] = validate_agent_owner_selection
    kwargs.setdefault("migration_registrar", register_legacy_migrations)
    kwargs.setdefault("runtime_assembler", assemble_runtime_composition)
    kwargs.setdefault("database_factory", Database)
    composition = select_product_composition(**kwargs)
    composition.bind_host_application_ports(runtime_builder=build_runtime, core_method_factory=agent_core_methods)
    from ..engineering import select_engineering
    composition.bind_host_engineering_selection(select_engineering)
    composition.bind_host_environment_ports(environment_factory=create_product_unit_admission,
        owned_environment_factory=create_owned_product_unit_admission,
        secret_store_factory=secret_service.product_secret_store)
    composition.bind_host_execution_ports(migration_registrar=kwargs["migration_registrar"],
        runtime_assembler=kwargs["runtime_assembler"], database_factory=kwargs["database_factory"])
    composition.bind_harness_registry(capture_selected_harness_catalog().registry)
    composition.selected_pi_execution = selected_pi
    return composition


def bind_product_harness_effects(composition):
    composition.bind_host_application_ports(runtime_builder=build_runtime, core_method_factory=agent_core_methods)
    from ..engineering import select_engineering
    composition.bind_host_engineering_selection(select_engineering)
    composition.bind_host_environment_ports(environment_factory=create_product_unit_admission,
        owned_environment_factory=create_owned_product_unit_admission,
        secret_store_factory=secret_service.product_secret_store)
    return composition
