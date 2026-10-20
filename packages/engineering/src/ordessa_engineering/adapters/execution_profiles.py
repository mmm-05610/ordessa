"""Adapters over the original Execution Profile, Decision, and Unit APIs.

These adapters preserve native immutable references and delegate authority to
their original owners. They do not infer roles from Profile metadata or create
authorization.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from itertools import islice
from dataclasses import dataclass, field
from typing import Any

from decision_runtime import DecisionAnswer, DecisionQuestion, PolicyRef
from ordessa_execution_agents.profiles import (
    ProfileRevisionRef,
    ProfileService,
    encode_content,
)
from ordessa_infrastructure.encoding.immutable_json import sealed_mapping, safe_json

from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError


_MAX_DESCRIPTION_BYTES = 16 * 1024
_MAX_OPTION_ID_BYTES = 512


@dataclass(frozen=True)
class ProfileTaskInput:
    """Finite immutable Engineering task data, never a Decision permission."""
    task_id: str
    task_revision: str
    goal: str
    inputs: tuple = ()
    boundaries: tuple = ()
    acceptance_criteria: tuple = ()
    context_refs: tuple = ()
    continuation_ref: object = None
    _snapshot: Mapping = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        for value in (self.task_id, self.task_revision):
            if (type(value) is not str or not value or len(value) > 256
                    or value.strip() != value or any(ord(char) < 32 for char in value)):
                raise EngineeringError("native_task_input_required")
        if type(self.goal) is not str:
            raise EngineeringError("native_task_input_required")
        value = {name: getattr(self, name) for name in (
            'task_id', 'task_revision', 'goal', 'inputs', 'boundaries',
            'acceptance_criteria', 'context_refs', 'continuation_ref')}
        object.__setattr__(self, '_snapshot', sealed_mapping(value, max_bytes=262144))

    def to_dict(self):
        return json.loads(safe_json(self._snapshot, max_bytes=262144))


def _ref_key(ref: ProfileRevisionRef) -> str:
    """Stable finite option id derived only from the complete native ref."""
    return f"{ref.profile_id}@{ref.revision}:{ref.digest}"


class NativeProfileSelectionSource:
    """Resolve a complete, explicitly method-authorized set of native refs.

    `allowed_revisions` must come from the trusted method host. The source
    rechecks that set against the original ProfileService on every read.
    """

    def __init__(self, profiles: ProfileService, *, allowed_revisions: Iterable[ProfileRevisionRef]):
        if type(profiles) is not ProfileService:
            raise EngineeringError("original_profile_service_required")
        try:
            refs = tuple(islice(iter(allowed_revisions), 65))
        except TypeError:
            raise EngineeringError("profile_candidate_set_unavailable") from None
        if len(refs) > 64:
            raise EngineeringError("profile_candidate_set_over_limit")
        if not refs or any(type(ref) is not ProfileRevisionRef for ref in refs):
            raise EngineeringError("profile_candidate_set_unavailable")
        if len(set(refs)) != len(refs):
            raise EngineeringError("profile_candidate_set_ambiguous")
        namespace = profiles.environment_namespace
        if any(ref.environment_namespace != namespace for ref in refs):
            raise EngineeringError("profile_candidate_environment_mismatch")
        keys = tuple(_ref_key(ref) for ref in refs)
        if len(set(keys)) != len(keys) or any(len(key.encode("utf-8")) > _MAX_OPTION_ID_BYTES for key in keys):
            raise EngineeringError("profile_candidate_set_ambiguous")
        self._profiles = profiles
        self._allowed = refs

    def _revision(self, ref: ProfileRevisionRef):
        if type(ref) is not ProfileRevisionRef or ref not in self._allowed:
            raise EngineeringError("profile_ref_not_method_allowed")
        if ref.environment_namespace != self._profiles.environment_namespace:
            raise EngineeringError("profile_candidate_environment_mismatch")
        # Every candidate must belong to an extant, unarchived management
        # Profile. This mirrors Unit's fixed-profile resolver; immutable
        # snapshot refs without a management Profile are not selectable here.
        # get applies the original per-Profile ACL without walking the catalog.
        profile = self._profiles.get(ref.profile_id)
        if profile.archived_at is not None:
            raise EngineeringError("profile_candidate_set_unavailable")
        revision = self._profiles.get_revision(ref)
        if type(revision.ref) is not ProfileRevisionRef or revision.ref != ref:
            raise EngineeringError("profile_revision_identity_mismatch")
        encoded = encode_content(revision.content)
        description = json.dumps(encoded, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if len(description.encode("utf-8")) > _MAX_DESCRIPTION_BYTES:
            raise EngineeringError("profile_description_too_large")
        return revision, description

    def candidates(self, *, max_candidates: int) -> Mapping[str, tuple[object, str]]:
        if type(max_candidates) is not int or not 1 <= max_candidates <= 64:
            raise EngineeringError("profile_candidate_limit_invalid")
        if len(self._allowed) > max_candidates:
            raise EngineeringError("profile_candidate_set_over_limit")
        candidates: dict[str, tuple[object, str]] = {}
        # Do not truncate. A failure on any configured entry means the host's
        # supposedly complete method-bound set cannot be established.
        for ref in self._allowed:
            _revision, description = self._revision(ref)
            candidates[_ref_key(ref)] = (ref, description)
        return candidates

    def validate(self, profile_ref: object) -> object:
        if type(profile_ref) is not ProfileRevisionRef or profile_ref not in self._allowed:
            raise EngineeringError("profile_ref_not_method_allowed")
        self._revision(profile_ref)
        return profile_ref


class NativeProfileChoice:
    """Build one native finite Choice question and call the injected gateway once."""

    def __init__(self, gateway: Any, policy_ref: PolicyRef):
        if not callable(getattr(gateway, "decide", None)) or type(policy_ref) is not PolicyRef:
            raise EngineeringError("original_decision_gateway_required")
        self._gateway = gateway
        self._policy_ref = policy_ref

    async def choose(
        self,
        task: object,
        *,
        request_id: str,
        question_id: str,
        question_text: str,
        options: Mapping[str, str],
    ) -> object:
        if type(task) is not ProfileTaskInput:
            raise EngineeringError("native_task_input_required")
        if not isinstance(request_id, str) or not request_id.strip():
            raise EngineeringError("decision_request_id_required")
        if not isinstance(options, Mapping) or not 2 <= len(options) <= 65:
            raise EngineeringError("profile_choice_options_required")
        bounded_options: dict[str, str] = {}
        for option_id, description in options.items():
            if (type(option_id) is not str or not option_id or len(option_id.encode("utf-8")) > _MAX_OPTION_ID_BYTES
                    or type(description) is not str or not description
                    or len(description.encode("utf-8")) > _MAX_DESCRIPTION_BYTES):
                raise EngineeringError("profile_choice_option_invalid")
            bounded_options[option_id] = description
        question = DecisionQuestion(
            question_id=question_id,
            version="1",
            kind="choice",
            bounded_state={"task": task.to_dict(), "request_id": request_id},
            question_text=question_text,
            options=bounded_options,
            allowed_answer_ids=tuple(bounded_options),
            policy_ref=self._policy_ref,
        )
        answer = await self._gateway.decide(question)
        if type(answer) is not DecisionAnswer or answer.question_id != question.question_id or answer.kind != "choice":
            raise EngineeringError("native_decision_answer_mismatch")
        # Preserve the exact native answer, receipt, and usage evidence. The
        # orchestration owner handles ties, decline, and option membership.
        return answer


class NativeProfileUnitCreator:
    """Create through the original public UnitManager using the fixed ref."""

    def __init__(self, manager: Any, *, agent_id: str, environment_reference: Mapping):
        from ordessa_units.api import UnitManager

        if type(manager) is not UnitManager:
            raise EngineeringError("original_public_unit_manager_required")
        if not isinstance(agent_id, str) or not agent_id.strip() or not isinstance(environment_reference, Mapping):
            raise EngineeringError("fixed_unit_context_required")
        self._manager = manager
        self._agent_id = agent_id
        # Use the same canonical immutable JSON conversion as UnitSpec now,
        # so later mutation of the caller's mapping cannot alter this context.
        self._environment_reference = sealed_mapping(environment_reference)

    def create(self, profile_ref: object, authorization: Any) -> object:
        from ordessa_units.api import UnitSpec

        if type(profile_ref) is not ProfileRevisionRef:
            raise EngineeringError("fixed_profile_revision_required")
        return self._manager.create(
            UnitSpec(self._agent_id, profile_ref, self._environment_reference),
            authorization,
        )


class NativeProfileAgentCreator:
    """Delegate one fixed Profile start to the original current Agent owner.

    The process root supplies an already bound endpoint, the exact start-request
    factory and original invocation resolver. Neither profile choice nor an
    opaque authorization value is converted into permission by this adapter.
    Stable request identity and replay/UNKNOWN handling remain their owners'.
    """

    def __init__(self, manager, *, endpoint, request_factory, invocation_resolver):
        from ordessa_execution_agents.public import AgentManager
        from ordessa_execution_agents.sdk.endpoint import BoundEndpoint

        if type(manager) is not AgentManager:
            raise EngineeringError("original_public_agent_manager_required")
        if (type(endpoint) is not BoundEndpoint or not callable(request_factory)
                or not callable(invocation_resolver)):
            raise EngineeringError("fixed_agent_context_required")
        self._manager = manager
        self._endpoint = endpoint
        self._request_factory = request_factory
        self._invocation_resolver = invocation_resolver

    async def create(self, profile_ref: object, authorization: Any) -> object:
        from ordessa_execution_agents.public import AgentStartRequest

        if type(profile_ref) is not ProfileRevisionRef:
            raise EngineeringError("fixed_profile_revision_required")
        request = self._request_factory(profile_ref, self._endpoint.ref, authorization)
        if (type(request) is not AgentStartRequest
                or request.profile_revision_ref != profile_ref
                or request.endpoint_ref != self._endpoint.ref):
            raise EngineeringError("fixed_agent_start_request_required")
        invocation = self._invocation_resolver(authorization)
        # No retry or key rewrite: original Manager admission and durable ledger
        # own both a fresh start and its completed/UNKNOWN replay.
        return await self._manager.start(request, self._endpoint, invocation)


__all__ = [
    "ProfileTaskInput",
    "NativeProfileSelectionSource",
    "NativeProfileChoice",
    "NativeProfileUnitCreator",
    "NativeProfileAgentCreator",
]
