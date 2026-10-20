"""Host composition of the selected product Environment, store and owner lifecycle.

The explicit selection inputs carry no additional store, issuer or registry.
"""
from __future__ import annotations
from ordessa_units.public import (
    AgentOwnerUnavailable, validate_agent_owner_selection,
)

def create_owned_product_unit_admission(store_path, root_ownership_port, *,
                                     fingerprint_port, agent_owner_inputs, native_channels_selected,
                                     fingerprint_factory=None):
    if agent_owner_inputs is not None and fingerprint_factory is None:
        validate_agent_owner_selection(fingerprint_port, agent_owner_inputs)
    from .agent_owner import _expected_binding, preflight_fresh_journal
    binding = _expected_binding(store_path, root_ownership_port)
    if agent_owner_inputs is not None:
        preflight_fresh_journal(store_path, binding, root_port=root_ownership_port)
    def current_owner():
        try:
            root_ownership_port.validate_owned_root(binding, root_path=binding.root_path,
                                 store_path=store_path,
                                 child_path=binding.child_path)
            return True
        except Exception:
            return False
    return create_product_unit_admission(store_path, fingerprint_port=fingerprint_port,
                                      agent_owner_inputs=agent_owner_inputs,
                                      native_channels_selected=native_channels_selected,
                                      fingerprint_factory=fingerprint_factory,
                                      _exclusive_owner=current_owner,
                                    _root_ownership=binding, _root_ownership_port=root_ownership_port)


