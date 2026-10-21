"""Pure model-choice C2 translation with explicitly supplied provider implementations."""
from __future__ import annotations
import hashlib
import json
from typing import Any, Mapping
from ordessa_agents.harness.definitions import AdapterRefusal, Assessment, ConfigurationAdapterDescriptor, ErrorCode, FieldClaim, FieldPath, IntentSet as HarnessIntentSet, IntentSource, Match, Mismatch, SetField, BindSecret as HarnessBindSecret, TargetHandle as HarnessTargetHandle, ValueSchema, VerificationUnknown, VersionRange
from ordessa_agents.harness.definitions.model_compilation import AdapterContext as LocalAdapterContext
from ordessa_agents.harness.definitions.model_compilation import BindSecret as LocalBindSecret
from ordessa_agents.harness.definitions.model_compilation import ChoiceRequest, CompileIntent, IntentSet as LocalIntentSet
from ordessa_agents.harness.definitions.model_compilation import RequestParams
from ordessa_agents.harness.definitions.model_compilation import MountContent as LocalMountContent
from ordessa_agents.harness.definitions.model_compilation import Refusal as LocalRefusal
from ordessa_agents.harness.definitions.model_compilation import TargetHandle as LocalTargetHandle
from .native_context import NativeLiveModelContext
from ordessa_agents.harness.definitions.model_compilation import parse_version
FACET_ID = 'assets.model-provider'
FACET_SCHEMA_VERSION = '1'
CONTRIBUTOR_VERSION = '1'
ENTRY = 'acp'
ENV_HANDLE_SUFFIX = '.env'
_REFUSAL_CODES = {'capability-unsupported': ErrorCode.CAPABILITY_UNSUPPORTED, 'target-conflict': ErrorCode.TARGET_CONFLICT}

def _inclusive_ceiling(exclusive_high: tuple[int, ...]) -> tuple[int, int, int]:
    """``<0.6`` becomes the inclusive ceiling of everything below: the last
    version of the previous minor series. Semver tuples compare element-wise,
    so a sentinel 999999 covers an open patch/minor range."""
    major, minor = (exclusive_high[0], exclusive_high[1])
    if minor > 0:
        return (major, minor - 1, 999999)
    return (major - 1, 999999, 999999)

def native_version_range(bounds) -> VersionRange:
    low, high = bounds
    minimum = parse_version(low)
    assert minimum is not None
    return VersionRange((minimum + (0, 0))[:3], _inclusive_ceiling(parse_version(high)))

def choice_payload_schema() -> ValueSchema:
    """The ``model-provider.choice.v1`` payload: one Provider/Model selection.

    ``credentialRef`` is a secret *reference*; content never travels here.
    """
    return ValueSchema('object', properties=(('provider', ValueSchema('string')), ('model', ValueSchema('string')), ('endpoint', ValueSchema('string', nullable=True)), ('protocol', ValueSchema('string')), ('credentialRef', ValueSchema('string', nullable=True)), ('authentication', ValueSchema('string')), ('modelCapabilities', ValueSchema('object', properties=(('toolCall', ValueSchema('boolean')), ('reasoning', ValueSchema('boolean')), ('reasoningOptions', ValueSchema('array', items=ValueSchema('object', properties=(('type', ValueSchema('string')), ('values', ValueSchema('array', items=ValueSchema('string')))), required=('type',)))), ('modalities', ValueSchema('object', properties=tuple(((key, ValueSchema('array', items=ValueSchema('string'))) for key in ('input', 'output'))))), ('limits', ValueSchema('object', properties=tuple(((key, ValueSchema('integer')) for key in ('context', 'output'))))), ('cost', ValueSchema('object', properties=tuple(((key, ValueSchema('number')) for key in ('input', 'output', 'cacheRead')))))))), ('brandFields', ValueSchema('object', nullable=True, additional_properties=True)), ('requestParams', ValueSchema('object', nullable=True, properties=(('reasoningEffort', ValueSchema('string')), ('maxTokens', ValueSchema('integer')), ('timeoutMs', ValueSchema('integer')), ('retry', ValueSchema('object', properties=(('enabled', ValueSchema('boolean')), ('maxRetries', ValueSchema('integer')), ('provider', ValueSchema('object', properties=(('maxRetries', ValueSchema('integer')), ('maxRetryDelayMs', ValueSchema('integer'))), required=('maxRetries', 'maxRetryDelayMs')))), required=('enabled', 'maxRetries', 'provider'))))))), required=('provider', 'model', 'protocol'))

