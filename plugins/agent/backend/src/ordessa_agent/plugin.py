"""Agent domain plugin (T010-01): the A1 owners exposed as wire projections.

The wire methods below are projections of the ONE owner set per target.
Business validation and native application stay where A1 puts them; this
plugin never becomes a second writer. The provided port `agent.owners@1`
hands the owner registry to the 010-12 consumer migration.
"""
from __future__ import annotations

from typing import Any, Mapping

from server_plugin_api import (
    ServerMethodDescriptor,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
    WireError,
)

from .owners import AgentOwnerRegistry, AuthorityConflictError, UnknownOutcome, wire_value

PLUGIN_ID = "ordessa.agent"
PLUGIN_DISPLAY_NAME = "Agent domain owners (A1)"
PLUGIN_VERSION = "1"


class AgentDomainPlugin:
    def __init__(self, registry: AgentOwnerRegistry | None = None, *, target_resolver=None,
                 submission_port=None, submission_service_factory=None,
                 session_resolver=None, config_preparer=None, submission_capabilities=None) -> None:
        self._registry = registry
        self._target_resolver = target_resolver
        self._submission_port = submission_port
        self._submission_service_factory = submission_service_factory
        self._submission_service = None
        self._session_resolver = session_resolver
        self._config_preparer = config_preparer
        self._submission_capabilities = submission_capabilities
        self._repository = None

    def close(self):
        if self._submission_service is not None:
            close_service = getattr(self._submission_service, "close", None)
            if callable(close_service):
                close_service()
            self._submission_service = None
        if self._repository is not None:
            self._repository.close()
            self._repository = None

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            id=PLUGIN_ID, display_name=PLUGIN_DISPLAY_NAME, version=PLUGIN_VERSION,
            requires=(),
        )

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        production = hasattr(context, 'data_root')
        if self._registry is None:
            if production:
                from .config_repository import ConfigRepository
                from pathlib import Path
                self._repository = ConfigRepository(Path(context.data_root) / 'plugins/agent/config.sqlite')
            self._registry = AgentOwnerRegistry(self._repository)

        def ensure_target(params: Mapping[str, Any]) -> str:
            target = params.get("target")
            if not isinstance(target, str) or not target:
                raise WireError("INVALID_REQUEST", "target is required")
            if production:
                draft = self._repository is not None and self._repository.knows_draft(target)
                if not draft and (self._target_resolver is None or self._target_resolver(target) != target):
                    raise WireError('FORBIDDEN', 'Agent target has no verified binding', {'internalCode':'AUTHORIZATION_REFUSED'})
            with self._registry.lock:
                owners = self._registry.owners_of(target)
                if owners is None:
                    binding = context.ports.get('core.binding') if production else None
                    if binding is not None:
                        from ordessa_environment_api.targets import CanonicalFactTarget, AuthorityKey, AuthorityRegistration
                        environment = binding.environment
                        # A backend-issued target, never a window/schema alias,
                        # is the one fact identity registered with the kernel.
                        registration = AuthorityRegistration(
                            key=AuthorityKey('agent.configuration', CanonicalFactTarget('local', 'ordessa.agent', target)),
                            declaring_owner_domain=PLUGIN_ID, target_schema_id='agent-target', schema_major=1)
                        environment.register_authority(registration, environment.agent_activation)
                    owners = self._registry.register(target)
            return target

        def session_resolve(params):
            location = params.get('location')
            if not isinstance(location, Mapping):
                raise WireError('INVALID_REQUEST', 'location must map')
            if location.get('kind') == 'draft' and self._repository is not None:
                if not isinstance(location.get('draftId'), str) or not location['draftId']:
                    raise WireError('INVALID_REQUEST', 'draftId required')
                result = self._repository.resolve_draft(location)
                return observation_capability(result)
            if self._session_resolver is None:
                raise WireError('CAPABILITY_UNSUPPORTED', 'native session binding unavailable')
            return observation_capability(self._session_resolver(location, params.get('nativeOwner')))

        def observation_capability(result):
            binding = context.ports.get('core.binding') if production else None
            if binding is None:
                return result
            environment = binding.environment
            declared = self._submission_capabilities(result['target']) if self._submission_capabilities else {}
            return {**result, 'submission': {
                'namespace': environment.environment_id, 'principalScope': 'local',
                'schema': 'agent-input/v1', 'available': declared.get('available') is True,
                'nativeBound': declared.get('nativeBound') is True,
                'mode': declared.get('mode') or ('createWithConfig' if self._repository is not None
                    and self._repository.knows_draft(result['target']) else 'existing'),
            }, 'observation': {'method': 'agent.config.observe',
                'releaseMethod': 'agent.config.release', 'environment': environment.environment_id,
                'creditLimit': 32}}

        def config_prepare(params):
            target = ensure_target(params)
            if self._config_preparer is None:
                raise WireError('CAPABILITY_UNSUPPORTED', 'conditional native config preparation unavailable')
            return self._config_preparer(target, params)

        def observation_binding(params):
            from ordessa_environment_api.targets import CanonicalFactTarget
            target = ensure_target(params)
            resolved = session_resolve({'location': params.get('location'), 'nativeOwner': params.get('nativeOwner')})
            if resolved.get('target') != target or str(resolved.get('generation')) != str(params.get('generation')):
                raise WireError('CONFLICT_VERSION', 'configuration observation binding/generation changed')
            binding = context.ports.get('core.binding') if production else None
            if binding is None:
                raise WireError('CAPABILITY_UNSUPPORTED', 'managed Environment observation unavailable')
            environment = binding.environment
            return environment, CanonicalFactTarget('local', 'ordessa.agent', target), target

        def config_observe(params):
            from ordessa_environment_api import SubscriptionRef
            from .config_observation import ConfigObservationSource, envelope_wire
            environment, fact_target, target = observation_binding(params)
            credits = params.get('credits')
            if type(credits) is not int or credits < 0 or credits > 32:
                raise WireError('INVALID_REQUEST', 'observation credits must be an integer from 0 to 32')
            cursor = params.get('cursor')
            if cursor is not None and not isinstance(cursor, str):
                raise WireError('INVALID_REQUEST', 'observation cursor must be a string or null')
            identity = params.get('subscriptionId')
            if identity is None:
                source = ConfigObservationSource(self._registry.owners_of(target)['config'])
                handle = environment.read_and_subscribe(
                    environment.bind('agent.configuration-observation'), fact_target,
                    cursor, credits, source=source, principal='local')
                ref = handle.ref
            elif isinstance(identity, str) and identity:
                ref = SubscriptionRef(environment.environment_id, identity)
            else:
                raise WireError('INVALID_REQUEST', 'invalid subscription identity')
            return envelope_wire(environment.observe(ref, cursor, credits, 1000,
                principal='local', target=fact_target))

        def config_release(params):
            from ordessa_environment_api import SubscriptionRef
            from ordessa_environment_api.targets import CanonicalFactTarget
            # Release owns the captured subscription, even after its native
            # generation changes. The Environment checks principal and target.
            target = params.get('target')
            if not isinstance(target, str) or not target:
                raise WireError('INVALID_REQUEST', 'target is required')
            binding = context.ports.get('core.binding') if production else None
            if binding is None:
                raise WireError('CAPABILITY_UNSUPPORTED', 'managed Environment observation unavailable')
            environment = binding.environment
            fact_target = CanonicalFactTarget('local', 'ordessa.agent', target)
            identity = params.get('subscriptionId')
            if not isinstance(identity, str) or not identity:
                raise WireError('INVALID_REQUEST', 'subscription identity required')
            environment.unsubscribe(SubscriptionRef(environment.environment_id, identity),
                principal='local', target=fact_target)
            return {'released': True}

        def config_read(params: Mapping[str, Any]) -> dict[str, Any]:
            target = ensure_target(params)
            snapshot, operations = self._registry.owners_of(target)["config"].capture_configuration()
            return {
                "ownerRef": snapshot.owner_ref,
                "revision": snapshot.revision,
                "observedEvidence": snapshot.observed_evidence,
                "fields": dict(snapshot.fields),
                "resolved": wire_value(snapshot.resolved),
                "operations": [{"operationId": op.operation_id, "patchKinds": list(op.patch_kinds),
                    "sourceRef": op.source_ref, "submittedAtOrder": op.submitted_at_order,
                    "state": op.state} for op in operations],
            }

        def config_submit_operation(params: Mapping[str, Any]) -> dict[str, Any]:
            target = ensure_target(params)
            patch = params.get("patch", {})
            unset = params.get("unset", [])
            if not isinstance(patch, Mapping) or not isinstance(unset, list):
                raise WireError("INVALID_REQUEST", "patch must map and unset must list")
            config_owner = self._registry.owners_of(target)["config"]
            binding = context.ports.get('core.binding') if production else None
            def apply_intent():
                return config_owner.submit_operation(patch, str(params.get('sourceRef', 'wire')),
                                                    unset=tuple(str(u) for u in unset))
            if binding is None:
                summary = apply_intent() # explicit isolated owner fixture
            else:
                import hashlib, json
                from uuid import uuid4
                from ordessa_environment_api import RequestKey
                environment = binding.environment
                captured = json.dumps({'target':target, 'patch':dict(patch), 'unset':unset},
                                      sort_keys=True, allow_nan=False)
                summaries = []
                environment.invoke('agent.configuration-intent', RequestKey(
                    environment_namespace=environment.environment_id, principal_scope='local',
                    request_id='intent-' + uuid4().hex),
                    input_digest=hashlib.sha256(captured.encode()).hexdigest(),
                    handler=lambda: summaries.append(apply_intent()))
                summary = summaries[0]
            return {
                "operationId": summary.operation_id,
                "patchKinds": list(summary.patch_kinds),
                "state": summary.state,
            }

        def submission_service():
            if self._submission_service is not None:
                return self._submission_service
            if self._submission_service_factory is None:
                raise WireError('CAPABILITY_UNSUPPORTED', 'Agent reliable submission service is unavailable')
            binding = context.ports.get('core.binding')
            environment = getattr(binding, 'environment', None)
            if environment is None:
                raise WireError('CAPABILITY_UNSUPPORTED', 'composed Environment is unavailable')
            try:
                service = self._submission_service_factory(context, self._registry)
            except Exception as error:
                raise WireError('CAPABILITY_UNSUPPORTED',
                                f'Agent reliable submission service could not be composed: {error}') from error
            if not callable(getattr(service, 'submit', None)) or not callable(
                getattr(service, 'query', None)
            ):
                raise WireError('CAPABILITY_UNSUPPORTED', 'submission service has no submit/query contract')
            if getattr(service, 'environment', environment) is not environment:
                raise WireError('CAPABILITY_UNSUPPORTED',
                                'submission service is not bound to the composed Environment')
            self._submission_service = service
            return service

        def submit_input(params: Mapping[str, Any]) -> dict[str, Any]:
            target = ensure_target(params)
            capture = params.get("capture", {})
            if not isinstance(capture, Mapping):
                raise WireError("INVALID_REQUEST", "capture must map")
            if production:
                service = submission_service()
                required = {'submissionId', 'draft', 'configOperationIds', 'schema', 'mode'}
                if not required.issubset(capture):
                    raise WireError('INVALID_REQUEST', 'capture requires submissionId, draft, configOperationIds, schema, and mode')
                if set(capture) - required - {'expectedConditions'}:
                    raise WireError('INVALID_REQUEST', 'capture contains undeclared fields')
                if 'outcome' in capture or 'accepted' in capture:
                    raise WireError('INVALID_REQUEST', 'caller outcome claims are not submission evidence')
                from .submission_service import SubmissionInput
                draft = capture.get('draft')
                if not isinstance(draft, Mapping):
                    raise WireError('INVALID_REQUEST', 'capture draft must map')
                operation_ids = capture.get('configOperationIds')
                if not isinstance(operation_ids, (tuple, list)):
                    raise WireError('INVALID_REQUEST', 'configOperationIds must be a list')
                if 'draftRevision' in params and params['draftRevision'] != draft.get('draftRevision'):
                    raise WireError('INVALID_REQUEST', 'draftRevision differs from captured draft')
                item = SubmissionInput(
                    submission_id=capture['submissionId'],
                    principal_scope='local',
                    target=target,
                    mode=capture['mode'],
                    draft=draft,
                    config_operation_ids=tuple(operation_ids),
                    schema=capture['schema'],
                    expected_conditions=capture.get('expectedConditions'),
                )
                try:
                    result = service.submit(item)
                except Exception as error:
                    from .submission_journal import JournalConflictError, ReliableSubmissionUnsupported
                    from ordessa_environment_api import AdmissionRefusedError, GuaranteeUnavailableError
                    if isinstance(error, JournalConflictError):
                        raise WireError('CONFLICT_REQUEST', str(error)) from error
                    if isinstance(error, ReliableSubmissionUnsupported):
                        raise WireError('CAPABILITY_UNSUPPORTED', str(error)) from error
                    if isinstance(error, GuaranteeUnavailableError):
                        raise WireError('CAPABILITY_UNSUPPORTED', str(error)) from error
                    if isinstance(error, AdmissionRefusedError):
                        raise WireError('FORBIDDEN', str(error), {'internalCode':'AUTHORIZATION_REFUSED'}) from error
                    raise
                return _submission_wire(result)
            # A context without a data root is an isolated unit fixture only.
            submission = self._registry.owners_of(target)["submission"]
            receipt = submission.submit(int(params.get("draftRevision", 0)), capture)
            if receipt.outcome == "unknown":
                # unknown keeps its request association; the wire answer says
                # so and NEVER invites an automatic re-send.
                return {
                    "submissionId": receipt.submission_id,
                    "outcome": "unknown",
                    "queryRequestKey": receipt.query_request_key,
                    "resend": False,
                }
            return {
                "submissionId": receipt.submission_id,
                "outcome": receipt.outcome,
                "consumedDraftRevision": receipt.consumed_draft_revision,
            }

        def submission_query(params: Mapping[str, Any]) -> dict[str, Any]:
            # Historical reconciliation is keyed by the durable original
            # RequestKey and its frozen target/principal association. It must
            # remain readable when today's draft/native binding decoder has
            # been retired; effectful operations still use ensure_target.
            target = params.get('target')
            if not isinstance(target, str) or not target or target.strip() != target:
                raise WireError('INVALID_REQUEST', 'target is required')
            submission_id = params.get('submissionId')
            if not isinstance(submission_id, str) or not submission_id or submission_id.strip() != submission_id:
                raise WireError('INVALID_REQUEST', 'submissionId is required')
            if not production:
                return {'outcome': 'unknown', 'submissionId': submission_id, 'resend': False}
            service = submission_service()
            observation = service.query(target, submission_id, 'local')
            if observation is None:
                return {'outcome': 'unknown', 'submissionId': submission_id, 'resend': False}
            native = observation.native_fact
            return {
                'submissionId': observation.submission.request.request_id,
                'request': _request_wire(observation.submission.request),
                'outcome': native.outcome if native is not None else 'unknown',
                'backend': _backend_wire(observation.backend_fact),
                'configApply': wire_value(native.config_apply if native is not None
                                          and native.config_apply is not None
                                          else observation.submission.config_apply)
                if (native is not None and native.config_apply is not None)
                or observation.submission.config_apply is not None else None,
                'inputAcceptance': wire_value(native.input_acceptance if native is not None
                                              and native.input_acceptance is not None
                                              else observation.submission.input_acceptance)
                if (native is not None and native.input_acceptance is not None)
                or observation.submission.input_acceptance is not None else None,
                'runResult': wire_value(native.run_result if native is not None
                                        and native.run_result is not None
                                        else observation.submission.run_result)
                if (native is not None and native.run_result is not None)
                or observation.submission.run_result is not None else None,
                'resend': False,
            }

        def _request_wire(request):
            return {
                'environmentNamespace': request.environment_namespace,
                'principalScope': request.principal_scope,
                'requestId': request.request_id,
            }

        def _backend_wire(value):
            if not isinstance(value, tuple) or len(value) != 2:
                return None
            receipt, current = value
            return {
                'request': _request_wire(receipt.request),
                'delivery': receipt.delivery,
                'issuedRevision': receipt.issued_revision,
                'outcome': current.outcome,
                'revision': current.revision,
            }

        def _submission_wire(result):
            record = result.record
            return {
                'submissionId': record.request.request_id,
                'request': _request_wire(record.request),
                'outcome': result.outcome,
                'replayed': result.replayed,
                'stage': record.stage,
                'configApply': wire_value(record.config_apply) if record.config_apply is not None else None,
                'inputAcceptance': wire_value(record.input_acceptance)
                if record.input_acceptance is not None else None,
                'runResult': wire_value(record.run_result) if record.run_result is not None else None,
                'resend': False,
            }

        def session_list(params: Mapping[str, Any]) -> dict[str, Any]:
            target = ensure_target(params)
            sessions = tuple(self._registry.owners_of(target)["session"].list())
            source = 'persisted'
            if production and self._submission_service_factory is not None:
                try:
                    sessions, source = submission_service().list_sessions(target)
                except WireError:
                    # Missing native history support leaves the existing
                    # persisted owner projection readable, with provenance.
                    pass
            result = {"items": [wire_value(session) for session in sessions]}
            if production:
                result['source'] = source
            return result

        def run_query(params: Mapping[str, Any]) -> dict[str, Any]:
            target = ensure_target(params)
            run_id = str(params.get("runId", ""))
            run = self._registry.owners_of(target)["run"].query(run_id)
            if run is None:
                return {"outcome": "unknown", "queryHint": f"run:{run_id}", "resend": False}
            return {"run": dict(run)}

        def interaction_record(params: Mapping[str, Any]) -> dict[str, Any]:
            target = ensure_target(params)
            interaction_id = str(params.get("interactionId", ""))
            fields = params.get("fields", {})
            if not interaction_id or not isinstance(fields, Mapping):
                raise WireError("INVALID_REQUEST", "interactionId must name and fields must map")
            self._registry.owners_of(target)["interaction"].record(interaction_id, fields)
            return {"record": dict(fields)}

        def interaction_list(params: Mapping[str, Any]) -> dict[str, Any]:
            target = ensure_target(params)
            interactions = self._registry.owners_of(target)["interaction"].list()
            return {"items": [dict(i) for i in interactions]}

        def submission_scope(params):
            binding = context.ports.get('core.binding') if production else None
            if binding is None:
                raise WireError('CAPABILITY_UNSUPPORTED', 'authorized submission scope unavailable')
            # Same authenticated scope as submit/query. Never enumerate other
            # installations or principals, and do not require a live native owner.
            return {'namespace': binding.environment.environment_id, 'principalScope': 'local'}

        def submission_capture_read(params):
            target = ensure_target(params)
            service = submission_service()
            reader = getattr(service, 'capture_conditions', None)
            if not callable(reader):
                raise WireError('CAPABILITY_UNSUPPORTED', 'trusted capture conditions unavailable')
            try:
                return reader(target, params.get('mode'), principal_scope='local')
            except Exception as error:
                raise WireError('CAPABILITY_UNSUPPORTED', f'trusted capture conditions unavailable: {error}') from error

        methods = (
            ServerMethodDescriptor(method_id='agent.submission.scope', required_params=frozenset(),
                                   optional_params=frozenset(), handler=submission_scope, owner=PLUGIN_ID),
            ServerMethodDescriptor(method_id='agent.submission.capture.read', required_params=frozenset({'target', 'mode'}),
                                   optional_params=frozenset(), handler=submission_capture_read, owner=PLUGIN_ID),
            ServerMethodDescriptor(method_id='agent.config.observe',
                required_params=frozenset({'target','location','generation','credits'}),
                optional_params=frozenset({'subscriptionId','cursor','nativeOwner'}), handler=config_observe, owner=PLUGIN_ID),
            ServerMethodDescriptor(method_id='agent.config.release',
                required_params=frozenset({'target','location','generation','subscriptionId'}),
                optional_params=frozenset(), handler=config_release, owner=PLUGIN_ID),
            ServerMethodDescriptor(method_id='agent.session.resolve', required_params=frozenset({'location'}),
                optional_params=frozenset({'nativeOwner'}), handler=session_resolve, owner=PLUGIN_ID),
            ServerMethodDescriptor(method_id='agent.config.prepare', required_params=frozenset({'target'}),
                optional_params=frozenset({'revision','generation','submissionId','draftRevision'}), handler=config_prepare, owner=PLUGIN_ID),
            ServerMethodDescriptor(method_id="agent.config.read", required_params=frozenset({"target"}),
                                   optional_params=frozenset(), handler=config_read, owner=PLUGIN_ID),
            ServerMethodDescriptor(method_id="agent.config.submitOperation",
                                   required_params=frozenset({"target"}),
                                   optional_params=frozenset({"patch", "unset", "sourceRef"}),
                                   handler=config_submit_operation, owner=PLUGIN_ID),
            ServerMethodDescriptor(method_id="agent.submitInput", required_params=frozenset({"target"}),
                                   optional_params=frozenset({"draftRevision", "capture"}),
                                   handler=submit_input, owner=PLUGIN_ID),
            ServerMethodDescriptor(method_id="agent.submission.query",
                                   required_params=frozenset({"target", "submissionId"}),
                                   optional_params=frozenset(), handler=submission_query, owner=PLUGIN_ID),
            ServerMethodDescriptor(method_id="agent.session.list", required_params=frozenset({"target"}),
                                   optional_params=frozenset(), handler=session_list, owner=PLUGIN_ID),
            ServerMethodDescriptor(method_id="agent.run.query", required_params=frozenset({"target"}),
                                   optional_params=frozenset({"runId"}), handler=run_query, owner=PLUGIN_ID),
            ServerMethodDescriptor(method_id="agent.interaction.record", required_params=frozenset({"target"}),
                                   optional_params=frozenset({"interactionId", "fields"}),
                                   handler=interaction_record, owner=PLUGIN_ID),
            ServerMethodDescriptor(method_id="agent.interaction.list", required_params=frozenset({"target"}),
                                   optional_params=frozenset(), handler=interaction_list, owner=PLUGIN_ID),
        )
        return ServerPluginRegistration(
            methods=methods,
            provided_ports={"agent.owners@1": self._registry}, disposal=self.close,
        )