def create_product_unit_admission(store_path, *, fingerprint_port, agent_owner_inputs,
                               native_channels_selected, _exclusive_owner=None,
                         _root_ownership=None, _root_ownership_port=None,
                         fingerprint_factory=None):
    """Use the original store and explicitly selected protected fingerprint.

    The configured-key reader receives this same store before admission exists.
    Historical tables keep their identifiers and are not execution fallbacks.
    """
    if fingerprint_factory is not None and (
            not callable(fingerprint_factory) or fingerprint_port is not None):
        raise AgentOwnerUnavailable('request-integrity source conflicts with an explicit fingerprint')
    if agent_owner_inputs is not None and fingerprint_factory is None:
        validate_agent_owner_selection(fingerprint_port, agent_owner_inputs)
    from pathlib import Path
    if agent_owner_inputs is not None:
        from .agent_owner import preflight_fresh_journal
        if not callable(getattr(_root_ownership_port, "validate_owned_root", None)):
            raise AgentOwnerUnavailable("Agent owner requires the host root ownership proof")
        expected_root = Path(store_path).parent.parent
        expected_child = expected_root / "state" / "agent-owner" / "operations.sqlite"
        try:
            _root_ownership_port.validate_owned_root(_root_ownership, root_path=expected_root,
                                         store_path=store_path,
                                         child_path=expected_child)
        except Exception as exc:
            raise AgentOwnerUnavailable("Agent owner root proof is invalid") from exc
        preflight_fresh_journal(store_path, _root_ownership, root_port=_root_ownership_port)

    from uuid import uuid4
    from ordessa_units.persistence.sqlite import SqliteUnitStore
    from ordessa_units.admission.context import UnitAdmissionContext
    from ordessa_units.admission.generation import seed_fresh_environment
    from .unit_admission import create_unit_admission, close_unit_admission

    # Existing C1 effect tombstones cannot be reinterpreted as absent
    # Environment requests. Refuse before writing any new schema; the
    # sealed historical source remains available to an explicit recovery.
    legacy_path = Path(store_path)
    if legacy_path.exists():
        import sqlite3
        from contextlib import closing
        from ordessa_units.errors import UnitGuaranteeUnavailable
        with closing(sqlite3.connect(legacy_path.resolve().as_uri() + '?mode=ro', uri=True)) as legacy:
            tables = {row[0] for row in legacy.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for name in ('core_execution', 'core_operation'):
                if name in tables and legacy.execute('SELECT 1 FROM ' + name + ' LIMIT 1').fetchone():
                    raise UnitGuaranteeUnavailable(
                        'sealed legacy Core effect records require explicit reconciliation; '
                        'their request tombstones cannot be compared as new Environment requests')

    # The host holds the OS process lock before constructing this store.
    # Acquiring it proves the previous product process released ownership;
    # a stale SQL marker alone never authorizes dispatch or a takeover.
    verified_owner = _exclusive_owner is not None and _exclusive_owner() is True
    # A crashed predecessor has no held OS lock. A failed live construction
    # retains the original lock, preventing this new owner from acquiring it.
    # The Store takes over only the exact SQL marker it observed in one CAS.
    store = SqliteUnitStore(store_path, allow_takeover=verified_owner)
    environment = None
    try:
        if fingerprint_factory is not None:
            fingerprint_port = fingerprint_factory(store)
            if fingerprint_port is None:
                raise AgentOwnerUnavailable('configured request-integrity source is unavailable')
            if agent_owner_inputs is not None:
                validate_agent_owner_selection(fingerprint_port, agent_owner_inputs)
        with store.transaction() as connection:
            row = connection.execute("SELECT value FROM env_meta WHERE key='environment_id'").fetchone()
            identity = row[0] if row else 'environment-' + uuid4().hex
            if row is None:
                connection.execute("INSERT INTO env_meta VALUES('environment_id', ?)", (identity,))
                seed_fresh_environment(connection, identity)

        class ProductUnitAdmission(UnitAdmissionContext):
            @property
            def store_port(self):
                return store

            def close(self):
                if getattr(self, "_agent_owner_closing", False):
                    from ordessa_units.errors import UnitGuaranteeUnavailable
                    raise UnitGuaranteeUnavailable("Environment close is already in progress")
                self._agent_owner_closing = True
                try:
                    self.drain()
                    if any(self.pending().values()):
                        from ordessa_units.errors import UnitGuaranteeUnavailable
                        raise UnitGuaranteeUnavailable('Unit pending records retain the original writer and root owner')
                    if not self._closed:
                        owner = getattr(self, "agent_owner", None)
                        if owner is not None:
                            owner.revoke()
                    # Environment.close retries pending observation detaches
                    # even after its admission bit became closed.
                    close_unit_admission(self)
                    store.close()
                finally:
                    self._agent_owner_closing = False

        class LocalProductPolicy:
            # The product is one authenticated local-user realm. Transport
            # authenticates before entering its business method registry.
            def admit_invoke(self, principal, surface, guarantee):
                return principal == 'local' and guarantee == 'reliable' and surface in {
                        'pacthold.agents.profiles.create',
                        'pacthold.agents.profiles.clone',
                        'pacthold.agents.profiles.edit',
                        'pacthold.agents.profiles.rename',
                        'pacthold.agents.profiles.archive',
                        'pacthold.agents.profiles.restore',
                        'pacthold.agents.configuration.apply',
                        'pacthold.agents.nodes.prepare',
                        'pacthold.agents.nodes.stop',
                        'pacthold.agents.nodes.release',
                        'pacthold.agents.nodes.recover',
                    } or (
                        principal == 'local' and guarantee == 'raw'
                        and self_native_channels
                        and surface in ('native.channel-start', 'native.channel-write', 'native.channel-release')
                    )
            def admit_object_access(self, principal, object_ref, mode):
                return principal == 'local'

        self_native_channels = native_channels_selected
        environment = create_unit_admission(identity, store=store,
            policy=LocalProductPolicy(), fingerprint_port=fingerprint_port,
            context_type=ProductUnitAdmission)
        environment.agent_owner = None
        environment.owner_ports = None
        environment.store_path = Path(store_path)
        environment.agent_journal_path = Path(store_path).parent / "agent-owner" / "operations.sqlite"
        if agent_owner_inputs is not None:
            from .agent_owner import assemble_agent_owner
            owner = assemble_agent_owner(environment, agent_owner_inputs,
                                         _root_ownership, root_port=_root_ownership_port)
            environment.agent_owner = owner
            environment.owner_ports = owner.ports
        return environment
    except BaseException as construction_failure:
        try:
            if environment is not None:
                environment.close()
            else:
                store.close()
        except BaseException as close_failure:
            # The factory never returned this Environment to CoreBinding.
            # Retain the exact object so Host retry can finish its original
            # revoke/detach obligations before Store and OS owner release.
            if environment is not None:
                construction_failure.pending_environment_close = environment
            construction_failure.pending_store_close = store
            existing = getattr(construction_failure, "cleanup_errors", ())
            construction_failure.cleanup_errors = tuple(existing) + (close_failure,)
        raise
