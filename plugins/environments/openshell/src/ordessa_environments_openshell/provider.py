"""SDK resource ownership without duplicating the OpenShell control plane.

Client and official same-authority stub are injected. SDK snapshot names are
never identity: every lookup resolves immutable ID via a complete SDK listing.
No high-level Sandbox context (delete_on_exit=True), auto-auth or Local fallback.
"""
import base64
import hashlib
import json
import time
import uuid
import grpc
from openshell._proto import datamodel_pb2, openshell_pb2 as pb
from openshell.sandbox import SandboxClient
from ordessa_environments import BackendNotFound, EnvironmentRefused, EnvironmentOperationUnknown

from .configuration import OpenShellConfiguration, create_spec
from .mapping import observation
from .execution import OpenShellExecution
from .files import OpenShellFileArea


class _Use:
    def __init__(self, provider, sandbox, generation):
        bound_runtime = observation(sandbox).runtime_identity
        def validate():
            fresh = provider._lookup(sandbox.id)
            if (fresh.name != sandbox.name or observation(fresh).state != 'running'
                    or bound_runtime is not None and observation(fresh).runtime_identity != bound_runtime):
                raise EnvironmentRefused('OpenShell use backend binding/runtime changed')
        self.files = OpenShellFileArea(provider._rpc, configuration=provider.configuration, sandbox_name=sandbox.name, validate=validate)
        files_verified = False
        if provider.configuration.file_helper is not None:
            self.files.probe()
            files_verified = True
        self.capabilities = observation(sandbox, files_verified=files_verified).capabilities
        self.execution = OpenShellExecution(provider._rpc, workspace=provider.configuration.workspace, sandbox_name=sandbox.name, validate=validate,generation=generation,file_root=provider.configuration.file_root)

    def release(self):
        # Individual streams/processes are creator-owned and managed by core
        # Use. Never close the shared SDK client or delete/stop the sandbox.
        return {'resourcePreserved':True}


