"""Small application services. Native effects remain provider work."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import re
from uuid import uuid4
from typing import Mapping, Sequence

from .events import CoreEvent, EventType, execution_created_event
from .errors import (
    ContractViolation,
    DispatchAmbiguous,
    DispatchFailed,
    DispatchRejected,
    ExecutionStartRejected,
    InvalidStartReceipt,
    InvalidProjectionTransition,
    FinalizationRequired,
    FinalizationConflict,
)
from .finalization import ExecutionFinalizationRequest, FinalizationReceipt
from .models import Execution, Ref, RefType, Work, WorkLifecycle
from .projection import ExecutionProjection, Freshness, Phase
from .registry import (
    ExecutionPreflightRequest,
    ExecutionStartReceipt,
    ExecutionStartRequest,
    ExtensionRegistry,
    RecoverySupport,
    ResolvedExecutionInput,
    ResolutionEffect,
    ResourceResolutionContext,
)
from .repository import CoreRepository, RefRelation
from .resource_observations import ResourceObservation


def _ref_identity(ref: Ref) -> tuple:
    return (
        ref.type,
        ref.provider,
        ref.native_id,
        ref.uri,
        tuple(sorted(ref.metadata.items())),
    )


#: An upper-snake token is the shared shape of a typed code across layers (the
#: ``code`` attribute the secrets store sets, and the reason-code vocabulary the
#: transcript maps). Only a *whole* token counts, so a sentence never becomes a
#: code by accident.
_TYPED_CODE = re.compile(r"[A-Z][A-Z0-9_]{2,127}")


def _dispatch_error_code(exc: BaseException) -> str | None:
    """Order 135: pull the typed code out of the exception a Dispatch will wrap.

    The low layer (secrets/runtime) raises the credential failure with a real
    ``code`` attribute, but ``_safe_code`` on the transcript leg only reads a
    ``code`` off an ``ExecutionStartRejected`` in the chain - so a plain
    ``RuntimeError("CREDENTIAL_NOT_AVAILABLE")`` reaching this wrap loses its
    identity the moment we stringify it into a Dispatch. We re-attach it here so
    the code travels structurally to the user-visible leg instead of surviving
    as message text. Truly unknown failures (no attribute, sentence message)
    still return ``None`` and stay the generic reason.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        explicit = getattr(current, "code", None)
        if isinstance(explicit, str) and _TYPED_CODE.fullmatch(explicit):
            return explicit
        current = current.__cause__ or current.__context__
    message = str(exc).strip()
    if _TYPED_CODE.fullmatch(message):
        return message
    return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class WorkService:
    def __init__(self, repository: CoreRepository) -> None:
        self.repository = repository

    def create_work(self, objective: str, *, metadata: dict[str, str] | None = None) -> Work:
        now, work_id = _now(), _id("work")
        work = Work(work_id, objective, WorkLifecycle.OPEN, now, now, metadata=metadata or {})
        return self.repository.create_work(work, CoreEvent(_id("evt"), EventType.WORK_CREATED, work_id, now, {"objective": objective}))

    def complete_work(self, work_id: str, reason: str) -> Work:
        current, now = self.repository.get_work(work_id), _now()
        next_value = replace(current, lifecycle=WorkLifecycle.COMPLETED, closure_reason=reason, updated_at=now)
        return self.repository.update_work(next_value, expected_version=current.version, event=CoreEvent(_id("evt"), EventType.WORK_COMPLETED, work_id, now, {"reason": reason}))

    def reopen_work(self, work_id: str, reason: str) -> Work:
        current, now = self.repository.get_work(work_id), _now()
        next_value = replace(current, lifecycle=WorkLifecycle.OPEN, closure_reason=None, updated_at=now)
        return self.repository.update_work(next_value, expected_version=current.version, event=CoreEvent(_id("evt"), EventType.WORK_REOPENED, work_id, now, {"reason": reason}))


