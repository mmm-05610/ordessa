"""Resolve explicit persisted user selections through their original owners.

This is a data reader for an already configured product. It does not create a
Profile, Environment, proposal, material, Unit, grant, credential, or process.
Launch paths are supplied separately by trusted product policy; they are never
accepted from the user document.
"""
from dataclasses import dataclass
from collections.abc import Mapping

from ordessa_infrastructure.encoding import decode_json
from ordessa_engineering.adapters.review_sources import (
    ConfiguredReviewPhase, ConfiguredMaterialSubmission, SQLiteReviewBindings,
)
from ordessa_engineering.application.contracts.commands import CommandKey
from ordessa_engineering.domain.artifacts.ref_codec import decode_artifact_ref
from ordessa_engineering.domain.changes.ref_codec import decode_proposal_ref
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.reviews.target_codec import decode_subject_ref
from ordessa_engineering.domain.reviews.refs import SubmissionRef
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_execution_agents.profiles import ProfileRevisionRef, ProfileService, decode_revision_ref
from ordessa_environments import EnvironmentManager
from ordessa_units.admission.context import UnitAdmissionContext
from ordessa_units.public import composed_profile_service
from ordessa_units.assembly import LocalUnitOwner
from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from ordessa_server.composition.pi_selection import PiExecutionSelection


class ProductUserConfigurationError(ValueError):
    """The explicit selection is malformed, stale, or differs from its owners."""


@dataclass(frozen=True)
class ResolvedProductUserSelection:
    pi_selection: PiExecutionSelection
    proposal_ref: ProposalRef | None
    phases: tuple[ConfiguredReviewPhase, ...] | None
    material_submissions: tuple[ConfiguredMaterialSubmission, ...]


_ROOT_KEYS = {"version", "piSelection", "engineering"}
_PI_KEYS = {"agentId", "profileRevision", "environment", "model"}
_ENV_KEYS = {"id", "provider", "isolation", "sharing"}
_MODEL_KEYS = {"declarationId", "provider", "model"}
_ENG_KEYS = {"proposalRef", "phases", "materialSubmissions"}
_PHASE_KEYS = {"phaseKey", "eligibleReviewerRoles", "materialInputs", "workflowNodeId",
               "submissionRef", "reviewPurpose"}
_MATERIAL_KEYS = {"revisionRef", "commandKey"}
_COMMAND_KEYS = {"realm_id", "principal_id", "request_id"}
_LAUNCH_KEYS = {"bridge_executable", "bridge_sha256", "pi_executable", "credential_source"}


def _object(value, keys, label):
    if type(value) is not dict or set(value) != keys:
        raise ProductUserConfigurationError(f"invalid {label} fields")
    return value


def _text(value, label):
    if type(value) is not str or not value or value.strip() != value:
        raise ProductUserConfigurationError(f"invalid {label}")
    return value


def _same_scope(value, scope):
    return (getattr(value, "realm_id", None), getattr(value, "project_id", None)) == (
        scope.realm_id, scope.project_id)


def _resolve_native_selection(document, *, profile_service, environments,
                              environment_namespace, model_catalogue, trusted_launch):
    if type(model_catalogue) is not tuple or not model_catalogue:
        raise ProductUserConfigurationError("actual selected-owner model catalogue required")
    launch = _object(trusted_launch, _LAUNCH_KEYS, "trusted launch policy")
    for key, value in launch.items():
        _text(value, key)
    if (len(launch["bridge_sha256"]) != 64
            or any(ch not in "0123456789abcdef" for ch in launch["bridge_sha256"])):
        raise ProductUserConfigurationError("invalid trusted bridge digest")

    if type(document) in (str, bytes):
        raw_size = len(document.encode("utf-8") if type(document) is str else document)
        if raw_size > 1_048_576:
            raise ProductUserConfigurationError("configuration exceeds the 1 MiB limit")
        try:
            document = decode_json(document)
        except (ValueError, TypeError, UnicodeDecodeError):
            raise ProductUserConfigurationError("invalid configuration JSON") from None
    root = _object(document, _ROOT_KEYS, "configuration")
    if type(root["version"]) is not int or root["version"] != 1:
        raise ProductUserConfigurationError("unsupported configuration version")
    pi = _object(root["piSelection"], _PI_KEYS, "Pi selection")
    env = _object(pi["environment"], _ENV_KEYS, "Environment selection")
    model = _object(pi["model"], _MODEL_KEYS, "model selection")
    if type(env["sharing"]) is not bool:
        raise ProductUserConfigurationError("sharing must be an explicit boolean")
    profile_ref = decode_revision_ref(pi["profileRevision"])
    if type(profile_ref) is not ProfileRevisionRef:
        raise ProductUserConfigurationError("fixed Profile revision required")
    if profile_ref.environment_namespace != environment_namespace:
        raise ProductUserConfigurationError("Profile belongs to another original Environment")
    revision = profile_service.get_revision(profile_ref)
    if revision.ref != profile_ref:
        raise ProductUserConfigurationError("persisted Profile revision differs")
    declarations = tuple(d for d in revision.content.declarations
                         if d.declaration_id == _text(model["declarationId"], "model declaration"))
    if len(declarations) != 1:
        raise ProductUserConfigurationError("selected Profile model declaration is absent or ambiguous")
    declaration = declarations[0]
    payload = declaration.payload
    if (declaration.configuration_kind != "assets.model-provider"
            or declaration.schema_version != "1" or declaration.action != "value"
            or not isinstance(payload, Mapping)
            or payload.get("provider") != _text(model["provider"], "provider")
            or payload.get("model") != _text(model["model"], "model")
            or model["model"] not in model_catalogue):
        raise ProductUserConfigurationError("Profile model differs from owner catalogue selection")

    environment_id = _text(env["id"], "Environment id")
    instance = environments.get(environment_id)
    snapshot = instance.inspect()
    if (instance.identity != environment_id or snapshot.provider_id != _text(env["provider"], "Environment provider")
            or snapshot.phase != "ready" or snapshot.observation is None
            or snapshot.observation.state != "running"
            or snapshot.observation.capabilities.isolation != _text(env["isolation"], "Environment isolation")):
        raise ProductUserConfigurationError("selected persisted Environment is not the declared ready instance")

    selection = PiExecutionSelection(
        _text(pi["agentId"], "agent id"), profile_ref, environment_id,
        _text(env["provider"], "Environment provider"), _text(env["isolation"], "Environment isolation"),
        env["sharing"], model["declarationId"], model["provider"], model["model"],
        launch["bridge_executable"], launch["bridge_sha256"],
        launch["pi_executable"], launch["credential_source"],
    )
    return root, selection