def _local_request(payload: Mapping[str, Any]) -> ChoiceRequest:
    brand_fields = payload.get('brandFields') or {}
    try:
        params = RequestParams.from_record(payload.get('requestParams'))
    except ValueError as error:
        raise _MalformedRequestParams(str(error)) from error
    return ChoiceRequest(provider_config_id=str(payload.get('providerConfigId') or payload['provider']), model_id=payload['model'], endpoint=payload.get('endpoint'), protocol=payload['protocol'], credential_ref=payload.get('credentialRef'), provider_name=payload['provider'], brand_fields=dict(brand_fields), params=params)

class _MalformedRequestParams(ValueError):
    """requestParams failed the closed-shape validation; the bridge turns
    this into the typed refusal both call sites answer with."""

def _local_context(context: Any, expected_session_id: str | None=None) -> LocalAdapterContext:
    """Project the harness context onto the local shape (version gate facts)."""
    native = context.installation.native_version
    version = '.'.join((str(part) for part in native)) if native else None
    return LocalAdapterContext(target_handle=LocalTargetHandle(harness_id=context.installation.harness_id, scope='instance', identity=context.targets[0].handle.handle_id), harness_version=version, capabilities={'native_session_id': expected_session_id})

def _to_refusal(refusal: LocalRefusal) -> AdapterRefusal:
    code = _REFUSAL_CODES.get(refusal.code, ErrorCode.CAPABILITY_UNSUPPORTED)
    return AdapterRefusal(code, refusal.message)

def _compiled_intents(context: Any, compiled: LocalIntentSet, mounted_facts: Mapping[int, tuple[str, str]], *, project_mount) -> HarnessIntentSet:
    source = IntentSource(FACET_ID, 'choice', FACET_SCHEMA_VERSION)
    intents = []
    for intent in compiled.intents:
        if isinstance(intent, LocalBindSecret):
            target = _harness_target_of_kind(context, 'environment')
            intents.append(HarnessBindSecret(source, target, intent.slot, intent.secret_ref))
            continue
        try:
            target = _harness_target_of_kind(context, 'file', intent.target_handle.identity)
        except UnauthorizedTargetError:
            return AdapterRefusal(ErrorCode.CAPABILITY_UNSUPPORTED, f"the host composition has not issued the declared target {intent.target_handle.identity!r}; the {(intent.field_path[0] if intent.field_path else '?')} param cannot be projected here")
        if isinstance(intent, CompileIntent):
            intents.append(SetField(source, target, FieldPath(intent.field_path), intent.typed_value))
        elif isinstance(intent, LocalMountContent):
            endpoint, protocol = mounted_facts[id(intent)]
            if not callable(project_mount):
                raise ValueError('No declared mounted-content projection')
            intents.append(project_mount(source, target, intent, endpoint, protocol))
        else:
            raise ValueError(f'unsupported local intent {type(intent).__name__}')
    return HarnessIntentSet(tuple(intents))

def _harness_target_of_kind(context: Any, kind: str, identity: str | None=None) -> HarnessTargetHandle:
    for target in context.targets:
        if target.kind != kind:
            continue
        if identity is None or target.handle.handle_id == identity:
            return target.handle
    wanted = identity or kind
    raise UnauthorizedTargetError(wanted)

class UnauthorizedTargetError(ValueError):
    """The descriptor declares a claim, but the host composition did not
    issue the target: the honest answer is a typed refusal, not a write to a
    lookalike handle."""

