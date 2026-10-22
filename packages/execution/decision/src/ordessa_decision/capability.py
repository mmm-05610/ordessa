"""`decisions` capability over the frozen F1 contracts (independent package)."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
import re

from ordessa_interfaces_contracts import (
    Capability, CapabilityDescriptor, CapabilityError, OperationDescriptor,
    OperationResult, compute_descriptor_digest, validate_capability, validate_result,
)

from .definitions.values import DecisionError, digest_hex, canonical_bytes, job_document_bound
from .job import validate_job
from .runner import DecisionRunner
from .settings import DecisionsSettings
from .evidence import EvidenceScope

CAPABILITY_ID = "decisions"
VERSION = "f1/3.1"
_JOB_SCHEMA = {"type": "object", "required": ["job"],
               "additionalProperties": False,
               "properties": {"job": {"type": "object"}}}
_MAP = {"type": "object"}
_ERR = {"INVALID_INPUT": "INVALID_INPUT", "invalid_job": "INVALID_INPUT",
        "run_request_conflict":"CONFLICT", "authority_unavailable": "AUTHORITY_UNAVAILABLE", "permission_denied": "PERMISSION_DENIED",
        "engine_required": "CAPABILITY_UNSUPPORTED",
        "engine_unavailable": "CAPABILITY_UNSUPPORTED",
        "engine_not_allowed": "CAPABILITY_UNSUPPORTED",
        "provider_unavailable": "PROVIDER_UNAVAILABLE",
        "running_loop": "INVALID_INPUT", "CAPABILITY_UNSUPPORTED": "CAPABILITY_UNSUPPORTED"}


def _error(code: str, message: str) -> CapabilityError:
    return CapabilityError(_ERR.get(code, "INVALID_INPUT"), message)


def _failed(code: str, message: str) -> OperationResult:
    return OperationResult("refused", error=_error(code, message))


def _encode_recorded(result):
    validate_result(result)
    return {'status':result.status,'data':result.data,'error':None if result.error is None else {
        'code':result.error.code,'message':result.error.message,'retryable':result.error.retryable},
        'operationRef':result.operation_ref,'evidenceRefs':list(result.evidence_refs)}


def _decode_recorded(value,operation):
    if type(value) is not dict or set(value)!={'status','data','error','operationRef','evidenceRefs'}:
        raise DecisionError('run_record_corrupt')
    error=value['error']
    if error is not None:
        if type(error) is not dict or set(error)!={'code','message','retryable'}:raise DecisionError('run_record_corrupt')
        error=CapabilityError(error['code'],error['message'],error['retryable'])
    if type(value['evidenceRefs']) is not list or value['operationRef'] not in (None,operation):raise DecisionError('run_record_corrupt')
    return validate_result(OperationResult(value['status'],data=value['data'],error=error,
        operation_ref=value['operationRef'],evidence_refs=tuple(value['evidenceRefs'])))


class DecisionsCapability:
    def __init__(self, settings: DecisionsSettings, invocation_resolver=None, evidence_scope_resolver=None):
        self.settings = settings
        self.invocation_resolver=invocation_resolver
        self.evidence_scope_resolver=evidence_scope_resolver
        # Owner-held background work for async model runs (F11). These tasks are
        # not a second executor or a wire queue: each is one already-claimed run.
        self._background=set()
        self._running=set()

    def _store(self,context,operation):
        if (not callable(self.invocation_resolver) or not callable(self.evidence_scope_resolver)
                or not callable(getattr(self.settings.evidence,'scoped',None))):
            raise DecisionError('authority_unavailable')
        try:
            invocation=self.invocation_resolver(context)
            if invocation is None:raise ValueError()
            scope=self.evidence_scope_resolver(invocation,operation)
            if type(scope) is not EvidenceScope:raise ValueError()
            store=self.settings.evidence.scoped(scope)
            store.verify_scope(for_write=operation=='decisions.run')
            return store,scope
        except Exception:
            raise DecisionError('permission_denied') from None

    async def validate(self, request: Mapping, context) -> OperationResult:
        try:
            job = validate_job(request["job"], host_limits=self.settings.host_limits)
            canonical_bytes({'job': job.raw, 'dryRun': False},
                            maximum=job_document_bound(self.settings.job_document_max_bytes))
        except (KeyError, TypeError):
            return _failed("INVALID_INPUT", "job is required")
        except DecisionError as exc:
            return _failed(exc.code, "decision job is invalid")
        return OperationResult("completed", data={
            "job_id": job.job_id, "version": job.version,
            "steps": len(job.steps), "limits": job.limits})

    async def run(self, request: Mapping, context) -> OperationResult:
        try:store,scope=self._store(context,'decisions.run')
        except DecisionError as exc:return _failed(exc.code,'decision evidence scope unavailable or refused')
        try:
            job = validate_job(request["job"], host_limits=self.settings.host_limits)
            canonical_bytes({'job': job.raw, 'dryRun': False},
                            maximum=job_document_bound(self.settings.job_document_max_bytes))
        except (KeyError, TypeError):
            return _failed("INVALID_INPUT", "job is required")
        except DecisionError as exc:
            return _failed(exc.code, "decision job is invalid")
        dry_run = request.get("dry_run", False)
        if type(dry_run) is not bool:
            return _failed("INVALID_INPUT", "dry_run must be a boolean")
        has_model_step = any(step["type"] == "ask" for step in job.steps)
        if dry_run and has_model_step:
            return _failed("CAPABILITY_UNSUPPORTED",
                           "dry-run jobs may not call a model")
        if has_model_step and not dry_run and self.settings.provider is None:
            # Refused before the claim: an unconfigured provider is not a run.
            return _failed('provider_unavailable',
                           'decision model provider is not configured')
        request_digest=digest_hex({'job':job.raw,'dryRun':dry_run}, maximum=job_document_bound(self.settings.job_document_max_bytes))
        try:
            _,read_scope=self._store(context,'decisions.get')
            if read_scope!=scope:raise DecisionError('permission_denied')
        except DecisionError:return _failed('permission_denied','original decision request read refused')
        try:
            created,operation,recorded=store.claim_run(context.request_id,request_digest)
        except DecisionError as exc:
            if exc.code=='run_request_conflict':return _failed(exc.code,'same request has different input')
            return OperationResult('unknown',error=CapabilityError('EFFECT_UNKNOWN','original decision request record unavailable',False))
        if not created:
            try:
                _,read_scope=self._store(context,'decisions.get')
                if read_scope!=scope:raise DecisionError('permission_denied')
            except DecisionError:return _failed('permission_denied','original decision request read refused')
            if recorded is None:
                if (scope, context.request_id) in self._running:
                    return OperationResult('accepted',data={'state':'pending'},operation_ref=operation)
                return OperationResult('unknown',error=CapabilityError('EFFECT_UNKNOWN','original decision run is unresolved; no retry',False),operation_ref=operation)
            try:return _decode_recorded(recorded,operation)
            except Exception:
                return OperationResult('unknown',error=CapabilityError('EFFECT_UNKNOWN','original decision result unavailable',False),operation_ref=operation)
        if has_model_step and not dry_run:
            # F11: a model-bearing run leaves the HTTP wait; the owner keeps the
            # claim and publishes the terminal fact for a later query.
            task=asyncio.get_running_loop().create_task(self._run_background(
                job,store,scope,context,operation,request_digest))
            self._background.add(task);self._running.add((scope, context.request_id))
            task.add_done_callback(lambda done,_rid=(scope, context.request_id):
                (self._background.discard(done),self._running.discard(_rid)))
            return OperationResult('accepted',data={'state':'pending'},operation_ref=operation)
        result=await self._execute_once(job,dry_run,store,scope,context,operation)
        # A revoked scope left the original claim unresolved. Never persist under
        # a different subject or retry to reconstruct this possibly executed run.
        try:
            current_store,current_scope=self._store(context,'decisions.run')
            if current_scope!=scope:raise DecisionError('permission_denied')
            current_store.complete_run(context.request_id,request_digest,_encode_recorded(result))
        except Exception:
            return OperationResult('unknown',error=CapabilityError('EFFECT_UNKNOWN','original decision result publication uncertain',False),operation_ref=operation)
        try:
            _,read_scope=self._store(context,'decisions.get')
            if read_scope!=scope:raise DecisionError('permission_denied')
        except DecisionError:
            return OperationResult('unknown',error=CapabilityError('EFFECT_UNKNOWN',
                'decision executed but original result read is unavailable',False),operation_ref=operation)
        return result

    async def _execute_once(self,job,dry_run,store,scope,context,operation):
        runner = self.settings.runner(provider=None if dry_run else self.settings.provider)
        try:
            result = await runner.run_async(job.raw)
        except DecisionError as exc:
            return _failed(exc.code, "decision run is invalid")
        if result.status == "refused":
            return _failed(result.error["code"], "decision run refused")
        # Recheck current external scope after an awaited provider. Lost access
        # cannot rebind the same result to another subject or an unowned root.
        try:
            store,current=self._store(context,'decisions.run')
            if current!=scope:raise DecisionError('permission_denied')
        except DecisionError:
            return OperationResult('unknown',error=CapabilityError('EFFECT_UNKNOWN',
                'decision result could not be stored under its original authorized scope',False),
                operation_ref=operation)
        if result.status == "unknown":
            ref = store.put(result.evidence)
            return OperationResult("unknown", error=CapabilityError(
                "EFFECT_UNKNOWN", "model call outcome is unknown", False),
                operation_ref=operation,
                evidence_refs=("sha256:" + ref.digest,))
        ref = store.put(result.evidence)
        return OperationResult("completed", data={"result": result.data["result"],
                                                  "evidence": {"digest": ref.digest,
                                                               "byte_length": ref.byte_length,
                                                               "durability": ref.durability}},
                               operation_ref=operation,
                               evidence_refs=("sha256:" + ref.digest,))

    async def _run_background(self,job,store,scope,context,operation,request_digest):
        """One already-claimed model run; publish only under current authority.

        Authorization is rechecked at the actual dispatch after acceptance; a
        revoked scope refuses before any provider call. If publication is no
        longer authorized, the durable claim remains unresolved and query reports
        unknown once the in-process task is no longer running.
        """
        result=None
        try:
            try:
                _,current=self._store(context,'decisions.run')
                if current!=scope:raise DecisionError('permission_denied')
            except DecisionError:
                result=_failed('permission_denied','decision dispatch refused after acceptance')
            if result is None:
                result=await self._execute_once(job,False,store,scope,context,operation)
        except asyncio.CancelledError:
            result=OperationResult('unknown',error=CapabilityError(
                'EFFECT_UNKNOWN','decision background run was cancelled',False),
                operation_ref=operation)
            raise
        except Exception:
            result=OperationResult('unknown',error=CapabilityError(
                'EFFECT_UNKNOWN','decision background outcome unknown',False),
                operation_ref=operation)
        try:
            current_store,current_scope=self._store(context,'decisions.run')
            if current_scope!=scope:raise DecisionError('permission_denied')
            current_store.complete_run(context.request_id,request_digest,_encode_recorded(result))
        except Exception:
            # Unpublished result stays an unconfirmed claim (readable unknown);
            # it is never retried or rebound to another subject.
            return
        finally:
            self._running.discard((scope, context.request_id))

    async def wait_background(self):
        """Await every owner-held run (tests and orderly shutdown)."""
        if self._background:
            await asyncio.gather(*tuple(self._background),return_exceptions=True)

    async def query(self, request: Mapping, context) -> OperationResult:
        """Read one ORIGINAL run by request id and input digest; never claims.

        The digest is recomputed exactly as ``run`` did. A missing claim, a
        foreign scope or a different input is refused without creating a claim,
        calling a provider or resending the job. A claim without a result is a
        pending only while this owner still runs it; otherwise it is unknown,
        never a new execution right.
        """
        original = request.get("originalRequestId")
        if (type(original) is not str or not original or len(original) > 512
                or any(ord(c) < 32 or ord(c) == 127 for c in original)):
            return _failed("INVALID_INPUT", "originalRequestId is required")
        try: store, _scope = self._store(context, 'decisions.query')
        except DecisionError as exc: return _failed(exc.code, 'decision evidence scope unavailable or refused')
        try:
            job = validate_job(request["job"], host_limits=self.settings.host_limits)
            canonical_bytes({'job': job.raw, 'dryRun': False},
                            maximum=job_document_bound(self.settings.job_document_max_bytes))
        except (KeyError, TypeError):
            return _failed("INVALID_INPUT", "job is required")
        except DecisionError as exc:
            return _failed(exc.code, "decision job is invalid")
        dry_run = request.get("dry_run", False)
        if type(dry_run) is not bool:
            return _failed("INVALID_INPUT", "dry_run must be a boolean")
        if dry_run and any(step["type"] == "ask" for step in job.steps):
            return _failed("CAPABILITY_UNSUPPORTED", "dry-run jobs may not call a model")
        request_digest = digest_hex({'job': job.raw, 'dryRun': dry_run},
                                    maximum=job_document_bound(self.settings.job_document_max_bytes))
        try:
            operation, recorded = store.read_run(original, request_digest)
        except DecisionError as exc:
            if exc.code == 'run_not_found':
                return _failed("INVALID_INPUT", "original decision run was not found")
            if exc.code == 'run_request_conflict':
                return _failed("run_request_conflict", "original decision request has different input")
            return _failed("INVALID_INPUT", "original decision run record is invalid")
        if recorded is None:
            if (_scope, original) in self._running:
                return OperationResult("accepted", data={"state": "pending"},
                                       operation_ref=operation)
            return OperationResult("unknown", error=CapabilityError(
                "EFFECT_UNKNOWN", "original decision run is unresolved; no retry", False),
                operation_ref=operation)
        try:
            return _decode_recorded(recorded, operation)
        except Exception:
            return OperationResult("unknown", error=CapabilityError(
                "EFFECT_UNKNOWN", "original decision result unavailable", False),
                operation_ref=operation)

    async def get(self, request: Mapping, context) -> OperationResult:
        return await self._get(request,context,'decisions.get')

    async def _get(self,request,context,operation):
        digest = request.get("digest")
        if type(digest) is not str or re.fullmatch(r'[0-9a-f]{64}',digest) is None:
            return _failed("INVALID_INPUT", "evidence digest is required")
        try:store,_=self._store(context,operation)
        except DecisionError as exc:return _failed(exc.code,'decision evidence scope unavailable or refused')
        try:
            summary = store.get(digest)
        except DecisionError:
            return _failed("INVALID_INPUT", "evidence is unavailable")
        return OperationResult("completed", data={"summary": summary})

    async def evidence(self, request: Mapping, context) -> OperationResult:
        return await self._get(request, context,'decisions.evidence')


_QUERY_SCHEMA = {
    "type": "object", "required": ["originalRequestId", "job"], "additionalProperties": False,
    "properties": {**_JOB_SCHEMA["properties"], "originalRequestId": {"type": "string", "minLength": 1, "maxLength": 512},
                   "dry_run": {"type": "boolean"}}}


def _cli_metadata(operation, args):
    return {'command': 'decisions', 'operation': operation, 'args': tuple(args)}


def descriptor() -> CapabilityDescriptor:
    operations = (
        OperationDescriptor(f"{CAPABILITY_ID}.validate", _JOB_SCHEMA, _MAP, cli=_cli_metadata(
            'validate', [{'name': 'job', 'flags': ('--job',), 'type': 'json-file'}])),
        OperationDescriptor(f"{CAPABILITY_ID}.run", {**_JOB_SCHEMA,
                           "properties": {**_JOB_SCHEMA["properties"],
                                          "dry_run": {"type": "boolean"}}}, _MAP, cli=_cli_metadata(
            'run', [{'name': 'job', 'flags': ('--job',), 'type': 'json-file'},
                    {'name': 'dry_run', 'flags': ('--dry-run',), 'type': 'boolean', 'jsonPath': 'dry_run'}])),
        OperationDescriptor(f"{CAPABILITY_ID}.get", {
            "type": "object", "required": ["digest"], "additionalProperties": False,
            "properties": {"digest": {"type": "string"}}}, _MAP, cli=_cli_metadata(
            'get', [{'name': 'digest', 'flags': ('--digest',), 'type': 'string'}])),
        OperationDescriptor(f"{CAPABILITY_ID}.evidence", {
            "type": "object", "required": ["digest"], "additionalProperties": False,
            "properties": {"digest": {"type": "string"}}}, _MAP, cli=_cli_metadata(
            'evidence', [{'name': 'digest', 'flags': ('--digest',), 'type': 'string'}])),
        OperationDescriptor(f"{CAPABILITY_ID}.query", _QUERY_SCHEMA, _MAP, cli=_cli_metadata(
            'query', [{'name': 'originalRequestId', 'flags': ('--original-request-id',), 'type': 'string'},
                      {'name': 'job', 'flags': ('--job',), 'type': 'json-file'},
                      {'name': 'dry_run', 'flags': ('--dry-run',), 'type': 'boolean', 'jsonPath': 'dry_run'}])),
    )
    base = CapabilityDescriptor(CAPABILITY_ID, VERSION, operations, "")
    return CapabilityDescriptor(CAPABILITY_ID, VERSION, operations,
                                compute_descriptor_digest(base))


def build_capability(settings: DecisionsSettings, *, invocation_resolver=None, evidence_scope_resolver=None) -> Capability:
    if type(settings) is not DecisionsSettings:
        raise DecisionError("invalid_settings")
    service = DecisionsCapability(settings,invocation_resolver,evidence_scope_resolver)
    capability = Capability(descriptor(), {
        f"{CAPABILITY_ID}.validate": service.validate,
        f"{CAPABILITY_ID}.run": service.run,
        f"{CAPABILITY_ID}.get": service.get,
        f"{CAPABILITY_ID}.evidence": service.evidence,
        f"{CAPABILITY_ID}.query": service.query,
    })
    validate_capability(capability)
    # Internal owner handle (not a public operation): orderly shutdown/tests need
    # to await the same owner-held background runs; it issues no capability.
    try:
        object.__setattr__(capability, '_decision_service', service)
    except (AttributeError, TypeError):
        pass
    return capability


class DecisionsCapabilityFactory:
    """Entry point object; bindings are trusted process-local services."""

    def build(self, bindings: Mapping) -> Capability:
        if not isinstance(bindings, Mapping):
            raise DecisionError("invalid_bindings")
        services = bindings.get("services")
        if not isinstance(services, Mapping):
            raise DecisionError("invalid_bindings")
        settings = services.get("decisions")
        if type(settings) is not DecisionsSettings:
            raise DecisionError("invalid_bindings")
        return build_capability(settings,invocation_resolver=bindings.get('invocation_resolver'),
            evidence_scope_resolver=bindings.get('evidence_scope_resolver'))


factory = DecisionsCapabilityFactory()