class ExecutionService:
    def __init__(self, repository: CoreRepository) -> None:
        self.repository = repository

    def create_execution(
        self,
        work_id: str,
        provider_id: str,
        *,
        responsibility_intent: str,
        provenance: dict[str, str] | None = None,
    ) -> Execution:
        now, execution_id = _now(), _id("exec")
        projection = ExecutionProjection(Phase.UNKNOWN, None, None, Freshness.STALE, now)
        execution = Execution(execution_id, work_id, provider_id, projection, now, provenance=provenance or {})
        event = execution_created_event(
            _id("evt"),
            execution_id,
            now,
            provider_id=provider_id,
            responsibility_intent=responsibility_intent,
        )
        return self.repository.create_execution(execution, event)

    def dispatch_execution(
        self,
        execution_id: str,
        inputs: Sequence[tuple[str, Ref]],
        registry: ExtensionRegistry,
        idempotency_key: str,
    ):
        """Freeze, resolve, validate and start one Preview Execution Dispatch."""
        canonical = self._canonicalize_input_shape(inputs)
        inputs_digest = self._inputs_digest(canonical)

        existing = self.repository.get_dispatch_by_key(idempotency_key)
        if existing is not None:
            if existing["execution_id"] != execution_id:
                raise DispatchRejected(
                    "dispatch idempotency key belongs to another execution"
                )
            if existing["inputs_digest"] != inputs_digest:
                raise DispatchRejected(
                    "dispatch idempotency key was reused with different inputs"
                )
            # Replay never re-invokes provider.start: an accepted Dispatch is
            # a sealed side effect, a failed one keeps its recorded error, and
            # a still-requested one cannot prove whether start ran at all.
            state = existing["state"]
            if state == "accepted":
                return self.repository.get_dispatch_receipt(existing["id"])
            if state == "failed":
                raise DispatchFailed(
                    f"Dispatch already failed for {execution_id}: "
                    f"{self._recorded_dispatch_error(existing['id'], execution_id) or 'unknown error'}"
                )
            raise DispatchAmbiguous(
                f"Dispatch {existing['id']} for {execution_id} is still "
                f"'{state}'; whether provider.start produced side effects "
                "cannot be proven from Core"
            )

        execution = self.repository.get_execution(execution_id)
        provider = registry.get(execution.provider_id)
        self._validate_registered_contracts(canonical, registry)
        self._validate_input_limits(provider, canonical)

        now, dispatch_id = _now(), _id("dispatch")
        requested_event = CoreEvent(
            _id("evt"),
            EventType.EXECUTION_DISPATCH_REQUESTED,
            execution_id,
            now,
            {
                "dispatch_id": dispatch_id,
                "inputs_digest": inputs_digest,
                "provider": provider.descriptor().id,
                "provider_version": provider.descriptor().version,
            },
            idempotency_key,
        )
        self.repository.create_dispatch_with_inputs(
            dispatch_id,
            execution_id,
            canonical,
            inputs_digest,
            idempotency_key,
            requested_event,
        )

        try:
            preflight_ids = self._preflight_contract_ids(provider)
            early, late = self._partition_inputs(provider, canonical, preflight_ids)
            resolved_early = self._resolve_inputs(early, registry, execution_id=execution_id, dispatch_id=dispatch_id)
            if preflight_ids:
                preflight = getattr(provider, "preflight", None)
                if not callable(preflight):
                    raise ContractViolation(
                        "ExecutionProvider declares preflight inputs but has no preflight()"
                    )
                preflight(ExecutionPreflightRequest(
                    execution_id, dispatch_id, inputs_digest, canonical, resolved_early,
                ))
            resolved_late = self._resolve_inputs(late, registry, execution_id=execution_id, dispatch_id=dispatch_id)
            by_ref = {
                (item.contract_id, _ref_identity(item.ref)): item
                for item in (*resolved_early, *resolved_late)
            }
            request = ExecutionStartRequest(
                execution_id,
                dispatch_id,
                inputs_digest,
                tuple(
                    by_ref[(contract_id, _ref_identity(ref))]
                    for contract_id, ref in canonical
                ),
            )
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"[:256]
            self.repository.record_dispatch_failed(dispatch_id, message)
            error = DispatchFailed(
                f"Execution Dispatch failed for {execution_id}: {message}"
            )
            code = _dispatch_error_code(exc)
            if code is not None:
                error.code = code
            raise error from exc

        try:
            receipt = provider.start(request)
            self._validate_start_receipt(provider, request, receipt)
        except ExecutionStartRejected as exc:
            message = f"{type(exc).__name__}: {exc}"[:256]
            self.repository.record_dispatch_failed(dispatch_id, message)
            error = DispatchFailed(
                f"Execution Dispatch failed for {execution_id}: {message}"
            )
            code = _dispatch_error_code(exc)
            if code is not None:
                error.code = code
            raise error from exc
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"[:256]
            self.repository.record_dispatch_ambiguous(dispatch_id, message)
            error = DispatchAmbiguous(
                f"Execution Dispatch is ambiguous for {execution_id}: {message}"
            )
            code = _dispatch_error_code(exc)
            if code is not None:
                error.code = code
            raise error from exc

        self.repository.record_dispatch_accepted(dispatch_id, receipt)
        return self.repository.get_dispatch_receipt(dispatch_id)

    @staticmethod
    def _canonicalize_input_shape(
        inputs: Sequence[tuple[str, Ref]],
    ) -> tuple[tuple[str, Ref], ...]:
        values: list[tuple[str, Ref, tuple]] = []
        seen: dict[tuple, str] = {}
        for item in inputs:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ContractViolation("each input must be a (contract_id, Ref) tuple")
            contract_id, ref = item
            if not isinstance(contract_id, str) or not contract_id.strip():
                raise ContractViolation("input contract_id is required")
            if not isinstance(ref, Ref):
                raise ContractViolation("input must contain a Ref")
            ref_type = ref.type.value
            identity = (
                ref_type,
                ref.provider,
                ref.native_id,
                ref.uri,
                tuple(sorted(ref.metadata.items())),
            )
            previous = seen.get(identity)
            if previous is not None and previous != contract_id:
                raise ContractViolation(
                    "one Ref cannot use multiple contract_ids in one Execution"
                )
            if previous is not None:
                raise ContractViolation("duplicate input Ref")
            seen[identity] = contract_id
            values.append((contract_id, ref, identity))
        values.sort(key=lambda value: (value[0], value[2]))
        return tuple((contract_id, ref) for contract_id, ref, _ in values)

    @staticmethod
    def _canonicalize_inputs(inputs, registry):
        canonical = ExecutionService._canonicalize_input_shape(inputs)
        ExecutionService._validate_registered_contracts(canonical, registry)
        return canonical

    @staticmethod
    def _validate_registered_contracts(inputs, registry) -> None:
        for contract_id, _ in inputs:
            try:
                registry.get_contract_type(contract_id)
            except ValueError as exc:
                raise ContractViolation(
                    f"unknown resource contract: {contract_id}"
                ) from exc

    @staticmethod
    def _validate_input_limits(provider, inputs: Sequence[tuple[str, Ref]]) -> None:
        declared = getattr(provider, "input_limits", None)
        limits = declared() if callable(declared) else declared
        if not isinstance(limits, Mapping):
            raise ContractViolation(
                f"ExecutionProvider {provider.descriptor().id} must declare input_limits()"
            )
        counts: dict[str, int] = {}
        for contract_id, _ in inputs:
            counts[contract_id] = counts.get(contract_id, 0) + 1
        for contract_id, count in counts.items():
            if contract_id not in limits:
                raise ContractViolation(
                    f"ExecutionProvider does not accept contract: {contract_id}"
                )
            minimum, maximum = limits[contract_id]
            if count < minimum or (maximum is not None and count > maximum):
                raise ContractViolation(
                    f"contract input count outside provider limit: {contract_id} ({count})"
                )
        for contract_id, limit in limits.items():
            minimum, maximum = limit
            count = counts.get(contract_id, 0)
            if count < minimum or (maximum is not None and count > maximum):
                raise ContractViolation(
                    f"contract input count outside provider limit: {contract_id} ({count})"
                )

    @staticmethod
    def _inputs_digest(inputs: Sequence[tuple[str, Ref]]) -> str:
        canonical = []
        for contract_id, ref in inputs:
            canonical.append(
                {
                    "contract_id": contract_id,
                    "ref": {
                        "type": ref.type.value,
                        "provider": ref.provider,
                        "native_id": ref.native_id,
                        "uri": ref.uri,
                        "metadata": dict(sorted(ref.metadata.items())),
                    },
                }
            )
        encoded = json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _resolve_inputs(
        inputs: Sequence[tuple[str, Ref]], registry: ExtensionRegistry,
        *, execution_id: str | None = None, dispatch_id: str | None = None
    ) -> tuple[ResolvedExecutionInput, ...]:
        resolved: list[ResolvedExecutionInput] = []
        for contract_id, ref in inputs:
            resource_provider = registry.get_resource_provider(ref.provider)
            if contract_id not in resource_provider.supported_contract_ids:
                raise ContractViolation(
                    f"resource provider {ref.provider} does not support {contract_id}"
                )
            if execution_id is not None:
                try:
                    value = resource_provider.resolve(contract_id, ref, context=ResourceResolutionContext(execution_id, dispatch_id))
                except TypeError as exc:
                    if "context" not in str(exc):
                        raise
                    value = resource_provider.resolve(contract_id, ref)
            else:
                value = resource_provider.resolve(contract_id, ref)
            try:
                expected_type = registry.get_contract_type(contract_id)
            except ValueError as exc:
                raise ContractViolation(
                    f"unknown resource contract: {contract_id}"
                ) from exc
            if not isinstance(value, expected_type):
                raise ContractViolation(
                    f"resource provider returned {type(value).__name__} for {contract_id}; "
                    f"expected {expected_type.__name__}"
                )
            resolved.append(ResolvedExecutionInput(contract_id, ref, value))
        return tuple(resolved)

    @staticmethod
    def _preflight_contract_ids(provider) -> frozenset[str]:
        declared = getattr(provider, "preflight_contract_ids", None)
        if declared is None:
            return frozenset()
        values = declared() if callable(declared) else declared
        if not isinstance(values, frozenset) or not all(
            isinstance(contract_id, str) for contract_id in values
        ):
            raise ContractViolation("preflight_contract_ids() must return frozenset[str]")
        return values

    @staticmethod
    def _partition_inputs(provider, inputs, preflight_ids):
        effect_for = getattr(provider, "resolution_effect", None)
        early: list[tuple[str, Ref]] = []
        late: list[tuple[str, Ref]] = []
        for contract_id, ref in inputs:
            raw_effect = (
                effect_for(contract_id)
                if callable(effect_for)
                else ResolutionEffect.IDEMPOTENT_MATERIALIZATION
            )
            try:
                effect = ResolutionEffect(raw_effect)
            except ValueError as exc:
                raise ContractViolation(
                    f"invalid resolution effect for {contract_id}: {raw_effect!r}"
                ) from exc
            if contract_id in preflight_ids:
                if effect is not ResolutionEffect.PURE:
                    raise ContractViolation(
                        f"preflight contract must have pure resolution: {contract_id}"
                    )
                early.append((contract_id, ref))
            else:
                late.append((contract_id, ref))
        return tuple(early), tuple(late)

    @staticmethod
    def _validate_start_receipt(provider, request, receipt) -> None:
        if not isinstance(receipt, ExecutionStartReceipt):
            raise InvalidStartReceipt("provider.start() must return ExecutionStartReceipt")
        if (
            receipt.execution_id != request.execution_id
            or receipt.dispatch_id != request.dispatch_id
            or receipt.inputs_digest != request.inputs_digest
        ):
            raise InvalidStartReceipt("start receipt identity does not match request")
        if not isinstance(receipt.recovery_support, RecoverySupport):
            raise InvalidStartReceipt("start receipt recovery_support is invalid")
        correlation = receipt.correlation_ref
        if receipt.recovery_support is not RecoverySupport.NONE and correlation is None:
            raise InvalidStartReceipt("recoverable receipt requires correlation_ref")
        if correlation is not None and correlation.provider != provider.descriptor().id:
            raise InvalidStartReceipt(
                "receipt correlation Ref must belong to ExecutionProvider"
            )

    def _recorded_dispatch_error(self, dispatch_id: str, execution_id: str) -> str | None:
        """Read the bounded failure message of a Dispatch from the event ledger."""
        for event in self.repository.list_events(execution_id):
            if (
                event.type is EventType.EXECUTION_DISPATCH_FAILED
                and event.data.get("dispatch_id") == dispatch_id
            ):
                return event.data.get("error")
        return None

    def observe_projection(self, execution_id: str, projection: ExecutionProjection) -> Execution:
        current = self.repository.get_execution(execution_id)
        if not current.projection.terminal and projection.terminal:
            raise FinalizationRequired(
                f"first terminal observation for {execution_id} requires apply_finalization()"
            )
        self._validate_projection_transition(execution_id, current.projection, projection)
        if projection.observed_at < current.projection.observed_at:
            return current
        # ``observed_at`` is freshness evidence, not a new cross-system fact.
        # Avoid turning every provider poll into a ledger event/version write.
        if self._same_projection_semantics(projection, current.projection):
            return current
        now = _now()
        # ended_at is write-once: an advisory-only update under the same
        # terminal outcome (freshness / native continuation) must not rewrite
        # the sealed terminal snapshot's end timestamp.
        changed = replace(
            current,
            projection=projection,
            started_at=current.started_at or (now if projection.phase is Phase.ACTIVE else None),
            ended_at=now if (projection.terminal and not current.projection.terminal) else current.ended_at,
        )
        event_type = EventType.EXECUTION_TERMINAL if projection.terminal else EventType.EXECUTION_PROJECTION_CHANGED
        return self.repository.update_projection(changed, expected_version=current.version, event=CoreEvent(_id("evt"), event_type, execution_id, now, {"phase": projection.phase.value, "freshness": projection.freshness.value}))

    def apply_finalization(self, request: ExecutionFinalizationRequest) -> FinalizationReceipt:
        """Validate and atomically commit the only first-terminal path."""
        if not isinstance(request, ExecutionFinalizationRequest):
            raise TypeError("apply_finalization requires ExecutionFinalizationRequest")
        execution = self.repository.get_execution(request.execution_id)
        if execution.projection.terminal:
            # Repository resolves the valid persisted replay; all other forms
            # are rejected without writes.
            digest = self._finalization_digest(request)
            return self.repository.finalize_execution(
                request.execution_id, request.terminal_projection,
                (), (), (), idempotency_key=request.idempotency_key,
                bundle_digest=digest, ended_at=execution.ended_at or _now(),
            )
        native = self._validated_refs(request.native_refs, "native_refs")
        output = self._validated_refs(request.output_refs, "output_refs")
        observations = self._validated_resource_observations(
            request.execution_id, request.resource_observations
        )
        digest = self._finalization_digest(request, native, output, observations)
        return self.repository.finalize_execution(
            request.execution_id, request.terminal_projection, native, output,
            observations, idempotency_key=request.idempotency_key,
            bundle_digest=digest, ended_at=_now(),
        )

    @staticmethod
    def _validated_refs(refs, name):
        if not isinstance(refs, Sequence) or isinstance(refs, (str, bytes)):
            raise ValueError(f"{name} must be a sequence of Ref")
        for ref in refs:
            if not isinstance(ref, Ref) or not isinstance(ref.type, RefType):
                raise ValueError(f"{name} entries must be Ref values")
        return tuple(refs)

    def _finalization_digest(self, request, native=None, output=None, observations=None):
        native = tuple(request.native_refs if native is None else native)
        output = tuple(request.output_refs if output is None else output)
        observations = tuple(request.resource_observations if observations is None else observations)
        def ref_payload(ref):
            return {"type": ref.type.value, "provider": ref.provider, "native_id": ref.native_id, "uri": ref.uri, "metadata": dict(ref.metadata)}
        payload = {
            "execution_id": request.execution_id,
            "projection": {"phase": request.terminal_projection.phase.value, "outcome": request.terminal_projection.outcome.value, "resumable_now": request.terminal_projection.resumable_now, "freshness": request.terminal_projection.freshness.value, "observed_at": request.terminal_projection.observed_at.isoformat()},
            "native_refs": sorted((ref_payload(ref) for ref in native), key=lambda x: json.dumps(x, sort_keys=True)),
            "output_refs": sorted((ref_payload(ref) for ref in output), key=lambda x: json.dumps(x, sort_keys=True)),
            "resource_observations": sorted((self.repository.observation_digest(request.execution_id, item) for item in observations)),
        }
        return "sha256:" + hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _validate_projection_transition(
        execution_id: str,
        current: ExecutionProjection,
        incoming: ExecutionProjection,
    ) -> None:
        """Terminal phase is monotonic: history stays sealed once terminal.

        A terminal Execution never returns to active/unknown, and an existing
        terminal outcome may not change.  Re-delivery of the same terminal
        semantics stays idempotent (no event, no version write).
        """
        if not current.terminal:
            return
        if incoming.terminal and incoming.outcome is current.outcome:
            return
        raise InvalidProjectionTransition(
            f"execution {execution_id} is already terminal "
            f"({current.outcome.value if current.outcome else 'unknown'}); "
            f"refusing projection {incoming.phase.value}"
            + (f"/{incoming.outcome.value}" if incoming.outcome else "")
        )

    @staticmethod
    def _same_projection_semantics(left: ExecutionProjection, right: ExecutionProjection) -> bool:
        return (
            left.phase is right.phase
            and left.outcome is right.outcome
            and left.resumable_now is right.resumable_now
            and left.freshness is right.freshness
        )

    def apply_observation(
        self,
        execution_id: str,
        projection: ExecutionProjection,
        *,
        native_refs=(),
        output_refs=(),
        resource_states=(),
        resource_observations=(),
    ) -> Execution:
        """Persist material projection and typed references from any provider.

        ``resource_states`` is the legacy free-string channel (deprecated);
        ``resource_observations`` carries typed ResourceObservation values.
        The full bundle is validated before any write; the typed observations
        are appended through the repository's single-transaction batch
        method.  The bundle as a whole (projection + refs + legacy states +
        typed observations) is not committed as one transaction.
        """
        if projection.terminal:
            current = self.repository.get_execution(execution_id)
            if not current.projection.terminal:
                raise FinalizationRequired(
                    f"first terminal observation for {execution_id} requires apply_finalization()"
                )
            self._validate_projection_transition(execution_id, current.projection, projection)
            if self._same_projection_semantics(current.projection, projection) and not any((native_refs, output_refs, resource_states, resource_observations)):
                return current
            raise FinalizationConflict(
                f"terminal Execution {execution_id} is sealed; use the late evidence API"
            )
        resource_entries = self._validate_resource_states(execution_id, resource_states)
        typed = self._validated_resource_observations(execution_id, resource_observations)
        changed = self.observe_projection(execution_id, projection)
        for ref in native_refs:
            self.repository.attach_ref(execution_id, RefRelation.NATIVE, ref, CoreEvent(_id("evt"), EventType.NATIVE_REF_DISCOVERED, execution_id, _now(), {"type": ref.type.value}))
        for ref in output_refs:
            self.repository.attach_ref(execution_id, RefRelation.OUTPUT, ref, CoreEvent(_id("evt"), EventType.REF_ATTACHED, execution_id, _now(), {"type": ref.type.value}))
        for ref, state, evidence in resource_entries:
            self.repository.record_resource_state(
                execution_id, ref, state, evidence, occurred_at=_now()
            )
        if typed:
            self.repository.record_resource_observations(
                execution_id, typed, recorded_at=_now()
            )
        return changed

    def record_resource_observations(
        self,
        execution_id: str,
        observations: Sequence[ResourceObservation],
    ) -> tuple[tuple[int, bool], ...]:
        """Append typed observations for one Execution's frozen inputs.

        Observations may arrive after the Execution is terminal (late
        evidence); they never change projection, outcome or Work lifecycle.
        The whole batch is validated before any write and persisted through
        the repository's single-transaction batch append.
        """
        typed = self._validated_resource_observations(execution_id, observations)
        if not typed:
            return ()
        return self.repository.record_resource_observations(
            execution_id, typed, recorded_at=_now()
        )

    def _validated_resource_observations(
        self, execution_id: str, observations
    ) -> tuple[ResourceObservation, ...]:
        if not isinstance(observations, Sequence) or isinstance(observations, (str, bytes)):
            raise ValueError(
                "resource_observations must be a sequence of ResourceObservation"
            )
        frozen = {
            (contract_id, _ref_identity(ref)): ref
            for contract_id, ref in self.repository.list_input_refs(execution_id)
        }
        result: list[ResourceObservation] = []
        for observation in observations:
            if not isinstance(observation, ResourceObservation):
                raise ValueError(
                    "resource_observations entries must be ResourceObservation values"
                )
            if (observation.contract_id, _ref_identity(observation.ref)) not in frozen:
                raise ValueError(
                    "resource observation does not address a frozen INPUT "
                    f"association: {execution_id}"
                )
            result.append(observation)
        return tuple(result)

    def _validate_resource_states(self, execution_id: str, resource_states):
        frozen = {
            (
                ref.type,
                ref.provider,
                ref.native_id,
                ref.uri,
                tuple(sorted(ref.metadata.items())),
            )
            for _, ref in self.repository.list_input_refs(execution_id)
        }
        result = []
        for item in resource_states:
            if not isinstance(item, (tuple, list)) or len(item) not in {2, 3}:
                raise ValueError(
                    "resource_states entries must be (Ref, state[, ArtifactRef])"
                )
            ref, state = item[0], item[1]
            evidence = item[2] if len(item) == 3 else None
            if not isinstance(ref, Ref):
                raise ValueError("resource observation requires a Ref")
            if not isinstance(state, str) or not state.strip():
                raise ValueError("resource_state must be a non-empty string")
            if len(state.strip()) > 256:
                raise ValueError("resource_state exceeds 256 characters")
            if evidence is not None and (
                not isinstance(evidence, Ref) or evidence.type is not RefType.ARTIFACT
            ):
                raise ValueError("resource evidence must be an ArtifactRef")
            identity = (
                ref.type,
                ref.provider,
                ref.native_id,
                ref.uri,
                tuple(sorted(ref.metadata.items())),
            )
            if identity not in frozen:
                raise ValueError(
                    f"resource observation is not a fixed INPUT Ref: {execution_id}"
                )
            result.append((ref, state, evidence))
        return tuple(result)