class OpenShellEnvironmentProvider:
    operations = frozenset({'start','stop','delete'})
    #: The bounded native management actions. Every one of them is a read over
    #: the gateway's own control plane: this port never creates or deletes a
    #: sandbox and never proxies an arbitrary remote interface.
    native_actions = frozenset({'list','inspect','health'})

    def __init__(self, configuration: OpenShellConfiguration, *, client: SandboxClient, rpc):
        self.configuration, self._client, self._rpc = configuration, client, rpc
        self.identity = configuration.provider_id
        self.binding_id = json.dumps(['openshell', configuration.gateway_reference, configuration.workspace], separators=(',',':'))

    def _lookup(self, backend_id):
        self._verify_gateway()
        if not isinstance(backend_id,str) or not backend_id:
            raise EnvironmentRefused('immutable sandbox ID required')
        # Name can be reused. A successful full census is required to assert
        # absence, and failure is never treated as not found.
        refs = self._client.list_all(workspace=self.configuration.workspace)
        matches = [ref for ref in refs if ref.id == backend_id]
        if not matches:
            raise BackendNotFound('immutable OpenShell sandbox ID is absent')
        if len(matches) != 1 or matches[0].workspace != self.configuration.workspace:
            raise EnvironmentRefused('ambiguous sandbox identity or workspace binding')
        return matches[0]

    def _verify_gateway(self):
        try:
            health = self._client.health()
        except Exception:
            raise EnvironmentRefused('OpenShell gateway health cannot be verified') from None
        if health.version.removeprefix('v') != '0.1.3':
            raise EnvironmentRefused('OpenShell gateway version differs from verified SDK release')
        if health.status != pb.SERVICE_STATUS_HEALTHY:
            raise EnvironmentRefused('OpenShell gateway did not report healthy')

    def _creation_name(self, operation_id):
        if (not isinstance(operation_id, str) or len(operation_id) != 32
                or any(char not in '0123456789abcdef' for char in operation_id)
                or operation_id == '0' * 32):
            raise EnvironmentRefused('creation requires the full lowercase UUID operation ID')
        # v0.1.3 routable names allow 19 characters. The full operation ID
        # remains the request/label identity; this 80-bit digest is only an
        # alias. For 1M names birthday collision probability is ~4.2e-13,
        # never zero: census, gateway uniqueness and full-label verification
        # all fail closed. There is no collision retry or existing adoption.
        material = json.dumps(['ordessa.openshell.creation.v1', self.binding_id,
                               operation_id], separators=(',', ':')).encode()
        suffix = base64.b32encode(hashlib.sha256(material).digest()[:10]).decode().lower()
        return 'oe-' + suffix

    def _creation_matches(self, sandbox, name, operation_id):
        return (bool(sandbox.id) and sandbox.name == name
                and sandbox.workspace == self.configuration.workspace
                and sandbox.labels.get('ordessa.creation-operation') == operation_id)

    def create(self, reference, *, operation_id):
        spec = create_spec(reference)
        self._verify_gateway()
        name = self._creation_name(operation_id)
        try:
            refs = self._client.list_all(workspace=self.configuration.workspace)
        except Exception:
            raise EnvironmentRefused('creation name availability could not be verified') from None
        if any(ref.name == name for ref in refs):
            raise EnvironmentRefused('creation name is occupied; existing sandbox is not adopted')
        request = pb.CreateSandboxRequest(
            workspace_scope=datamodel_pb2.WorkspaceSelector(workspace=self.configuration.workspace),
            # v0.1.3 admission requires hyphenated UUID, not its hex spelling.
            # This retains every bit of the persisted operation identity.
            name=name, spec=spec, request_id=str(uuid.UUID(hex=operation_id)),
            labels={'ordessa.creation-operation':operation_id})
        try:
            response = self._rpc.CreateSandbox(request, timeout=self.configuration.timeout_seconds)
        except grpc.RpcError as error:
            status = error.code()
            category = status.name if isinstance(status, grpc.StatusCode) else 'UNKNOWN'
            # Only an enum is exposed; arbitrary details may carry credentials.
            raise EnvironmentOperationUnknown('OpenShell create receipt unavailable (' + category + '); do not retry',identity=name) from None
        except Exception:
            raise EnvironmentOperationUnknown('OpenShell create receipt unavailable (UNKNOWN); do not retry',identity=name) from None
        backend_id = response.sandbox.metadata.id
        if not backend_id:
            raise EnvironmentOperationUnknown('OpenShell create returned no immutable ID',identity=name)
        meta = response.sandbox.metadata
        if (meta.name != name or meta.workspace != self.configuration.workspace
                or meta.labels.get('ordessa.creation-operation') != operation_id):
            # An uncorrelated ID is never persisted as this operation's mapping.
            raise EnvironmentOperationUnknown('OpenShell create receipt correlation differs',identity=name)
        try:
            sandbox = self._lookup(backend_id)
        except Exception:
            raise EnvironmentOperationUnknown('created sandbox requires inspection',identity=name,backend_id=backend_id) from None
        if not self._creation_matches(sandbox, name, operation_id):
            raise EnvironmentOperationUnknown('created sandbox correlation changed',identity=name)
        return observation(sandbox)

    def inspect(self, backend_id):
        return observation(self._lookup(backend_id))

    def recover_creation(self, operation_id):
        self._verify_gateway()
        name = self._creation_name(operation_id)
        refs=self._client.list_all(workspace=self.configuration.workspace)
        matches=[ref for ref in refs if ref.name == name]
        if len(matches)!=1 or not self._creation_matches(matches[0], name, operation_id):
            raise EnvironmentRefused('uncertain creation has no unique backend correlation evidence')
        sandbox = self._lookup(matches[0].id)
        if not self._creation_matches(sandbox, name, operation_id):
            raise EnvironmentRefused('creation correlation changed during recovery')
        return observation(sandbox)

    def open_use(self, backend_id, *, use_id, generation):
        sandbox = self._lookup(backend_id)
        if observation(sandbox).state != 'running':
            raise EnvironmentRefused('sandbox is not observed READY')
        return _Use(self, sandbox,generation)

    def _lifecycle(self, backend_id, operation):
        sandbox = self._lookup(backend_id)
        try:
            result = getattr(self._client,operation)(sandbox.name,workspace=self.configuration.workspace)
        except Exception:
            raise EnvironmentOperationUnknown('OpenShell lifecycle result unavailable',identity=backend_id,backend_id=backend_id) from None
        if result.id != backend_id:
            raise EnvironmentOperationUnknown('sandbox name changed identity during lifecycle',identity=backend_id,backend_id=backend_id)
        return observation(result)

    def start(self, backend_id):
        return self._lifecycle(backend_id,'start')

    def stop(self, backend_id):
        return self._lifecycle(backend_id,'stop')

    def delete(self, backend_id):
        sandbox = self._lookup(backend_id)
        try:
            result = self._client.delete(sandbox.name,workspace=self.configuration.workspace,allow_missing=False)
        except Exception:
            raise EnvironmentOperationUnknown('delete receipt unavailable; do not retry',identity=backend_id,backend_id=backend_id) from None
        if result.sandbox_id not in (None, backend_id):
            raise EnvironmentOperationUnknown('delete addressed a changed backend ID',identity=backend_id,backend_id=backend_id)
        # v0.1.3 deletion is asynchronous: an ACCEPTED receipt is a request, not
        # an absence. Only an observed absence confirms the deletion, so poll
        # the same complete-census lookup the rest of this provider trusts. A
        # bound that expires stays UNKNOWN; it never claims a completed delete.
        deadline = time.monotonic() + self.configuration.timeout_seconds
        while True:
            try:
                self._lookup(backend_id)
            except BackendNotFound:
                return
            except Exception:
                raise EnvironmentOperationUnknown('deletion absence is unverifiable',identity=backend_id,backend_id=backend_id) from None
            if time.monotonic() >= deadline:
                raise EnvironmentOperationUnknown('deletion absence was not confirmed within the bound',identity=backend_id,backend_id=backend_id)
            time.sleep(0.2)

    # -- the thin native management port -------------------------------------
    #
    # These are the provider's own official SDK calls behind a closed action
    # set. The neutral layer never names a gateway, an RPC or a protobuf
    # message; the mapping stays here, in the plugin that owns the SDK.

    def native_describe(self):
        """Availability plus this gateway/workspace binding's own facts."""
        facts = {'schemaVersion': 'environment-native-management/1',
                 'provider': self.identity, 'available': False, 'reason': None,
                 'gateway': self.configuration.gateway_reference,
                 'workspace': self.configuration.workspace,
                 'endpointKind': 'openshell-sandbox',
                 'binding': self.binding_id,
                 'gatewayVersion': None,
                 'actions': sorted(self.native_actions)}
        try:
            health = self._client.health()
        except Exception:
            facts['reason'] = 'OpenShell gateway health cannot be verified'
            return facts
        version = health.version.removeprefix('v')
        facts['gatewayVersion'] = version
        if version != '0.1.3':
            facts['reason'] = 'OpenShell gateway version differs from verified SDK release'
            return facts
        if health.status != pb.SERVICE_STATUS_HEALTHY:
            facts['reason'] = 'OpenShell gateway did not report healthy'
            return facts
        facts['available'] = True
        return facts

    def native_request(self, action, *, target=None, request_id=None):
        """One bounded read over the gateway's own control plane.

        The action set is closed. An action outside it is refused, and no
        sandbox is ever created or deleted from this port.
        """
        if action not in self.native_actions:
            raise EnvironmentRefused('OpenShell native management action is not supported')
        if action == 'list':
            return {'action': 'list',
                    'items': [self._neutral_sandbox(ref) for ref in self._native_list(request_id)]}
        if action == 'inspect':
            if not isinstance(target, str) or not target:
                raise EnvironmentRefused('OpenShell native inspect requires an immutable sandbox ID')
            try:
                sandbox = self._lookup(target)
            except BackendNotFound:
                # An absent sandbox is a fact about the gateway, not a failure
                # of this port.
                return {'action': 'inspect', 'present': False, 'backendId': target}
            return {'action': 'inspect', 'present': True, **self._neutral_sandbox(sandbox)}
        return {'action': 'health', **self._native_health(request_id)}

    def _native_list(self, request_id):
        try:
            return self._client.list_all(workspace=self.configuration.workspace)
        except grpc.RpcError as error:
            status = error.code()
            category = status.name if isinstance(status, grpc.StatusCode) else 'UNKNOWN'
            raise EnvironmentOperationUnknown(
                'OpenShell sandbox listing outcome is unavailable (' + category + '); do not retry',
                identity=request_id) from None
        except Exception:
            raise EnvironmentOperationUnknown(
                'OpenShell sandbox listing outcome is unavailable (UNKNOWN); do not retry',
                identity=request_id) from None

    def _native_health(self, request_id):
        try:
            health = self._client.health()
        except grpc.RpcError as error:
            status = error.code()
            category = status.name if isinstance(status, grpc.StatusCode) else 'UNKNOWN'
            raise EnvironmentOperationUnknown(
                'OpenShell gateway health outcome is unavailable (' + category + '); do not retry',
                identity=request_id) from None
        except Exception:
            raise EnvironmentOperationUnknown(
                'OpenShell gateway health outcome is unavailable (UNKNOWN); do not retry',
                identity=request_id) from None
        return {'gatewayVersion': health.version.removeprefix('v'),
                'status': 'healthy' if health.status == pb.SERVICE_STATUS_HEALTHY else 'not-healthy'}

    def _neutral_sandbox(self, sandbox):
        """The neutral fact of one sandbox: identity, name, workspace and state."""
        return {'backendId': sandbox.id, 'name': sandbox.name, 'workspace': sandbox.workspace,
                'state': observation(sandbox).state}
