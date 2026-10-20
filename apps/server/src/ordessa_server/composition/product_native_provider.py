"""Construct explicit original-owner inputs for one selected local Pi Unit.

This is a lifecycle producer, not a credential/grant issuer or model catalog.
The caller supplies persisted Profile content, real selected Pi/Harness facts,
the verified current Principal and the already-configured runtime authority.
"""
from __future__ import annotations
from ordessa_units.bindings.profile_admission import UnitProfileAdmission

from collections.abc import Mapping
from dataclasses import dataclass
import math
from pathlib import Path
import time

from ordessa_execution_agents.profiles import (
    Profile,
    ProfileRevision,
    ProfileService,
    ProfileRevisionRef,
    decode_content,
)
from ordessa_environments import (
    EnvironmentInstance,
    EnvironmentManager,
    EnvironmentSnapshot,
    SQLiteEnvironmentStore,
)
from ordessa_execution_agents.harness.providers.registry import HarnessDefinitionDeclaration
from ordessa_units.definitions.fingerprints import ProtectedFingerprintPort
from ordessa_interfaces.system_access.access_control import (
    InstanceAccessAuthority,
    VerifiedPrincipal,
)
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_units.assembly import UnitRunPermission

from .pi_selection import PiExecutionPorts, PiExecutionSelection


_UNIT_ACTIONS = frozenset({"prepare", "start", "interaction", "stop", "release"})


class NativeProviderInputsUnavailable(ValueError):
    """Required selected owner input is absent, stale, or crosses a scope."""


@dataclass(frozen=True)
class ProductNativeProviderInputs:
    """Original selected objects for the product runtime selection hook."""

    selection: PiExecutionSelection
    ports: PiExecutionPorts
    derived_scope: Scope
    environment_manager: EnvironmentManager
    environment_instance: EnvironmentInstance
    environment_snapshot: EnvironmentSnapshot
    profile_service: ProfileService
    profile: Profile
    profile_revision: ProfileRevision