def _read_material_submissions(engineering, scope):
    material_values = engineering["materialSubmissions"]
    if type(material_values) is not list:
        raise ProductUserConfigurationError("material submissions must be an explicit array")
    materials = []
    for raw in material_values:
        item = _object(raw, _MATERIAL_KEYS, "material submission")
        ref = decode_artifact_ref(item["revisionRef"])
        command = _object(item["commandKey"], _COMMAND_KEYS, "prior command provenance")
        key = CommandKey(**{name: _text(command[name], name) for name in _COMMAND_KEYS})
        if key.realm_id != ref.realm_id or not _same_scope(ref, scope):
            raise ProductUserConfigurationError("material receipt provenance is outside the selected scope")
        materials.append(ConfiguredMaterialSubmission(ref, key))
    if len({item.revision_ref for item in materials}) != len(materials):
        raise ProductUserConfigurationError("duplicate configured material receipt")

    return tuple(materials)


def resolve_unbound_product_user_configuration(
    document, *, profile_service, environments, runtime, project_id,
    model_catalogue, trusted_launch,
):
    """Read pre-Proposal selections from the original Product admission owner.

    This only reads persisted native selections and provenance data. It creates
    no Engineering context, grants, review reader, Proposal or method. The
    runtime application-port factory creates the one original unbound reader;
    its bind_selection receives the later owner-returned Proposal and phases.
    """
    admission_context = getattr(getattr(runtime, "unit_runtime", None), "context", None)
    owner = getattr(runtime, "unit_execution_owner", None)
    if (not isinstance(admission_context, UnitAdmissionContext)
            or type(owner) is not LocalUnitOwner or owner.admission is not admission_context
            or getattr(runtime, "units", None) is not owner.manager
            or getattr(getattr(runtime, "wire", None), "identity_authority", None)
                is not owner.permission.access_authority
            or type(profile_service) is not ProfileService
            or type(environments) is not EnvironmentManager
            or getattr(runtime, "execution_environments", None) is not environments
            or profile_service.environment_namespace != admission_context.environment_namespace):
        raise ProductUserConfigurationError("original Product admission/Profile owners required")
    admission_context.check_open()
    if composed_profile_service(admission_context) is not profile_service:
        raise ProductUserConfigurationError("Profile service differs from the original Product owner")
    scope = WireScope(admission_context.environment_namespace,
                      _text(project_id, "Engineering project"))
    if scope != owner.permission.scope:
        raise ProductUserConfigurationError("Engineering project differs from the selected original Unit owner")
    with owner.permission.guard("prepare"):
        root, selection = _resolve_native_selection(
            document, profile_service=profile_service, environments=environments,
            environment_namespace=scope.realm_id, model_catalogue=model_catalogue,
            trusted_launch=trusted_launch)
    if (selection.profile_revision != owner.permission.profile_revision
            or selection.agent_id != owner.permission.agent_id
            or selection.environment_id != owner.environment.identity):
        raise ProductUserConfigurationError("Profile/agent differs from the selected original Unit owner")
    engineering = _object(root["engineering"], _ENG_KEYS, "Engineering selection")
    if engineering["proposalRef"] is not None or engineering["phases"] is not None:
        raise ProductUserConfigurationError("bootstrap requires explicit paired null Proposal/phases")
    materials = _read_material_submissions(engineering, scope)
    return ResolvedProductUserSelection(selection, None, None, materials)


