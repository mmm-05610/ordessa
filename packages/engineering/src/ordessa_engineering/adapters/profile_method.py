"""Read selection policy from the original guarded immutable method manifest.

Profile selection precedes package authorization. This adapter supplies no
permission, run state or implicit model retry; an existing TrustedFlow supplies
its original gateway. The returned objects remain native Profile and Decision.
"""
from decision_runtime import PolicyRef

from ..application.contracts.errors import ApplicationError
from ..application.orchestration.profile_selection import (
    select_method_profile, validate_profile_selection_policy,
)
from ..domain.artifacts.method_binding import MethodRef
from ..methods.loading.parsing import parse_document
from .execution_profiles import (
    NativeProfileChoice, NativeProfileSelectionSource, NativeProfileUnitCreator,
)
from .persistence.sqlite.method_control import SQLiteMethodControl


def read_method_profile_selection_policy(methods, context, method_ref):
    """Return authored policy and its exact native Decision policy binding.

    Uses the original method guard and snapshot blob reader. This read must be
    made before opening a business UoW; the original snapshot reader rejects
    nested transactions. No wire policy or current/latest manifest is accepted.
    """
    if type(methods) is not SQLiteMethodControl or type(method_ref) is not MethodRef:
        raise ApplicationError('PROFILE_METHOD_AUTHORITY_UNAVAILABLE')
    with methods.guard_method(context, method_ref) as snapshot:
        raw = methods.snapshots.read_blob(snapshot.manifest_ref)
        manifest = parse_document(raw, snapshot.manifest_ref.media_type, 'method.yaml')
        metadata = manifest.get('metadata') if type(manifest) is dict else None
        policy = metadata.get('agent_profile_selection') if type(metadata) is dict else None
        policy = validate_profile_selection_policy(policy)
        # The snapshot digest binds all captured resources and compiler policy;
        # it never borrows the unrelated Engineering standard_profile_ref.
        ref = PolicyRef(method_ref.method_id, method_ref.release_version,
                        'sha256:' + method_ref.snapshot_digest.hex)
    return policy, ref


async def select_profile_for_method(context, method_ref, task, *, methods,
                                    candidates, gateway, request_id):
    """Choose a fixed ref using an existing TrustedFlow's original gateway.

    Immutable policy is read before the await; no library lock is held while
    Decision runs. Current method enablement is checked again before returning.
    Original package/action and Unit authorization remain separate admissions.
    """
    policy, policy_ref = read_method_profile_selection_policy(methods, context, method_ref)
    selected, answer = await select_method_profile(task, policy=policy,
        candidates=candidates, choice=NativeProfileChoice(gateway, policy_ref),
        request_id=request_id)
    with methods.guard_method(context, method_ref):
        pass
    return selected, answer


class MethodExecutionSelection:
    """Transparent method-bound composition; no selected-result/run authority.

    The process composition supplies existing owners once. Ordinary callers
    select with their admitted context and task, then pass an existing exact
    Unit authorization to create. This class creates neither permission nor a
    Decision run/provider, and retains no second durable or mutable run state.
    """
    def __init__(self, methods, method_ref, candidates, units):
        self._methods, self._method_ref = methods, method_ref
        self._candidates, self._units = candidates, units

    def policy_ref(self, context):
        """Exact native policy pin for the existing DecisionServices assembly."""
        return read_method_profile_selection_policy(
            self._methods, context, self._method_ref)[1]

    async def select(self, context, task, *, gateway, request_id):
        return await select_profile_for_method(context, self._method_ref, task,
            methods=self._methods, candidates=self._candidates,
            gateway=gateway, request_id=request_id)

    def create(self, context, profile_ref, authorization):
        # Method preflight is released before native creation. Actual Unit
        # authorization and later package/dispatch write-cut guards remain
        # their original owners; no through-COMMIT claim is made here.
        with self._methods.guard_method(context, self._method_ref):
            self._candidates.validate(profile_ref)
        return self._units.create(profile_ref, authorization)


def build_method_execution_selection(methods, profiles, *, method_ref,
        allowed_revisions, unit_manager, agent_id, environment_reference):
    """Stable composition entry over the same original selected public owners."""
    if type(methods) is not SQLiteMethodControl or type(method_ref) is not MethodRef:
        raise ApplicationError('PROFILE_METHOD_AUTHORITY_UNAVAILABLE')
    return MethodExecutionSelection(methods, method_ref,
        NativeProfileSelectionSource(profiles, allowed_revisions=allowed_revisions),
        NativeProfileUnitCreator(unit_manager, agent_id=agent_id,
                                environment_reference=environment_reference))


__all__ = ['read_method_profile_selection_policy', 'select_profile_for_method',
           'build_method_execution_selection', 'MethodExecutionSelection']
