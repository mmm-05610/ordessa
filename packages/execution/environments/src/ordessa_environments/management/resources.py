"""Scoped EnvironmentManager and stable resource facade."""
import uuid

from ..definitions.errors import BackendNotFound, EnvironmentOperationUnknown, EnvironmentRefused
from ..definitions.models import EnvironmentOperationReceipt
from .store import encode_observation, decode_observation
from .usages import EnvironmentUse


class EnvironmentManager:
    def __init__(self, *, store, providers):
        self.store = store
        self.providers = dict(providers)
        for key, provider in self.providers.items():
            if not isinstance(key, str) or not key or provider.identity != key:
                raise EnvironmentRefused('provider registry binding differs from its identity')
            self.store.bind_provider(key,provider.binding_id)

    def _provider(self, identity):
        try:
            return self.providers[identity]
        except KeyError:
            raise EnvironmentRefused('environment provider is not bound') from None

    def create(self, provider_id, reference):
        provider = self._provider(provider_id)
        identity, operation_id = 'environment/' + uuid.uuid4().hex, uuid.uuid4().hex
        # Durable intent precedes any remote effect. A failed initial commit
        # does not dispatch create. Never persist configuration/credentials.
        self.store.insert(identity, provider_id, operation_id=operation_id)
        observation = None
        try:
            try:
                observation = provider.create(reference, operation_id=operation_id)
            except EnvironmentRefused:
                # Provider refusals are pre-dispatch only. Once dispatched,
                # uncertain providers must raise EnvironmentOperationUnknown.
                self.store.refuse_creation(identity,operation_id)
                raise
            self.store.confirm(identity, observation, expected_operation_id=operation_id)
        except Exception as error:
            if isinstance(error,EnvironmentRefused) and observation is None:
                raise
            backend_id = observation.backend_id if observation is not None else getattr(error, 'backend_id', None)
            try:
                self.store.unknown(identity, operation_id=operation_id, backend_id=backend_id)
            except Exception:
                # Original durable creating row stays fenced even if the store
                # is unavailable. Caller receives immutable mapping evidence.
                pass
            raise EnvironmentOperationUnknown('create outcome requires explicit inspection',
                identity=identity, backend_id=backend_id) from error
        return EnvironmentInstance(self, identity)

    def register(self, provider_id, backend_id):
        provider = self._provider(provider_id)
        observation = provider.inspect(backend_id)
        if observation.backend_id != backend_id:
            raise EnvironmentRefused('registration resolved a different immutable backend ID')
        identity = 'environment/' + uuid.uuid4().hex
        self.store.insert(identity, provider_id, observation=observation)
        return EnvironmentInstance(self, identity)

    def reconcile_creation(self, identity, backend_id=None):
        """Explicitly bind the evidence from an uncertain create; never create again."""
        snapshot = self.store.snapshot(identity)
        if snapshot.operation != 'create' or snapshot.phase not in ('creating', 'unknown'):
            raise EnvironmentRefused('resource has no uncertain creation')
        if snapshot.backend_id is not None and backend_id not in (None, snapshot.backend_id):
            raise EnvironmentRefused('immutable backend identity changed')
        with self.store.transaction() as connection:
            operation_id = self.store.resource(connection, identity)['operation_id']
        provider = self._provider(snapshot.provider_id)
        if snapshot.backend_id is None:
            observation = provider.recover_creation(operation_id)
            if backend_id is not None and observation.backend_id != backend_id:
                raise EnvironmentRefused('creation correlation differs from supplied immutable ID')
        else:
            observation = provider.inspect(snapshot.backend_id)
        if snapshot.backend_id is not None and observation.backend_id != snapshot.backend_id:
            raise EnvironmentRefused('creation evidence resolved a different backend ID')
        self.store.confirm(identity, observation, expected_operation_id=operation_id)
        return self.get(identity)

    def get(self, identity):
        self.store.snapshot(identity)
        return EnvironmentInstance(self, identity)

    def list(self):
        return tuple(self.store.snapshot(identity) for identity in self.store.identities())