def resolve_product_user_configuration(
    document,
    *,
    profile_service,
    environments,
    context,
    factory,
    method_control,
    access,
    scope,
    method_ref,
    model_catalogue,
    trusted_launch,
):
    """Decode user selections and verify persisted profile/environment facts.

    ``trusted_launch`` is a closed mapping produced by deployment policy, not
    by the document. It supplies executable locations and the credential-source
    reference without opening or reading that source.
    """
    if (type(context) is not CommandContext or type(access) is not EngineeringCommandAccess
            or type(scope) is not WireScope):
        raise ProductUserConfigurationError("original admitted Engineering identities required")
    if getattr(method_control, "factory", None) is not factory:
        raise ProductUserConfigurationError("Engineering factory/method-control mismatch")
    if access.current_context() is not context:
        raise ProductUserConfigurationError("no current admitted Engineering context")
    if not _same_scope(context.scope, scope) or access.owner_scope(scope) != context.scope:
        raise ProductUserConfigurationError("Engineering scope differs from current context")
    root, selection = _resolve_native_selection(
        document, profile_service=profile_service, environments=environments,
        environment_namespace=context.scope.realm_id,
        model_catalogue=model_catalogue, trusted_launch=trusted_launch)

    engineering = _object(root["engineering"], _ENG_KEYS, "Engineering selection")
    if engineering["proposalRef"] is None or engineering["phases"] is None:
        raise ProductUserConfigurationError(
            "unbound selection requires the original admission bootstrap reader")
    proposal_ref = decode_proposal_ref(engineering["proposalRef"])
    if not _same_scope(proposal_ref, scope):
        raise ProductUserConfigurationError("ProposalRef is outside the current Engineering scope")
    phase_values = engineering["phases"]
    if type(phase_values) is not list or not phase_values:
        raise ProductUserConfigurationError("explicit configured review phases required")
    phases = []
    for raw in phase_values:
        phase = _object(raw, _PHASE_KEYS, "review phase")
        roles, inputs = phase["eligibleReviewerRoles"], phase["materialInputs"]
        if (type(roles) is not list or not roles
                or any(type(role) is not str or not role for role in roles)
                or len(set(roles)) != len(roles) or type(inputs) is not list):
            raise ProductUserConfigurationError("invalid configured phase roles or material inputs")
        material_inputs = []
        for item in inputs:
            _object(item, {"name", "revisionRef"}, "phase material input")
            material_inputs.append((_text(item["name"], "material input name"),
                                    decode_artifact_ref(item["revisionRef"])))
        submission = None
        if phase["submissionRef"] is not None:
            submission = decode_subject_ref(phase["submissionRef"])
            if type(submission) is not SubmissionRef or not _same_scope(submission, scope):
                raise ProductUserConfigurationError("configured acceptance SubmissionRef is invalid")
        phases.append(ConfiguredReviewPhase(
            _text(phase["phaseKey"], "phase key"), tuple(roles), tuple(material_inputs),
            _text(phase["workflowNodeId"], "workflow node id"), None, submission,
            phase["reviewPurpose"],
        ))
    if len({phase.phase_key for phase in phases}) != len(phases):
        raise ProductUserConfigurationError("duplicate configured review phase")
    with method_control.guard_method(context, method_ref) as method_snapshot:
        expected_phase_keys = {
            node.id for node in method_snapshot.program.workflow.steps
            if getattr(node, "operation", None) == "engineering.reviews.request"
        }
    if not expected_phase_keys or {phase.phase_key for phase in phases} != expected_phase_keys:
        raise ProductUserConfigurationError("configured review phases do not cover the selected method")
    review_bindings = SQLiteReviewBindings(
        factory, method_control, scope=access.owner_scope(scope),
        proposal_ref=proposal_ref, phases=tuple(phases))
    # Resolve every requested phase through the original method/proposal and
    # original SQLite library. This rejects placeholder refs and incomplete
    # or stale phase configuration before returning a selection.
    for phase in phases:
        review_bindings.resolve_bindings(context, method_ref, phase.phase_key)

    materials = _read_material_submissions(engineering, scope)

    # CommandKey is retained only as exact provenance configuration here. The
    # original SQLiteReviewAuthorshipSource verifies the completed journal row
    # and returned artifact when a real ReviewPlan is evaluated.
    return ResolvedProductUserSelection(selection, proposal_ref, tuple(phases), tuple(materials))


__all__ = ["ProductUserConfigurationError", "ResolvedProductUserSelection",
           "resolve_product_user_configuration",
           "resolve_unbound_product_user_configuration"]
