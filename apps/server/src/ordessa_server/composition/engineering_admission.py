"""Compose original Engineering authorities from explicit trusted owner ports.

This assembly does not select a method, issue permissions, authenticate a human,
or turn an unbound JEV terminal into a formal review. Owner factories are local
deployment inputs and are never read from wire parameters.
"""
from dataclasses import dataclass

from ordessa_engineering.adapters.confirmation.conversation import ConversationAdmission
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.reviews.admission import EngineeringReviewAdmission
from ordessa_engineering.application.usecases.support.methods import MethodUseCases
from ordessa_engineering.application.assembly import build_submission_acceptance_admission
from ordessa_system_access_bindings.engineering_wire import EngineeringApplicationPorts

from .conversation_attestor import RegisteredMainAgentAttestor
from .engineering_intent_assembly import build_engineering_intent_admission_router


@dataclass(frozen=True)
class EngineeringAdmissionAssembly:
    methods: MethodUseCases
    method_control: SQLiteMethodControl
    application_ports: EngineeringApplicationPorts


def assemble_engineering_admission(factory, access, scope, *, management,
        bindings, reviewer_source, policy_bytes, policy_ref,
        intent_guard_factory=None, proposal_control_admission=None, review_control=None,
        conversation_locator=None, presentation_binding=None, method_control=None, blobs=None,
        review_admission=None):
    """Use one original UoW/library and reject absent production authorities.

    intent_guard_factory(method_control, bindings) must be the Engineering-owned
    complete intent/requirements closure. A method pin alone is insufficient.
    Method adoption remains a separate authorized MethodUseCases call with CAS;
    merely creating this assembly never adopts or enables a method.
    """
    if management is None:
        raise ApplicationError("METHOD_MANAGEMENT_UNAVAILABLE")
    if bindings is None:
        raise ApplicationError("METHOD_TARGET_BINDINGS_UNAVAILABLE")
    if reviewer_source is None:
        raise ApplicationError("REVIEW_SOURCE_AUTHORITY_UNAVAILABLE")
    if presentation_binding is not None and conversation_locator is None:
        raise ApplicationError('CONFIRMATION_AUTHORITY_UNAVAILABLE')
    controls = method_control
    if controls is None:
        controls = SQLiteMethodControl(factory, SQLiteSnapshotStore(factory.library))
    elif getattr(controls, 'factory', None) is not factory:
        raise ApplicationError('METHOD_AUTHORITY_MISMATCH')
    snapshots = controls.snapshots
    if blobs is None:
        blobs = SQLiteBlobStore(factory.library)
    elif getattr(blobs, 'authority_id', None) != factory.authority_id:
        raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
    methods = MethodUseCases(factory, access, snapshots, management)
    reviews = review_admission
    if reviews is None:
        reviews = EngineeringReviewAdmission(factory, controls, bindings, reviewer_source)
    elif (getattr(reviews, 'factory', None) is not factory
            or getattr(reviews, 'methods', None) is not controls
            or getattr(reviews, 'bindings', None) is not bindings
            or getattr(reviews, 'source', None) is not reviewer_source):
        raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
    # Construct acceptance once through Engineering's public assembly API.
    # The same original object is used by the intent router and exposed to the
    # wire for report/submission assembly to preserve by identity.
    acceptance = build_submission_acceptance_admission(
        factory, method_control=controls, bindings=bindings)
    intent_router = build_engineering_intent_admission_router(
        factory, method_control=controls, bindings=bindings,
        acceptance_admission=acceptance)
    if intent_guard_factory is None:
        intent_guard = intent_router.guard_intent
    else:
        # An explicitly selected trusted deployment override remains supported.
        intent_guard = intent_guard_factory(controls, bindings)
    if intent_guard is None:
        raise ApplicationError("CONFIRMATION_AUTHORITY_UNAVAILABLE")
    attestor = RegisteredMainAgentAttestor(access, scope=scope,
        principal_id=access.authority.principal_id, selected_policy_ref=policy_ref)
    conversation = ConversationAdmission(policy_bytes, policy_ref,
        attestor_guard=attestor.guard, intent_guard=intent_guard)
    if conversation_locator is not None:
        from .engineering_chat_confirmation import MainAgentChatConfirmation
        conversation = MainAgentChatConfirmation(factory, conversation,
            conversation_locator=conversation_locator, presentation_binding=presentation_binding)
    ports = EngineeringApplicationPorts(
        proposal_control_admission=proposal_control_admission,
        review_admission=reviews, review_control=review_control,
        blobs=blobs, conversation_admission=conversation,
        acceptance_admission=acceptance)
    return EngineeringAdmissionAssembly(methods, controls, ports)