class EnvironmentInstance:
    def __init__(self, manager, identity):
        self._manager, self._identity = manager, identity

    @property
    def identity(self):
        return self._identity

    @property
    def snapshot(self):
        return self._manager.store.snapshot(self.identity)

    def inspect(self):
        store = self._manager.store
        snapshot = self.snapshot
        if snapshot.backend_id is None or snapshot.phase == 'deleted':
            return snapshot
        provider = self._manager._provider(snapshot.provider_id)
        try:
            observation = provider.inspect(snapshot.backend_id)
        except BackendNotFound:
            if snapshot.phase == 'unknown' and snapshot.operation == 'delete':
                with store.transaction() as connection:
                    operation_id = store.resource(connection, self.identity)['operation_id']
                store.confirm_deleted(self.identity, operation_id)
                return self.snapshot
            raise
        if observation.backend_id != snapshot.backend_id:
            raise EnvironmentRefused('provider observation changed immutable backend ID')
        with store.transaction() as connection:
            row = store.resource(connection, self.identity)
            # An observation must never silently remove an in-flight fence.
            if row['generation'] != snapshot.generation:
                raise EnvironmentRefused('observation raced a resource generation change')
            if row['phase'] == 'ready':
                previous = decode_observation(row['observation'])
                if (previous is not None and
                        (previous.runtime_identity is not None and previous.runtime_identity != observation.runtime_identity
                         or previous.state == 'running' and observation.state != 'running')):
                    connection.execute('UPDATE environment_resources SET generation=generation+1 WHERE identity=?', (self.identity,))
                    connection.execute("UPDATE environment_uses SET phase='invalid' WHERE environment_id=? AND phase IN ('active','unknown')", (self.identity,))
                connection.execute('UPDATE environment_resources SET observation=? WHERE identity=?',
                    (encode_observation(observation), self.identity))
            elif row['phase'] == 'unknown' and row['operation'] in ('start', 'stop'):
                target = {'start':'running', 'stop':'stopped'}[row['operation']]
                if observation.state == target:
                    connection.execute("UPDATE environment_resources SET phase='ready', observation=?, operation=NULL, operation_id=NULL WHERE identity=?",
                        (encode_observation(observation), self.identity))
        return self.snapshot

    def acquire(self, owner_id, *, sharing):
        self.inspect()
        store = self._manager.store
        use_id = 'environment-use/' + uuid.uuid4().hex
        backend_id, generation = store.reserve_use(self.identity, use_id, owner_id, sharing=sharing)
        snapshot = self.snapshot
        provider = self._manager._provider(snapshot.provider_id)
        # Admission and backend view acquisition are an in-flight use effect.
        # Resource lifecycle cannot pass this window.
        store.begin_use_effect(use_id)
        try:
            backend_use = provider.open_use(backend_id, use_id=use_id, generation=generation)
        except EnvironmentOperationUnknown as error:
            store.end_use_effect(use_id,unknown=True)
            raise EnvironmentOperationUnknown('backend use acquisition outcome unknown; recorded use remains held',
                identity=self.identity,backend_id=backend_id) from error
        except Exception:
            store.end_use_effect(use_id)
            store.release_use(use_id)
            raise
        store.end_use_effect(use_id)
        return EnvironmentUse(store, self.identity, use_id, generation, backend_use,
            getattr(backend_use, 'capabilities', snapshot.observation.capabilities))

    def _operate(self, operation, *, allow_in_use=False):
        store = self._manager.store
        snapshot = self.snapshot
        provider = self._manager._provider(snapshot.provider_id)
        if operation not in provider.operations:
            raise EnvironmentRefused('provider does not support this resource operation')
        operation_id = uuid.uuid4().hex
        backend_id, generation = store.begin_operation(self.identity, operation, operation_id, allow_in_use=allow_in_use)
        try:
            if operation == 'delete':
                provider.delete(backend_id)
                store.confirm_deleted(self.identity, operation_id)
            else:
                observation = getattr(provider, operation)(backend_id)
                if observation.state != {'start':'running', 'stop':'stopped'}[operation]:
                    raise EnvironmentRefused('backend lifecycle did not confirm requested state')
                store.confirm(self.identity, observation, expected_operation_id=operation_id)
        except Exception as error:
            try:
                store.unknown(self.identity, operation_id=operation_id)
            except Exception:
                pass
            raise EnvironmentOperationUnknown(operation + ' outcome requires inspection; no automatic retry',
                identity=self.identity, backend_id=backend_id) from error
        return EnvironmentOperationReceipt(self.identity, operation, generation, True)

    def start(self, *, allow_in_use=False):
        return self._operate('start', allow_in_use=allow_in_use)

    def stop(self, *, allow_in_use=False):
        return self._operate('stop', allow_in_use=allow_in_use)

    def delete(self):
        return self._operate('delete')
