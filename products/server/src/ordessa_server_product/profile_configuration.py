"""Product composition of Profile's port and domain-owned model resolution.

No native fields or brand switching strategy live here. Harness supplies the
application service; ModelProvider resolves business references. Every call
uses a backend-registered SessionRef and a current, independently read owner.
"""
from dataclasses import replace
from threading import RLock

from ordessa_profile.errors import ProfileError
from ordessa_profile.harness_port_adapter import HarnessApiConfigPort
from ordessa_profile.contracts import ApplyConfirmed, ApplyRejected, ApplyUnknown, PlanResult, PlannedItem, ReconcileOutcome
from ordessa_harness_api import ErrorCode


class NativeProfileConfigPort:
    native_turn_application = True

    def __init__(self, sessions, *, service_factory, resolver_factory, supported_harnesses=None,
                 restoration_service=None, credential_resolver=None):
        if supported_harnesses is not None and (
            not isinstance(supported_harnesses, tuple) or not supported_harnesses
            or any(type(identity) is not str or not identity or identity.strip() != identity
                   for identity in supported_harnesses)
            or len(set(supported_harnesses)) != len(supported_harnesses)):
            raise ValueError('Explicit supported production Harness routes required')
        self.supported_harnesses = frozenset(supported_harnesses or ())
        self.sessions = sessions
        self.service_factory, self.resolver_factory = service_factory, resolver_factory
        self._ports, self._plans = {}, {}
        self.restoration_service, self.credential_resolver = restoration_service, credential_resolver
        self._transitions = {}
        self._lock = RLock()

    def complete_restoration(self, ref, ticket):
        """Explicit trusted renewal, never automatic repair of arbitrary drift.

        Restore evidence is separate from a C4 application receipt. A fresh
        application must be planned against the new instance before prompting.
        """
        with self._lock:
            cached = self._ports.get(ref.session_uid)
            binding = self.sessions.require_registered(ref)
            if cached is not None and cached[0] != binding.snapshot.target:
                raise ProfileError('SWITCH_BLOCKED', 'Restoration does not match cached owner', status=409)
            result = self.sessions.complete_restoration(ref, ticket)
            if cached is not None and cached[0] not in (result.previous_target, result.snapshot.target):
                raise ProfileError('SWITCH_BLOCKED', 'Restoration does not match cached owner', status=409)
            if cached is not None and cached[0] == result.previous_target:
                self._ports.pop(ref.session_uid)
            for key, saved in tuple(self._plans.items()):
                if saved[0] == ref:
                    self._plans.pop(key)
            return result

    def _port(self, ref):
        binding = self.sessions.resolve(ref)
        if ref.harness_id not in self.supported_harnesses:
            raise ProfileError("SWITCH_BLOCKED", "Native application not yet available for this Harness", status=409)
        cached = self._ports.get(ref.session_uid)
        if cached is not None:
            if cached[0] != binding.snapshot.target:
                raise ProfileError("SWITCH_BLOCKED", "Native owner generation changed", status=409)
            return cached[1]
        try:
            service, native = self.service_factory(binding.snapshot.target)
        except Exception as exc:
            raise ProfileError("APPLICATION_PORT_ABSENT", "Verified native application unavailable", status=409) from exc
        port = HarnessApiConfigPort(service, owner_application=True,
            target_resolver=lambda target_ref: self.sessions.resolve(target_ref).snapshot.target,
            revision_provider=lambda target_ref: native.capture(
                self.sessions.resolve(target_ref).snapshot.target).before_revision)
        self._ports[ref.session_uid] = (binding.snapshot.target, port)
        return port

    def _complete_transition(self, ref, result, native_plan):
        if getattr(native_plan, 'mode', 'restart-resume') != 'live-update':
            return self.complete_restoration(ref, result.ticket)
        current = self.sessions.resolve(ref).snapshot
        observed = result.restored.snapshot
        if (result.ticket is not None or current.target != native_plan.before.target
            or observed.target != current.target or observed.owner is not current.owner
            or current.owner is not native_plan.before.owner
            or observed.native_generation != current.native_generation
            or current.native_generation != native_plan.expected_generation):
            raise ProfileError('SWITCH_BLOCKED', 'Live transition changed the session owner', status=409)
        self._ports.pop(ref.session_uid, None)
        for key, saved in tuple(self._plans.items()):
            if saved[0] == ref:
                self._plans.pop(key)

    def inspect(self, ref):
        with self._lock:
            return self._port(ref).inspect(ref)

    def _resolve(self, ref, desired):
        if (len(desired) != 1 or desired[0].facet_id != "assets.model-provider"
            or desired[0].item_id != "choice" or desired[0].op != "set"):
            raise ProfileError("SWITCH_BLOCKED", "This native route requires one supported model choice", status=409)
        try:
            resolved = self.resolver_factory().resolve(desired[0].value, harness_id=ref.harness_id)
        except Exception as exc:
            raise ProfileError("SWITCH_BLOCKED", "Current model choice cannot be resolved", status=409) from exc
        return (replace(desired[0], value=resolved.payload),), resolved.revisions

    def plan(self, ref, desired, operation_key):
        with self._lock:
            existing = self._transitions.get(operation_key)
            if existing is not None:
                if existing['plan'].session_ref != ref or existing['desired'] != desired:
                    raise ProfileError('SWITCH_BLOCKED', 'Native transition key already bound', status=409)
                return existing['plan']
            port = self._port(ref)
            mapped, revisions = self._resolve(ref, desired)
            plan = port.plan(ref, mapped, operation_key)
            if (plan.blocked and self.restoration_service is not None and callable(self.credential_resolver)
                and plan.items and all(item.reason.startswith(ErrorCode.CAPABILITY_UNSUPPORTED.value + ':')
                                       for item in plan.items)):
                # Harness decides whether this desired configuration has an
                # installed restoration route. No brand/dialect interpretation.
                try:
                    snapshot = self.sessions.resolve(ref).snapshot
                    native_plan = self.restoration_service.prepare(snapshot.target, mapped[0].value,
                        operation_key=operation_key,
                        credential=self.credential_resolver(ref, mapped[0].value))
                except Exception:
                    return plan  # typed blocked, zero restoration effect
                mode = getattr(native_plan, 'mode', 'restart-resume')
                if mode not in ('live-update', 'restart-resume'):
                    return plan
                plan = PlanResult(ref, operation_key, mode,
                    items=(PlannedItem(mapped[0].facet_id, mapped[0].item_id, mapped[0].op, mode),),
                    plan_digest=native_plan.input_digest,
                    fence={'restoration_operation': native_plan.operation_id})
                if len(self._transitions) >= 4096:
                    raise ProfileError('SWITCH_BLOCKED', 'Native transition capacity exhausted', status=409)
                self._transitions[operation_key] = dict(native_plan=native_plan, plan=plan, desired=desired,
                    mapped=mapped, revisions=revisions, started=False, fresh_port=None, fresh_plan=None,
                    result=None)
            if not plan.blocked:
                if len(self._plans) >= 4096:
                    raise ProfileError("SWITCH_BLOCKED", "Native plan capacity exhausted", status=409)
                self._plans[operation_key] = (ref, desired, mapped, revisions, plan)
            return plan

    def apply(self, plan, desired):
        with self._lock:
            transition = self._transitions.get(plan.operation_key)
            if transition is not None:
                return self._apply_transition(plan, desired, transition)
            saved = self._plans.get(plan.operation_key)
            if saved is None or saved[0] != plan.session_ref or saved[1] != desired or saved[4] != plan:
                raise ProfileError("SWITCH_BLOCKED", "Unknown or changed prepared Profile plan", status=409)
            mapped, revisions = self._resolve(plan.session_ref, desired)
            if mapped != saved[2] or revisions != saved[3]:
                raise ProfileError("SWITCH_BLOCKED", "Model catalogue changed after planning", status=409)
            return self._port(plan.session_ref).apply(plan, mapped)

    def _apply_transition(self, plan, desired, saved):
        if saved['plan'] != plan or saved['desired'] != desired:
            raise ProfileError('SWITCH_BLOCKED', 'Unknown or changed native transition', status=409)
        if saved['started']:
            if isinstance(saved['result'], ApplyRejected):
                return saved['result']
            outcome = self.reconcile(plan.operation_key, plan.session_ref)
            return (ApplyConfirmed('confirmed', outcome.receipt) if outcome.state == 'confirmed-current'
                    else ApplyUnknown('unknown', outcome.reason))
        mapped, revisions = self._resolve(plan.session_ref, desired)
        if mapped != saved['mapped'] or revisions != saved['revisions']:
            raise ProfileError('SWITCH_BLOCKED', 'Model catalogue changed after planning', status=409)
        # The Profile service has durably marked this operation applying before
        # entering this seam. Query/replay below never resumes either stage.
        saved['started'] = True
        try:
            result = self.restoration_service.execute(saved['native_plan'], mapped[0].value,
                credential=self.credential_resolver(plan.session_ref, mapped[0].value))
            if result.state == 'refused':
                # The native refused before any effect existed (typed evidence
                # over the pinned owner). Terminal honest rejection, not a
                # sticky unknown: nothing was applied and nothing is replayed.
                saved['result'] = ApplyRejected('rejected-unchanged',
                    getattr(result, 'reason', None) or 'Native provider restoration was refused')
                return saved['result']
            if result.state != 'observed':
                # Whitelisted nominal condition code from the Harness service;
                # never a raw RPC payload, digest or credential value.
                return ApplyUnknown('unknown', getattr(result, 'reason', None)
                    or 'Native provider restoration is unproven')
            self._complete_transition(plan.session_ref, result, saved['native_plan'])
            current, current_revisions = self._resolve(plan.session_ref, desired)
            if current != mapped or current_revisions != revisions:
                return ApplyUnknown('unknown', 'Model catalogue changed during restoration')
            # Never recycle the old C4 plan or receipt. Re-plan against the
            # observed owner/catalogue, including same-generation live updates.
            fresh_port = self._port(plan.session_ref)
            fresh_plan = fresh_port.plan(plan.session_ref, current, plan.operation_key)
            saved['fresh_port'], saved['fresh_plan'] = fresh_port, fresh_plan
            if fresh_plan.blocked:
                return ApplyUnknown('unknown', 'Restored configuration application remains blocked')
            outcome = fresh_port.apply(fresh_plan, current)
            if isinstance(outcome, ApplyRejected):
                outcome = ApplyUnknown('unknown', 'Restored configuration application was refused')
            saved['result'] = outcome
            return outcome
        except Exception:
            if not self.restoration_service.attempted(saved['native_plan']):
                saved['result'] = ApplyRejected('rejected-unchanged', 'Native restoration preflight refused')
                return saved['result']
            return ApplyUnknown('unknown', 'Native transition or new configuration application is unproven')

    def reconcile(self, operation_key, ref):
        with self._lock:
            transition = self._transitions.get(operation_key)
            if transition is not None:
                if transition['plan'].session_ref != ref:
                    raise ProfileError('SWITCH_BLOCKED', 'Foreign native transition', status=409)
                if isinstance(transition['result'], ApplyRejected):
                    return ReconcileOutcome('rejected-unchanged', reason=transition['result'].reason)
                if transition['fresh_port'] is None:
                    # A recovered restoration is not permission to execute a
                    # previously unstarted C4 action from a read-only query.
                    if transition['started']:
                        try:
                            restored = self.restoration_service.query(transition['native_plan'])
                            if restored.state == 'observed':
                                self._complete_transition(ref, restored, transition['native_plan'])
                        except Exception:
                            pass
                    return ReconcileOutcome('unknown', reason='Configuration application is not confirmed; no effects replayed')
                try:
                    result = transition['fresh_port'].reconcile(operation_key, ref)
                    if result.state == 'confirmed-current':
                        return result
                except Exception:
                    pass
                return ReconcileOutcome('unknown', reason='New configuration application remains unproven')
            return self._port(ref).reconcile(operation_key, ref)