class ModelChoiceAdapter:
    """One brand as a real C2 ``ConfigurationAdapter`` (assess/compile/verify)."""

    def __init__(self, *, descriptor, local_adapter, compile_native, project_mount, target_handle_id, minimum_native_version) -> None:
        if not isinstance(descriptor, ConfigurationAdapterDescriptor):
            raise ValueError('Typed model configuration descriptor required')
        if any((not callable(getattr(local_adapter, name, None)) for name in ('assess', 'compile', 'verify'))) or not callable(compile_native):
            raise ValueError('Explicit pure local and native model compilers required')
        if project_mount is not None and (not callable(project_mount)):
            raise ValueError('Explicit mounted-content projection required')
        self.brand = descriptor.harness_id
        self.descriptor = descriptor
        self._impl = local_adapter
        self._compile_native = compile_native
        self._project_mount = project_mount
        self._target_handle_id = target_handle_id
        self._minimum_native_version = minimum_native_version

    def assess(self, context: Any, request: Mapping[str, Any]) -> Assessment:
        if isinstance(context, NativeLiveModelContext):
            if self.brand != context.installation.harness_id:
                return Assessment('unsupported', reason='Native owner context requires matching brand adapter')
            result = self.compile(context, {}, request)
            return Assessment('supported', evidence_ref=context.capability_evidence_ref) if isinstance(result, HarnessIntentSet) else Assessment('unsupported', reason=result.reason)
        if not isinstance(request, Mapping) or 'protocol' not in request or 'model' not in request:
            return Assessment('unknown', reason='probe request carries no choice facts')
        try:
            local_request = _local_request(request)
        except _MalformedRequestParams as error:
            return Assessment('unknown', reason=f'malformed requestParams: {error}')
        verdict = self._impl.assess(_local_context(context), local_request)
        return Assessment(verdict.verdict, reason=verdict.reason, evidence_ref=f'assets.model-provider:{self.brand}:pin' if verdict.verdict == 'supported' else None)

    def compile(self, context: Any, before: Mapping[str, Any], desired: Mapping[str, Any]) -> HarnessIntentSet | AdapterRefusal:
        if isinstance(context, NativeLiveModelContext):
            if self.brand != context.installation.harness_id or not isinstance(desired, Mapping) or 'protocol' not in desired:
                return AdapterRefusal(ErrorCode.CAPABILITY_UNSUPPORTED, 'Full matching native model choice required')
            result = self._compile_native(context, desired, IntentSource(FACET_ID, 'choice', '1'))
            return result if isinstance(result, AdapterRefusal) else HarnessIntentSet((result,))
        payload = dict(desired)
        try:
            local_request = _local_request(payload)
        except _MalformedRequestParams as error:
            return AdapterRefusal(ErrorCode.INVALID_FRAGMENT, f'malformed requestParams: {error}')
        compiled = self._impl.compile(_local_context(context), before, local_request)
        if isinstance(compiled, LocalRefusal):
            return _to_refusal(compiled)
        mounted_facts: dict[int, tuple[str, str]] = {}
        for intent in compiled.intents:
            if isinstance(intent, LocalMountContent):
                mounted_facts[id(intent)] = (str(payload.get('endpoint') or ''), str(payload['protocol']))
        return _compiled_intents(context, compiled, mounted_facts, project_mount=self._project_mount)

    def verify(self, context: Any, observed: Mapping[str, Any]) -> Match | Mismatch | VerificationUnknown:
        if isinstance(context, NativeLiveModelContext):
            if self.brand != context.installation.harness_id or not isinstance(observed, dict) or set(observed) != {'currentValue', 'expectedValue'} or (not isinstance(observed['expectedValue'], str)) or (observed['expectedValue'] != observed['currentValue']):
                return Mismatch('Native model selection differs from operation-bound expectation')

            def flatten(options):
                for item in options:
                    if 'value' in item:
                        yield item
                    yield from flatten(item.get('options', []))
            values = [item for selector in context.native_snapshot.config_options if selector.get('id') == 'model' for item in flatten(selector.get('options', [])) if item.get('value') == observed['currentValue']]
            if len(values) != 1:
                return VerificationUnknown('Model was not independently observed in this owner catalog')
            digest = hashlib.sha256(json.dumps(observed, sort_keys=True).encode()).hexdigest()
            return Match(self.brand + '-native-model-readback:' + digest)
        expected_session = observed.get('expected_native_session_id')
        local_ctx = _local_context(context, expected_session_id=expected_session if isinstance(expected_session, str) else None)
        verdict = self._impl.verify(local_ctx, observed)
        if verdict.verdict == 'match':
            digest = hashlib.sha256(json.dumps(observed, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()[:16]
            return Match(f'model-provider:readback:{digest}')
        if verdict.verdict == 'mismatch':
            return Mismatch(verdict.reason or 'native readback differs from the compiled intent')
        return VerificationUnknown(verdict.reason or 'no read-back sample')

    def reconfiguration_for(self, payload) -> str:
        """'session-local' | 'restart-resume' | 'refused' for one choice.

    The brand reconfiguration declaration is a pinned semantic (conformance);
    the harness C2 compile surface does not carry it, so the controlled E2
    runtime reads it here to drive restart-resume honestly.
    """
        local_ctx = LocalAdapterContext(target_handle=LocalTargetHandle(harness_id=self.brand, scope='instance', identity=self._target_handle_id), harness_version=self._minimum_native_version)
        result = self._impl.compile(local_ctx, {}, _local_request(payload))
        if isinstance(result, LocalRefusal):
            return 'refused'
        return result.reconfiguration