def construct_product_native_provider_inputs(
    runtime,
    *,
    project_id: str,
    principal: VerifiedPrincipal,
    profile_id: str,
    profile_name: str,
    profile_content: dict,
    profile_request_id: str,
    environment_store_path: str,
    environment_root: str,
    unit_root_directory: str,
    unit_actions: frozenset[str],
    joint_capabilities: frozenset[str],
    permission_expires_at: float,
    agent_id: str,
    sharing: bool,
    model_declaration_id: str,
    provider: str,
    model: str,
    model_catalogue: tuple,
    native_model_definition: Mapping,
    declaration: HarnessDefinitionDeclaration,
    fingerprint: ProtectedFingerprintPort,
    bridge_executable: str,
    bridge_sha256: str,
    pi_executable: str,
    credential_source: str,
    credential_environment_variable: str = 'OPENCODE_API_KEY',
    callback_approval_factory: object = None,
    managed_input_ports: object = None,
    acp_turn_opt_in: bool = False,
    effect_write_guard_factory=None,
    existing_environment_manager: EnvironmentManager | None = None,
    selected_environment_snapshot: EnvironmentSnapshot | None = None,
) -> ProductNativeProviderInputs:
    """Select an existing confirmed local Environment or create one, then persist Profile.

    Invoke from the runtime lifecycle hook after original Unit admission and an
    authenticated current Principal exist, but before selected owner binding.
    With no existing-resource pair, this creates one local Environment and
    captures its confirmed snapshot. With both pair members, it selects the
    existing resource only through that manager's public ``get`` and
    ``validate_instance`` against the supplied frozen snapshot; it never
    creates or reconciles an Environment. The ProfileService view is built
    over the exact admission context and therefore uses the same atomic store,
    namespace and policy. The later LocalUnitOwner creates its own ProfileService
    view over that context; the views are not the same Python object and do not
    create another store or authority. No token, HMAC key, Grant, provider
    model row, or Harness declaration is read or invented here.
    """
    from ordessa_environments_local import LocalEnvironmentResourceProvider
    from ordessa_units.public import UnitAdmissionContext

    context = getattr(getattr(runtime, "unit_runtime", None), "context", None)
    wire = getattr(runtime, "wire", None)
    authority = getattr(wire, "identity_authority", None)
    if (not isinstance(context, UnitAdmissionContext)
            or type(authority) is not InstanceAccessAuthority
            or type(principal) is not VerifiedPrincipal):
        raise NativeProviderInputsUnavailable("original runtime admission, scope, authority, and Principal required")
    if getattr(runtime, "started", None) is not False:
        raise NativeProviderInputsUnavailable("native provider construction requires a not-yet-started runtime")
    try:
        context.check_open()
    except Exception as error:
        raise NativeProviderInputsUnavailable("original Unit admission context is closed") from error
    if (context.owner_ports is not None
            or getattr(runtime, "units", None) is not None
            or getattr(runtime, "unit_execution_owner", None) is not None):
        raise NativeProviderInputsUnavailable("Unit owner ports must not already be bound")

    # The native Engineering realm is derived from the original Unit owner.
    # Existing candidate materials in another realm remain historical; they
    # are never rewritten or re-referenced here.
    namespace = context.environment_namespace
    if type(project_id) is not str or not project_id:
        raise NativeProviderInputsUnavailable("explicit Engineering project id required")
    derived_scope = Scope(namespace, project_id)
    if principal.principal_id != context.principal_scope:
        raise NativeProviderInputsUnavailable("current Principal differs from original Unit principal scope")
    try:
        authority.verify(principal)
    except Exception as error:
        raise NativeProviderInputsUnavailable("current Principal is not valid for this runtime authority") from error

    if (type(profile_id) is not str or not profile_id
            or type(profile_name) is not str or not profile_name
            or type(profile_content) is not dict
            or type(profile_request_id) is not str or not profile_request_id):
        raise NativeProviderInputsUnavailable("explicit persisted Profile inputs required")
    if (type(environment_store_path) is not str or not Path(environment_store_path).is_absolute()
            or type(environment_root) is not str or not Path(environment_root).is_absolute()
            or type(unit_root_directory) is not str or not Path(unit_root_directory).is_absolute()):
        raise NativeProviderInputsUnavailable("absolute product-owned Environment and Unit roots required")
    if ((existing_environment_manager is None)
            != (selected_environment_snapshot is None)):
        raise NativeProviderInputsUnavailable(
            "existing Environment selection requires both its original manager and confirmed snapshot"
        )
    store_path = Path(environment_store_path)
    root_path = Path(environment_root)
    unit_path = Path(unit_root_directory)
    if any(path.resolve() != path or any(parent.is_symlink() for parent in (path, *path.parents))
           for path in (store_path, root_path, unit_path)):
        raise NativeProviderInputsUnavailable("selected product paths must be canonical and contain no symlink")
    if (store_path == root_path or store_path == unit_path
            or not store_path.parent.is_dir()):
        raise NativeProviderInputsUnavailable("Environment database and execution roots must be separate existing product paths")
    if (type(unit_actions) is not frozenset or not unit_actions
            or not unit_actions <= _UNIT_ACTIONS
            or any(type(action) is not str for action in unit_actions)
            or type(joint_capabilities) is not frozenset
            or not joint_capabilities
            or any(type(capability) is not str or not capability
                   for capability in joint_capabilities)
            or not {"execution.units." + action for action in unit_actions} <= joint_capabilities
            or type(permission_expires_at) not in (int, float)
            or not math.isfinite(permission_expires_at)
            or permission_expires_at <= time.time()):
        raise NativeProviderInputsUnavailable("explicit bounded Unit actions and expiry required")
    if (type(declaration) is not HarnessDefinitionDeclaration
            or declaration.descriptor.definition_ref.get("environmentNamespace") != namespace
            or not isinstance(fingerprint, ProtectedFingerprintPort)
            or context.fingerprint_port is not fingerprint
            or type(model_catalogue) is not tuple or not model_catalogue
            or any(type(item) is not str or not item for item in model_catalogue)
            or len(set(model_catalogue)) != len(model_catalogue)
            or model not in model_catalogue
            or not isinstance(native_model_definition, Mapping)
            or native_model_definition.get("provider") != provider
            or native_model_definition.get("id") != model):
        raise NativeProviderInputsUnavailable(
            "actual same-namespace Harness declaration, protected fingerprint, and Pi model owner facts required"
        )
    if type(sharing) is not bool or type(acp_turn_opt_in) is not bool:
        raise NativeProviderInputsUnavailable("explicit sharing and ACP opt-in booleans required")
    if effect_write_guard_factory is not None and not callable(effect_write_guard_factory):
        raise NativeProviderInputsUnavailable("original effect-write guard factory must be callable")
    for name, value in (
        ("profile_id", profile_id), ("profile_name", profile_name),
        ("agent_id", agent_id), ("model_declaration_id", model_declaration_id),
        ("provider", provider), ("model", model),
        ("bridge_executable", bridge_executable), ("bridge_sha256", bridge_sha256),
        ("pi_executable", pi_executable), ("credential_source", credential_source),
    ):
        if type(value) is not str or not value or value.strip() != value:
            raise NativeProviderInputsUnavailable("explicit selected " + name + " required")
    if (len(bridge_sha256) != 64
            or any(char not in "0123456789abcdef" for char in bridge_sha256)):
        raise NativeProviderInputsUnavailable("selected bridge SHA-256 required")
    try:
        decode_content(profile_content, namespace)
    except Exception as error:
        raise NativeProviderInputsUnavailable("original Profile content is invalid for this Unit namespace") from error

    # Prove the caller's explicit grants before provisioning an Environment or
    # writing the Profile. This checks existing authority; it never issues a grant.
    for capability in sorted(joint_capabilities):
        with authority.guard(principal, derived_scope, capability):
            pass

    # The original context is still cold: no UnitServices owner graph has
    # been composed yet. Construct one public ProfileService view over this
    # exact context so its policy, fingerprint and atomic writes stay on the
    # original admission/store. Composing unit_services(context) here would
    # prematurely fix owner_ports=None and block the selected LocalUnitOwner.
    profiles = ProfileService(UnitProfileAdmission(context))

    if existing_environment_manager is None:
        environment_store = SQLiteEnvironmentStore(str(store_path))
        environment_provider = LocalEnvironmentResourceProvider(default_root=str(root_path))
        environments = EnvironmentManager(
            store=environment_store,
            providers={"local": environment_provider},
        )
        environment = environments.create(
            "local", {"isolation": "none", "root": str(root_path)}
        )
        snapshot = environment.inspect()
    else:
        if (type(existing_environment_manager) is not EnvironmentManager
                or type(selected_environment_snapshot) is not EnvironmentSnapshot
                or type(getattr(existing_environment_manager, "store", None)) is not SQLiteEnvironmentStore
                or Path(existing_environment_manager.store.path) != store_path):
            raise NativeProviderInputsUnavailable(
                "selected existing Environment manager, database, and immutable snapshot must match"
            )
        environments = existing_environment_manager
        try:
            environment = environments.get(selected_environment_snapshot.identity)
            snapshot = environments.validate_instance(
                environment, expected_snapshot=selected_environment_snapshot,
            )
        except Exception as error:
            raise NativeProviderInputsUnavailable(
                "selected existing Environment snapshot is not confirmed by its original manager"
            ) from error
    if (snapshot.provider_id != "local"
            or snapshot.phase != "ready" or snapshot.observation is None
            or snapshot.operation is not None
            or snapshot.observation.state != "running"
            or snapshot.observation.capabilities.isolation != "none"):
        raise NativeProviderInputsUnavailable("selected original local Environment did not reach its declared running state")

    profile = profiles.create(
        profile_id=profile_id,
        name=profile_name,
        content=profile_content,
        request=profiles.request_key(profile_request_id),
    )
    revision = profiles.get_revision(profile.current_revision)
    if (type(revision.ref) is not ProfileRevisionRef
            or revision.ref != profile.current_revision
            or revision.ref.environment_namespace != namespace):
        raise NativeProviderInputsUnavailable("original Profile owner returned a different immutable revision")

    selection = PiExecutionSelection(
        agent_id=agent_id,
        profile_revision=revision.ref,
        environment_id=environment.identity,
        environment_provider="local",
        environment_isolation="none",
        sharing=sharing,
        model_declaration_id=model_declaration_id,
        provider=provider,
        model=model,
        bridge_executable=bridge_executable,
        bridge_sha256=bridge_sha256,
        pi_executable=pi_executable,
        credential_source=credential_source,
    )

    def permission_factory(*, runtime: object, admission_context: object,
                           selection: PiExecutionSelection, environment_instance: object):
        current_authority = getattr(getattr(runtime, "wire", None), "identity_authority", None)
        if (runtime is not globals_runtime
                or admission_context is not context
                or current_authority is not authority
                or selection is not globals_selection):
            raise NativeProviderInputsUnavailable("Unit permission request differs from the selected runtime owners")
        try:
            current_environment = environments.validate_instance(
                environment_instance, expected_snapshot=snapshot,
            )
        except Exception as error:
            raise NativeProviderInputsUnavailable(
                "selected Environment view differs from its confirmed original resource"
            ) from error
        if (environment_instance.identity != environment.identity
                or environment_instance.identity != selection.environment_id
                or current_environment.identity != snapshot.identity
                or current_environment.provider_id != "local"
                or current_environment.phase != "ready"
                or current_environment.operation is not None
                or current_environment.observation is None
                or current_environment.observation.state != "running"
                or current_environment.observation.capabilities.isolation != "none"):
            raise NativeProviderInputsUnavailable(
                "selected original local Environment no longer matches its confirmed running state"
            )
        try:
            authority.verify(principal)
        except Exception as error:
            raise NativeProviderInputsUnavailable("selected Unit Principal has expired or been revoked") from error
        try:
            context.check_open()
        except Exception as error:
            raise NativeProviderInputsUnavailable("selected Unit admission context is no longer open") from error
        if (getattr(runtime, "started", None) is not False
                or context.owner_ports is not None
                or getattr(runtime, "units", None) is not None
                or getattr(runtime, "unit_execution_owner", None) is not None
                or permission_expires_at <= time.time()):
            raise NativeProviderInputsUnavailable("selected runtime began binding Unit owner ports")
        # Refresh the whole original joint grant set at binding time. The
        # Unit permission remains a narrower action-scoped view of these grants.
        for capability in sorted(joint_capabilities):
            with authority.guard(principal, derived_scope, capability):
                pass
        permission = UnitRunPermission(
            access_authority=authority,
            principal=principal,
            scope=derived_scope,
            agent_id=agent_id,
            profile_revision=revision.ref,
            environment_identity=environment.identity,
            root_directory=str(unit_path),
            actions=unit_actions,
            expires_at=permission_expires_at,
        )
        # Recheck every selected capability at the final binding point. The
        # permission narrows existing joint grants; it cannot widen them.
        for action in sorted(unit_actions):
            with permission.guard(action):
                pass
        return permission

    # Bind identity checks in the callback without exposing any raw credential.
    globals_runtime = runtime
    globals_selection = selection
    ports = PiExecutionPorts(
        environments=environments,
        declaration=declaration,
        fingerprint=fingerprint,
        permission_factory=permission_factory,
        model_catalogue=model_catalogue,
        native_model_definition=native_model_definition,
        credential_environment_variable=credential_environment_variable,
        callback_approval_factory=callback_approval_factory,
        managed_input_ports=managed_input_ports,
        acp_turn_opt_in=acp_turn_opt_in,
        effect_write_guard_factory=effect_write_guard_factory,
    )
    return ProductNativeProviderInputs(
        selection, ports, derived_scope, environments, environment, snapshot,
        profiles, profile, revision
    )


__all__ = [
    "NativeProviderInputsUnavailable",
    "ProductNativeProviderInputs",
    "construct_product_native_provider_inputs",
]
