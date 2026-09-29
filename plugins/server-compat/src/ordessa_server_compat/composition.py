"""The deployment compositions: native Harness mode and sidecar deployments.

Moved from the host's `bootstrap.runtime` (core-cleanup stage 3): the host no
longer knows how a deployment assembles execution — the product composition
(products/server) selects these, and the compatibility core owns the
execution domain they assemble. `build_runtime` is imported from the host's
public bootstrap surface; everything below is business assembly.
"""
from __future__ import annotations

#: The one fixed, no-model ACP peer this composition may launch under the
#: controlled-test-peer opt-in, pinned by content (019 digest discipline).
_CONTROLLED_PEER_SHA256 = "45ebf370de499df9cc371875435f7b4269f5d8c864cde1b3b3fa9bfd08a70841"

import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Mapping

from ordessa_harness.server_acp import AccessEntryTransport
from ordessa_server.bootstrap import ServerRuntime, build_runtime
from server_plugin_api import ServerError
from pacthold_runtime_compat import capability
from pacthold_runtime_compat.runtime_composition.sandbox_port import resolve_sandbox_port
from pacthold.storage import SecretStore

def _home_projection_target(target: Any, *, kind: str) -> str:
    """Validate one declared guest-home target with the sandbox's own grammar.

    The Server does not own the guest layout: the one implementation lives with
    the sandbox that will actually create it, and this wrapper only translates
    its typed refusal into the deployment-level error this loader reports.  A
    deployment is therefore accepted here if and only if the compiler can mount
    it.
    """
    from pacthold_runtime_compat.resource_contracts.home_projection import (
        HomeProjectionRejected, home_projection_target,
    )

    try:
        return home_projection_target(target, kind=kind)
    except HomeProjectionRejected:
        raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID") from None


def _protected_state_paths(
    projection_targets: tuple[str, ...], state_target: str | None,
) -> tuple[str, ...]:
    """Derive the read-only paths inside the writable state subtree."""
    from pacthold_runtime_compat.resource_contracts.home_projection import (
        HomeProjectionRejected, protected_state_paths,
    )

    try:
        return protected_state_paths(projection_targets, state_target)
    except HomeProjectionRejected:
        raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID") from None


#: The token grammar shared by every mount a deployment declares.
MOUNT_TOKEN = re.compile(r"[a-z][a-z0-9-]{0,31}")


def _bound_mount_path(
    token: Any, bindings: Mapping[str, str], used: set[str],
) -> str:
    """Resolve one mount token to the machine-local path the caller bound.

    A document that names a host path instead of a token, a token nobody bound,
    or a binding value that is not an absolute path is refused here: the same
    document has to run on WSL, on this machine and over SSH, and a path in the
    document is exactly what stops that from being true.
    """
    if not isinstance(token, str) or MOUNT_TOKEN.fullmatch(token) is None:
        raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
    bound = bindings.get(token)
    if not isinstance(bound, str) or not bound.startswith("/"):
        raise RuntimeError("SIDECAR_ARTIFACT_BINDING_MISSING")
    if "\\" in bound or "\x00" in bound or "//" in bound or bound.endswith("/"):
        raise RuntimeError("SIDECAR_ARTIFACT_BINDING_INVALID")
    used.add(token)
    return bound


def _runtime_artifact_declarations(
    value: Any, bindings: Mapping[str, str] | None = None, used: set[str] | None = None,
) -> tuple[dict[str, str], ...]:
    """Validate `runtimeArtifactMounts`, resolving each token to its binding.

    The document declares *which* artifact tree a Harness needs and its expected
    digest; where that tree lives on the machine running the Worker is the
    caller's binding, not the document's line.  Existence, link status, the tree
    digest and every overlap rule are still settled on that machine, inside the
    distribution that will read the tree; the Server refuses a declaration that
    could not be verified at all and carries the exact digests across unchanged.
    """
    from pacthold_runtime_compat.resource_contracts.runtime_artifacts import (
        MAX_RUNTIME_ARTIFACT_TREES, RuntimeArtifactRejected,
        validate_runtime_artifact_target,
    )

    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > MAX_RUNTIME_ARTIFACT_TREES:
        raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
    declarations: list[dict[str, str]] = []
    paths: set[str] = set()
    targets: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"token", "target", "treeDigest"}:
            raise RuntimeError("SIDECAR_DEPLOYMENT_HOST_PATH" if "source" in item
                               else "SIDECAR_DEPLOYMENT_INVALID")
        source = _bound_mount_path(item["token"], bindings or {}, used if used is not None else set())
        target = item["target"]
        digest_value = item["treeDigest"]
        if (not isinstance(digest_value, str)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", digest_value) is None):
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        try:
            validate_runtime_artifact_target(target)
        except RuntimeArtifactRejected:
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID") from None
        if source in paths or target in targets:
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        paths.add(source)
        targets.add(target)
        declarations.append({"path": source, "target": target, "digest": digest_value})
    return tuple(declarations)


def _sidecar_deployment_file(root: Path, relative: Any) -> bytes:
    """Read one non-secret plugin artifact named by the deployment.

    `relative` is a plugin-relative name, never a host path: a drive letter, a
    leading separator or a UNC prefix is refused here, so a document written for
    one machine cannot half-work on another.
    """
    if (not isinstance(relative, str) or relative.startswith("/") or "\\" in relative
            or ":" in relative or "\x00" in relative
            or any(part in {"", ".", ".."} for part in relative.split("/"))):
        raise RuntimeError("SIDECAR_DEPLOYMENT_HOST_PATH")
    candidate = root.joinpath(*relative.split("/"))
    if candidate.is_symlink():
        raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID") from None
    if not resolved.is_file() or resolved.stat().st_size > 8 * 1024 * 1024:
        raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
    return resolved.read_bytes()


def _bridge_target(profile_spec) -> str | None:
    """The file the bridge entry belongs in, per the family's MCP declaration."""
    return getattr(profile_spec, "mcp_target", None)


def self_url_of() -> str:
    """The loopback URL the bridge dials back on.

    The Server's own bind address is a machine-local fact; the bridge runs in
    the same machine's network namespace, so the loopback address is the one
    that is always right. The port comes from the environment when the
    embedding process set one, and defaults to the documented port.
    """
    import os as _os

    port = _os.environ.get("AGENT_BOX_HTTP_PORT") or "8732"
    return f"http://127.0.0.1:{port}"


def _registry_profile_spec(harness_type: str):
    """The Harness's own `[harness.profile]` declaration, from the registry.

    Asset slots are the family's own facts (target path, key spelling), so
    they come from the registry the family ships - never from this module and
    never from the deployment, which describes a room, not a family.
    """
    try:
        from ordessa_harness.registry import load_builtin_registry
    except ImportError:
        return None
    try:
        definition = load_builtin_registry().get(harness_type)
        return getattr(definition, "profile", None)
    except BaseException:  # noqa: BLE001 - an unknown family has no slots
        return None


def _registry_native_homes() -> dict[str, str]:
    """The native home each registered Harness declares, keyed by seat id.

    Asked once per composition. The registry is the only place a Harness says
    where its own state lives; a deployment cannot invent one, and a seat the
    registry does not know has none (refused at dispatch, not guessed here).
    """
    try:
        from ordessa_harness.registry import load_builtin_registry
    except ImportError:
        return {}
    try:
        registry = load_builtin_registry()
    except Exception:
        return {}
    homes = {}
    for definition in registry.all():
        homes[definition.identity.harness_type] = definition.profile.native_home
    return homes


def _profile_home_locator(name: str, native_home: str, *, profile_id: str | None = None) -> str:
    """`<role>-<id suffix>/<native home>` - the locator a first Session records.

    The role directory is a normalized label chosen at creation; a later
    rename never recomputes it, because the Session (and the marker inside)
    keeps the locator that was recorded when the home was made.

    The eight-character suffix is the Profile's own identity, and it is what
    keeps two Profiles that share a display name on two different homes: the
    marker check compares identities, so a name-only directory would refuse
    the second Profile for good (the HOME_MARKER_CONFLICT the family gates
    kept hitting across runs). A first Session always records the resolved
    locator, so the rule stays stable for every later turn.
    """
    normalized = re.sub(r"[^a-z0-9-]+", "-", (name or "").lower()).strip("-")
    normalized = normalized[:40] or "role"
    suffix = ""
    if profile_id:
        tail = re.sub(r"[^a-z0-9]+", "", str(profile_id).lower())[-8:]
        if tail:
            suffix = f"-{tail}"
    return f"{normalized}{suffix}/{native_home}"


def _window_of_state_target(state_target: str | None, native_home: str) -> str | None:
    """The audit window relative to the role directory, or None.

    `stateProjection.target` stays a guest path under the guest home; the
    window is that path minus the guest home prefix, so it can name a subtree
    outside the native home as well as one inside it - whichever way the
    Harness family declares its own durable state. A target outside the guest
    home cannot be served by a home bind and is refused.
    """
    del native_home
    if not state_target:
        return None
    prefix = "/runtime/home/"
    if not state_target.startswith(prefix) or state_target == prefix:
        raise RuntimeError("SIDECAR_STATE_PROJECTION_INVALID")
    window = state_target[len(prefix):]
    if (not window or window.startswith("/")
            or any(part in {"", ".", ".."} for part in window.split("/"))
            or "\\" in window or "\x00" in window):
        raise RuntimeError("SIDECAR_STATE_PROJECTION_INVALID")
    return window


def _deployment_credentials(value: Mapping[str, Any]) -> list[dict[str, str]]:
    """Validate the optional `credentials` section of a deployment document.

    Returns the declarations in order; each is `{credentialId, kind, sourcePath,
    label}` with the label possibly empty. Nothing is read here - the file is
    opened by the secret store during import, which is also where the
    symlink/size/bounds rules live, so a declaration can only point at a real,
    ordinary file within the store's own limits.
    """
    raw = value.get("credentials")
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 16:
        raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID: credentials must be at most 16 entries")
    declarations: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping) or set(item) - _CREDENTIAL_DECLARATION_KEYS:
            raise RuntimeError(
                "SIDECAR_DEPLOYMENT_INVALID: a credential declaration takes exactly "
                "credentialId, kind, sourcePath and optional label"
            )
        credential_id = item.get("credentialId")
        kind = item.get("kind")
        source = item.get("sourcePath")
        label = item.get("label", "")
        if not isinstance(credential_id, str) or _CREDENTIAL_ID.fullmatch(credential_id) is None:
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID: credentialId must be credential_<32 hex>")
        if credential_id in seen:
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID: duplicate credentialId")
        if not isinstance(kind, str) or not (1 <= len(kind) <= 32):
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID: credential kind is required")
        if not isinstance(source, str) or not Path(source).is_absolute():
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID: credential sourcePath must be absolute")
        if not isinstance(label, str) or len(label) > 64:
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID: credential label is at most 64 characters")
        seen.add(credential_id)
        declarations.append({
            "credentialId": credential_id, "kind": kind, "label": label, "sourcePath": source,
        })
    return declarations




_APPROVED_CAPABILITY_DECLARERS = frozenset({"sandbox-bwrap"})


def _capability_binding(context: Mapping[str, Any]) -> str:
    """本次执行的中立环境身份（canonical 串）：分发/连接/远端路径三元组。

    声明文档与匹配上下文都用这一处派生结果，保证声明、授权、需求与环境绑定
    绑定在同一次执行上；绑定不含品牌词，业务层与公共层不需要解释它。
    """
    return "|".join((
        str(context.get("distribution", "")),
        str(context.get("connection_id", "")),
        str(context.get("remote_path", "")),
    ))


def _sandbox_provider_name(deployment: Mapping[str, Any], placement_kind: str | None) -> str:
    """The sandbox provider that composes the room for THIS execution.

    The room runs on the machine that executes the turn, not the machine hosting
    the Server (R-0014: a Windows control plane drives Linux WSL/SSH workers).
    A WSL/SSH placement always lands in a Linux guest, so its default is the
    guest sandbox - even when the Server process itself sits on Windows. Only a
    native `local` placement may default to the Windows sandbox. A deployment may
    still name `sandboxProvider` explicitly, or the process may pin
    `AGENT_BOX_SANDBOX_PROVIDER`; neither is overridden here. Keying the default
    on the host alone is order 090's defect: it sent a WSL turn to
    `sandbox-windows`, unresolved in the guest, and the refusal came back as an
    ambiguous dispatch.
    """
    provider = deployment.get("sandboxProvider") or os.environ.get("AGENT_BOX_SANDBOX_PROVIDER")
    if provider:
        return str(provider)
    if placement_kind in {"wsl", "ssh"}:
        return "sandbox-bwrap"
    return "sandbox-windows" if os.name == "nt" else "sandbox-bwrap"


def _capability_material(
    context: Mapping[str, Any], deployment: Mapping[str, Any],
) -> tuple[tuple[Any, ...], tuple[Any, ...], tuple[str, ...], str]:
    """Build the neutral injectables for one execution at the assembly boundary.

    返回 (declaration documents, grants, authorized providers, binding)：
    * documents 由插件以本次部署派生的 targets 逐执行构造（与 launcher 同源）；
      插件拒绝或 provider 不在批准映射内时返回空集——门随后 fail-closed 拒绝；
    * grants 来自部署文档的显式授权字段（独立推导路径），provenance 锁定政策；
    * authorized providers 来自本模块常量映射，不取自声明文档自身。
    """
    binding = _capability_binding(context)
    executable_targets = tuple(
        target for _source, target in deployment.get("_executable_mounts", ())
    )
    projection_targets = tuple(
        target for _source, target in deployment.get("_projection_mounts", ())
    )
    artifact_targets = tuple(
        target for _source, target in deployment.get("_runtime_artifact_mounts", ())
    )
    state_target = deployment.get("_state_target")
    grants = capability.sidecar_grants(
        deployment_executable_targets=executable_targets,
        deployment_projection_targets=projection_targets,
        deployment_artifact_targets=artifact_targets,
        deployment_state_target=state_target,
    )
    documents: tuple[Any, ...] = ()
    try:
        # 身份独立核对：实际安装插件的 descriptor id 与声明自报的 provider 必须
        # 一致，且两者都落在本模块的锁定批准映射内。"已安装/已加载"本身不构成
        # 授权——descriptor 只是待比对的身份，批准集才是授权来源。
        # 声明文档由**已解析的沙箱端口**构造（上层不认识具体沙箱）。
        # 默认随放置走（`_sandbox_provider_name`），与本执行 port_factory 同源。
        port = resolve_sandbox_port(
            _sandbox_provider_name(deployment, context.get("env_kind")))
        descriptor_id = port.descriptor_id()
        document = port.declaration_document(
            readonly_targets=executable_targets + projection_targets + artifact_targets,
            writable_targets=((state_target,) if state_target else ()),
            environment_binding=binding,
            observed_at=int(time.time()),
        )
        if (
            descriptor_id in _APPROVED_CAPABILITY_DECLARERS
            and document.provider in _APPROVED_CAPABILITY_DECLARERS
            and document.provider == descriptor_id
        ):
            documents = (document,)
    except Exception:
        # 解析不到端口、或 provider 按自己的语法拒绝了声明的面：材料留空；
        # 能力门随后 fail-closed 拒绝本次执行——绝不把失败变成一份声明。
        documents = ()
    return documents, grants, tuple(sorted(_APPROVED_CAPABILITY_DECLARERS)), binding


#: The exact keys one credential declaration may use. `sourcePath` is a *path*;
#: a document that tried to carry the secret itself would have to invent a key,
#: and an invented key is a refusal here rather than a silently ignored extra.
_CREDENTIAL_DECLARATION_KEYS = frozenset({"credentialId", "kind", "label", "sourcePath"})
_CREDENTIAL_ID = re.compile(r"^credential_[0-9a-f]{32}$")




def build_runtime_from_native_adapter(
    data_root: Path | str, *, plugin_root: Path | str, harness_id: str,
    adapter_command: str, adapter_args: tuple[str, ...] = (),
    native_continuation: bool = False,
    controlled_test_peer: bool = False,
) -> ServerRuntime:
    """Compose one current-user ACP Agent in an explicitly native Server.

    The adapter is a launch reference, never a credential or projected home.
    The plugin entry verifies its bundled bridge provenance at launch.
    """
    import shutil
    from ordessa_harness.server_acp.plugin import AcpChannelServerPlugin
    from ordessa_server_compat.execution import HarnessDescriptor, HarnessRegistry
    from ordessa_server_compat.execution.sidecar import (
        NativeHarnessPort, NativeProcessLauncher,
    )
    from ordessa_server_compat.execution.sidecar_backend import (
        SidecarExecutionBackend as _SidecarBackendCls,
    )
    from ordessa_server_compat.plugin import ServerCompatPlugin
    from ordessa_workspace.local_environment import LocalEnvironmentProvider
    from ordessa_workspace.plugin import WorkspaceServerPlugin

    if not re.fullmatch(r"[a-z][a-z0-9._-]{0,63}", harness_id):
        raise RuntimeError("NATIVE_HARNESS_INVALID")
    if type(native_continuation) is not bool:
        raise RuntimeError("NATIVE_CONTINUATION_INVALID")
    if type(controlled_test_peer) is not bool:
        raise RuntimeError("NATIVE_CONTROLLED_PEER_INVALID")
    if (not Path(adapter_command).is_absolute() or not Path(adapter_command).is_file()
            or not os.access(adapter_command, os.X_OK)
            or any(not isinstance(arg, str) or "\x00" in arg for arg in adapter_args)):
        raise RuntimeError("NATIVE_ADAPTER_INVALID")
    plugin = Path(plugin_root).resolve()
    entry = plugin / "runtime" / "worker-entry.mjs"  # retired old chain, launch-fail honest
    access_entry = plugin / "runtime" / "access-entry.mjs"
    provenance = plugin / "third_party" / "harness_remote" / "SOURCE.json"
    node = shutil.which("node")
    if not access_entry.is_file() or not provenance.is_file() or node is None:
        raise RuntimeError("NATIVE_HARNESS_ARTIFACT_MISSING")
    if controlled_test_peer:
        # The opt-in is only for the repository's one fixed, no-model ACP peer.
        # A caller cannot turn this into a generic command execution escape.
        # 019 digest discipline: the peer is pinned by CONTENT (sha256), not by
        # path — the fixture may sit wherever the tree keeps it, but its bytes
        # may not change by one character. Path independence also means test
        # relocations never touch production code again.
        candidate = (adapter_args[0]
                     if type(adapter_args) is tuple and len(adapter_args) == 1
                     and isinstance(adapter_args[0], str) else None)
        fixture = Path(candidate) if candidate is not None else None
        if (harness_id != "pi" or adapter_command != node or fixture is None):
            raise RuntimeError("NATIVE_CONTROLLED_PEER_INVALID")
        if not fixture.is_file() or fixture.is_symlink():
            raise RuntimeError("NATIVE_CONTROLLED_PEER_INVALID")
        import hashlib
        if hashlib.sha256(fixture.read_bytes()).hexdigest() != _CONTROLLED_PEER_SHA256:
            raise RuntimeError("NATIVE_CONTROLLED_PEER_INVALID")
    registry = HarnessRegistry()
    registry.register(HarnessDescriptor(
        harness_id, capability_claims=(
            {"native_continuation": True} if native_continuation else {}
        ),
    ))
    root = Path(data_root).resolve()
    adapter = {"command": adapter_command, "args": list(adapter_args)}

    def factory(records, objects, approvals, notifier, _connectors, _credentials,
                _secrets, _turn_inputs):
        def port_factory(context, on_event):
            if context.get("env_kind") != "local" or context.get("harness_type") != harness_id:
                raise RuntimeError("NATIVE_PLACEMENT_UNSUPPORTED")
            project = context.get("normalized_path")
            if not isinstance(project, str) or not project:
                raise RuntimeError("NATIVE_PROJECT_REQUIRED")
            environment = dict(os.environ)
            environment.pop("AGENTBOX_SIDECAR_ISOLATED", None)
            resume_native_id = None
            checkpoint_digest = context.get("checkpoint_object_digest")
            if checkpoint_digest and context.get("checkpoint_native_id"):
                try:
                    checkpoint = json.loads(objects.read(checkpoint_digest))
                except Exception:
                    checkpoint = None
                if (isinstance(checkpoint, dict) and checkpoint.get("resumable") is True
                        and checkpoint.get("harnessType") == harness_id
                        and checkpoint.get("nativeSessionId") == context["checkpoint_native_id"]):
                    resume_native_id = context["checkpoint_native_id"]
            return NativeHarnessPort(
                NativeProcessLauncher((node, str(entry), "--native"), cwd=project),
                environment=environment, profile=harness_id, adapter=adapter,
                directory=project, state_directory=str(root / "native-bridge" / harness_id),
                resume_native_id=resume_native_id,
                declared_capabilities=registry.canonical_claims(harness_id),
                on_event=on_event,
            )

        return _SidecarBackendCls(
            records, objects, approvals, port_factory=port_factory,
            on_event=notifier.notify,
        )

    def native_identity():
        # Read from the plugin this composition built (its own surface, resolved
        # per call: it exists only once that plugin's build has run, and None
        # again after its disposal). Not an attribute of the host runtime —
        # T014-S1b removed that bag.
        service = compat.product_service
        identity = runtime.native_profile_id
        try:
            profile = service.profiles.records.get(identity) if identity else None
            stored = (json.loads(runtime.objects.read(profile["config_object_digest"]))
                      if profile is not None else None)
        except Exception:
            profile = None
        valid = (profile is not None and profile["harness_type"] == harness_id
                 and profile["archived_at"] is None and profile["credential_id"] is None
                 and profile["account_id"] is None and not profile["recovery_pending"]
                 and stored.get("configuration") == {}
                 and service.sessions.native_profile_identity is not None
                 and profile["config_object_digest"] ==
                     service.sessions.native_profile_identity[2])
        return {
            "mode": "native", "harness": harness_id,
            "profileId": identity if valid else None,
        }

    # -- managed ACP channels (seam doc §5: the composition's transport entry) --
    # The channel is carried by the Harness plugin's production access entry:
    # the entry connects (verifying provenance, launching the declared adapter
    # with the Server-resolved cwd as the authoritative directory) and only
    # then relays ACP lines transparently; release goes through the entry's
    # own close-with-OS-confirmation contract.  Nothing here spawns an Agent
    # directly. The registry, its wire methods and the stream route belong to
    # the Harness server facet; this composition only supplies the launch.
    def launch_channel_transport(*, harness_id: str, cwd: str, on_line, on_exit):
        environment = dict(os.environ)
        environment.pop("AGENTBOX_SIDECAR_ISOLATED", None)
        environment.pop("AGENTBOX_ACCESS_TEST_MODE", None)
        if controlled_test_peer:
            environment["AGENTBOX_ACCESS_TEST_MODE"] = "controlled-peer-v1"
        return AccessEntryTransport(
            node=node, entry=str(access_entry), harness_id=harness_id,
            cwd=cwd, adapter=adapter, on_line=on_line, on_exit=on_exit,
            environment=environment,
            **({"controlled_test_peer": True} if controlled_test_peer else {}),
        ).start()

    compat = ServerCompatPlugin(
        harnesses=registry, execution_factory=factory,
        native_harness_id=harness_id,
    )
    acp = AcpChannelServerPlugin(
        launch=launch_channel_transport, native_identity=native_identity,
    )
    # S-06/S-03: the permissions backend joins the native composition (Q5-only
    # approval route — it writes its own store, never the compat approvals
    # table), giving the admission gate its product authority. The dual-write
    # guard stays armed for the legacy-delegated route.
    from ordessa_permissions_backend.plugin import PermissionsBackendPlugin
    runtime = build_runtime(
        root,
        local_workspace_provider=LocalEnvironmentProvider(execution_mode="native"),
        server_plugins=(WorkspaceServerPlugin(), compat, acp,
                        PermissionsBackendPlugin()),
    )
    runtime.native_harness_id = harness_id
    # The start hook reports the profile it created through the composition's
    # channel: the composition owns the runtime, the plugin owns the fact.
    compat.native_profile_sink = lambda pid: setattr(runtime, "native_profile_id", pid)
    # The compatibility core built the product surface its own build composed;
    # the native legs below are written against it directly rather than against
    # a host attribute (T014-S1b).
    service = compat.product_service
    def validate_native_workspace(workspace_id):
        if not isinstance(workspace_id, str) or not workspace_id:
            raise ServerError("NATIVE_PROJECT_REQUIRED", "a selected project is required", status=422)
        workspace = service.workspaces.records.get(workspace_id)
        if workspace["env_kind"] != "local":
            raise ServerError("NATIVE_PLACEMENT_UNSUPPORTED", "native Server requires a local project", status=409)
        selected = workspace["normalized_path"]
        normalized = service.workspaces.local.validate(selected)
        if normalized != selected:
            raise ServerError("NATIVE_PROJECT_CHANGED", "selected project changed", status=409)
    service.sessions.bind_native_workspace_validator(validate_native_workspace)
    # T014-S3: the native identity reaches `server.hello` through the Harness
    # plugin's own discovery-facet contribution (constructed above with
    # `native_identity=`), not through a host attribute the composition has to
    # remember to fill: the fact is already in that plugin's hands, and the
    # rule over what makes it a valid identity is harness business knowledge.
    return runtime


def build_runtime_from_sidecar_deployment(
    data_root: Path | str, deployment_path: Path | str,
    secret_store: SecretStore | None = None, *,
    plugin_root: Path | str, mount_bindings: Mapping[str, str] | None = None,
) -> ServerRuntime:
    """Compose registered Harnesses from an explicit non-secret deployment file.

    `secret_store` is the same explicit injection `build_runtime` accepts: a
    deployment that declares a credential kind needs a store to read the
    credential from, and a caller that already owns one (Windows DPAPI, or an
    acceptance harness with an ephemeral store) passes it here rather than
    relying on the platform default.

    The document names no host path. `plugin_root` is the machine-local root its
    plugin-relative sources are read from - supplied by whoever runs the Server,
    never carried in the document - and every mount the document declares names a
    `token` whose machine-local path `mount_bindings` supplies. A document that
    still carries a host path, or a mount with no binding, is refused rather than
    half-used: that refusal is what keeps one document runnable on any machine.
    """
    path = Path(deployment_path).resolve()
    value = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or value.get("schemaVersion") != 1
            or not isinstance(value.get("harnesses"), list)):
        raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
    if "pluginRoot" in value:
        raise RuntimeError("SIDECAR_DEPLOYMENT_HOST_PATH")
    root = Path(plugin_root).resolve()
    bindings = dict(mount_bindings or {})
    used_bindings: set[str] = set()
    from ordessa_server_compat.execution import HarnessDescriptor, HarnessRegistry, SidecarExecutionBackend
    from ordessa_server_compat.execution.local_channel import LocalSidecarLauncher
    from ordessa_server_compat.execution.placement import SSH_CHANNEL, WSL_CHANNEL, resolve_placement
    from ordessa_server_compat.execution.sidecar import (
        SidecarHarnessPort, WorkerSidecarLauncher, sidecar_bundle_files,
    )
    from pacthold_runtime_compat.resource_contracts.harness_capabilities import (
        CapabilityDeclarationError, validate_claims,
    )

    deployments: dict[str, dict[str, Any]] = {}
    additional_bundle: dict[str, bytes] = {}
    registry = HarnessRegistry()
    for item in value["harnesses"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        harness_id = item["id"]
        adapter = item.get("adapter")
        model_control_id = item.get("modelControlId")
        credential_kind = item.get("credentialKind")
        credential_environment = item.get("credentialEnvironment")
        # Order 56 stage A: a family whose subscription login is a declared
        # file set names it here, guest-home-relative. The names are the whole
        # authority for materialisation and reclamation - the working copy is
        # exactly these files, never a directory walk.
        subscription_credential = item.get("subscriptionCredential")
        subscription_files: tuple[str, ...] = ()
        if subscription_credential is not None:
            if (not isinstance(subscription_credential, dict)
                    or set(subscription_credential) != {"files"}
                    or not isinstance(subscription_credential.get("files"), list)
                    or not subscription_credential["files"]
                    or len(subscription_credential["files"]) > 8):
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
            declared_files: list[str] = []
            for relative in subscription_credential["files"]:
                if not isinstance(relative, str):
                    raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
                _home_projection_target(f"/runtime/home/{relative}", kind="file")
                declared_files.append(relative)
            if len(set(declared_files)) != len(declared_files):
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
            subscription_files = tuple(declared_files)
        timeout_ms = item.get("timeoutMs", 120_000)
        if (harness_id in deployments
                or re.fullmatch(r"[a-z][a-z0-9._-]{0,63}", harness_id) is None
                or not isinstance(adapter, dict)
                or not isinstance(adapter.get("command"), str)
                or not isinstance(adapter.get("args", []), list)
                or any(not isinstance(argument, str) or len(argument) > 8192 or "\x00" in argument
                       for argument in adapter.get("args", []))
                or type(timeout_ms) is not int or not 1 <= timeout_ms <= 120_000):
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        if model_control_id is not None and (
            not isinstance(model_control_id, str) or not model_control_id
        ):
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        if credential_kind is not None and (
            not isinstance(credential_kind, str) or not credential_kind
        ):
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        if credential_environment is not None and (
            credential_kind is None
            or not isinstance(credential_environment, str)
            or re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", credential_environment) is None
        ):
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        deployment = dict(item)
        deployment["_timeout_ms"] = timeout_ms
        adapter = dict(adapter)
        adapter_source = adapter.pop("source", None)
        if adapter_source is not None:
            if adapter["command"] != "/usr/bin/node":
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
            content = _sidecar_deployment_file(root, adapter_source)
            bundle_path = f"agentbox-sidecar/deployment/{harness_id}/adapter.mjs"
            additional_bundle[bundle_path] = content
            adapter["args"] = [f"/runtime/view/{bundle_path}", *adapter.get("args", [])]
        driver = adapter.pop("driver", None)
        if driver is not None:
            # A native Harness whose protocol is not ACP declares the module the
            # sidecar must load instead, as a plugin file named by the
            # deployment. Nothing here knows what that module speaks: the
            # declaration is carried into the reviewed bundle and the fixed view
            # path is what the sidecar loads, so no brand reaches this layer.
            if (not isinstance(driver, dict) or set(driver) != {"source"}
                    or not isinstance(driver.get("source"), str)):
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
            content = _sidecar_deployment_file(root, driver["source"])
            driver_bundle_path = f"agentbox-sidecar/deployment/{harness_id}/driver.mjs"
            additional_bundle[driver_bundle_path] = content
            adapter["driver"] = {"module": f"/runtime/view/{driver_bundle_path}"}
        environment = adapter.get("environment") or {}
        if not isinstance(environment, dict) or any(
            not isinstance(key, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", key) is None
            or re.search(r"TOKEN|SECRET|KEY|PASSWORD|CREDENTIAL|AUTH", key, re.I)
            or not isinstance(setting, str) or len(setting) > 8192 or "\x00" in setting
            or re.fullmatch(r"sk-[A-Za-z0-9_-]+", setting) is not None
            for key, setting in environment.items()
        ):
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        adapter["environment"] = dict(environment)
        deployment["adapter"] = adapter
        projection_mounts = []
        projection_targets: list[str] = []
        for index, projection in enumerate(item.get("projectionFiles") or ()):
            if not isinstance(projection, dict) or set(projection) != {"source", "target"}:
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
            source = projection.get("source")
            # 目标先校验（同一个 guest home 语法，与 bwrap 侧共用一套实现），
            # 再读源文件：一个越界/非规范的目标不该让 Server 先去读盘。
            target = _home_projection_target(projection.get("target"), kind="file")
            content = _sidecar_deployment_file(root, source)
            suffix = Path(str(source)).name
            bundle_path = f"agentbox-sidecar/deployment/{harness_id}/projection-{index}-{suffix}"
            additional_bundle[bundle_path] = content
            projection_mounts.append((bundle_path, target))
            projection_targets.append(target)
        deployment["_projection_mounts"] = tuple(projection_mounts)
        executable_authorizations = []
        executable_mounts = []
        for executable in item.get("executableMounts") or ():
            if not isinstance(executable, dict) or "source" in executable:
                raise RuntimeError("SIDECAR_DEPLOYMENT_HOST_PATH")
            target = executable.get("target")
            digest_value = executable.get("digest")
            source = _bound_mount_path(executable.get("token"), bindings, used_bindings)
            if (not isinstance(target, str)
                    or re.fullmatch(r"/runtime/bin/[A-Za-z0-9._-]+", target) is None
                    or not isinstance(digest_value, str)
                    or re.fullmatch(r"sha256:[0-9a-f]{64}", digest_value) is None):
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
            executable_authorizations.append({"path": source, "digest": digest_value})
            executable_mounts.append((source, target))
        deployment["_executable_authorizations"] = tuple(executable_authorizations)
        deployment["_executable_mounts"] = tuple(executable_mounts)
        artifact_authorizations = _runtime_artifact_declarations(
            item.get("runtimeArtifactMounts"), bindings, used_bindings,
        )
        deployment["_runtime_artifact_authorizations"] = artifact_authorizations
        deployment["_runtime_artifact_mounts"] = tuple(
            (str(declaration["path"]), str(declaration["target"]))
            for declaration in artifact_authorizations
        )
        preferred_auth_method = item.get("preferredAuthMethod")
        if preferred_auth_method is not None and (
            not isinstance(preferred_auth_method, str)
            or re.fullmatch(r"[a-z][a-z0-9._-]{0,63}", preferred_auth_method) is None
        ):
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        state_projection = item.get("stateProjection")
        # §14 (session library independent of the profile home): a family whose
        # session subtree can be split from the rest of its home declares
        # `sessionStore.kind = "sessions-subtree"`; the declared state target is
        # then the *session subtree* inside the guest home and is bound to the
        # per-harness store on the host. The default ("profile-home") keeps the
        # pre-§14 binding byte for byte - shared-DB families (the library holds
        # credential/account tables next to its session tables) must stay there.
        # Order 66 adds `whole-db`: the family library owns the live session
        # files named in `shared` (db + wal + shm + the revert/diff lands) and
        # everything else in the state directory stays in the profile home.
        session_store = item.get("sessionStore")
        session_store_kind = "profile-home"
        session_store_shared: tuple[tuple[str, str], ...] = ()
        if session_store is not None:
            if (not isinstance(session_store, dict)
                    or not set(session_store) <= {"kind", "shared"}
                    or not isinstance(session_store.get("kind"), str)
                    or session_store["kind"] not in
                    {"profile-home", "sessions-subtree", "whole-db"}):
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
            session_store_kind = session_store["kind"]
            if session_store_kind == "whole-db":
                declared = session_store.get("shared")
                if (not isinstance(declared, list) or not declared
                        or len(declared) > 16):
                    raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
                entries: list[tuple[str, str]] = []
                for entry in declared:
                    if (not isinstance(entry, dict)
                            or set(entry) != {"name", "kind"}
                            or not isinstance(entry.get("name"), str)
                            or entry.get("kind") not in {"file", "directory"}):
                        raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
                    # The same sandbox spelling rule as every other relative
                    # declaration: safe names, no escape, bounded depth.
                    _home_projection_target(
                        f"/runtime/home/{entry['name']}", kind="file",
                    )
                    entries.append((entry["name"], entry["kind"]))
                if len({name for name, _kind in entries}) != len(entries):
                    raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
                session_store_shared = tuple(entries)
            elif "shared" in session_store:
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        state_target: str | None = None
        state_ephemeral_paths: tuple[str, ...] = ()
        if state_projection is not None:
            if (not isinstance(state_projection, dict)
                    or not set(state_projection) <= {"target", "ephemeralPaths"}
                    or not isinstance(state_projection.get("target"), str)):
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
            state_target = _home_projection_target(
                state_projection["target"], kind="directory",
            )
            declared = state_projection.get("ephemeralPaths")
            if declared is None:
                declared = []
            if not isinstance(declared, list) or len(declared) > 8:
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
            for relative in declared:
                if not isinstance(relative, str):
                    raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
                # 与 target 同一套沙箱语法验证“可写 state 内的临时子路径”，
                # 由 bwrap 以 tmpfs 遮蔽：可写但不进 view/state/checkpoint。
                _home_projection_target(
                    f"{state_target}/{relative}", kind="directory",
                )
            state_ephemeral_paths = tuple(declared)
        # 受保护集合**派生**自这份声明本身：落在可写 state 子树里的只读投影文件
        # （按 state 目标的相对路径记名）。它既不按家硬编码，也不依赖"overlay 恰好
        # 遮住"——checkpoint 捕获按名字排除，恢复遇到同名相对路径直接类型化拒绝。
        deployment["_protected_state_paths"] = _protected_state_paths(
            tuple(projection_targets), state_target,
        )
        if session_store_kind in {"sessions-subtree", "whole-db"} and state_target is None:
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        if state_target is not None:
            deployment["_state_target"] = state_target
        else:
            deployment["_state_target"] = None
        usage_probe = item.get("usageProbe")
        if usage_probe is not None:
            if (not isinstance(usage_probe, dict)
                    or not set(usage_probe) <= {"journalSuffix", "format"}
                    or not isinstance(usage_probe.get("journalSuffix"), str)
                    or not isinstance(usage_probe.get("format"), str)):
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
            from ordessa_server_compat.execution.usage import FORMATS

            if usage_probe["format"] not in FORMATS:
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
            deployment["_usage_probe"] = {
                "journalSuffix": usage_probe["journalSuffix"],
                "format": usage_probe["format"],
            }
        else:
            deployment["_usage_probe"] = None
        deployment["_session_store"] = session_store_kind
        deployment["_session_store_shared"] = session_store_shared
        deployment["_subscription_files"] = subscription_files
        # Order 67's narrowed lock: a family whose home cannot be certified for
        # concurrent writers declares `homeConcurrency = "exclusive"`, and
        # admission then admits one active Turn per Profile for that family
        # alone. The default stays "shared": the Session is the uniqueness
        # unit, and the lock is declared per family, never guessed.
        home_concurrency_value = item.get("homeConcurrency", "shared")
        if home_concurrency_value not in {"shared", "exclusive"}:
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        deployment["_home_concurrency"] = home_concurrency_value
        deployment["_state_ephemeral_paths"] = state_ephemeral_paths
        deployments[harness_id] = deployment
        # 能力声明是部署座位上的唯一入口：canonical id + 真 bool，其它一律类型化拒绝。
        # 任何生产模板都只能经过这里，不能再各自手写一套不受校验的字典。
        raw_claims = item.get("capabilityClaims")
        try:
            capability_claims = {} if raw_claims is None else validate_claims(raw_claims)
        except CapabilityDeclarationError as exc:
            raise RuntimeError(f"SIDECAR_DEPLOYMENT_INVALID: {exc.code}") from exc
        # Order 092: the seat may declare the canonical protocols it speaks and
        # the family-native dialect value for each. Absent = undeclared (unknown,
        # never incompatible); an illegal declaration is a typed refusal.
        raw_wire_protocols = item.get("wireProtocols") or {}
        if not isinstance(raw_wire_protocols, dict):
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        from ordessa_server_compat.execution import HarnessDescriptorError
        try:
            descriptor = HarnessDescriptor(
                harness_id,
                credential_kind=credential_kind,
                model_control_id=model_control_id,
                credential_environment=credential_environment,
                capability_claims=capability_claims,
                control_options={
                    str(key): tuple(options)
                    for key, options in dict(item.get("controlOptions") or {}).items()
                },
                security_locked_controls=tuple(item.get("securityLockedControls") or ()),
                wire_protocols=raw_wire_protocols,
            )
        except HarnessDescriptorError as exc:
            raise RuntimeError(f"SIDECAR_DEPLOYMENT_INVALID: {exc}") from exc
        registry.register(descriptor)
    unused = sorted(set(bindings) - used_bindings)
    if unused:
        # A binding nobody asked for is a typo or a stale document, and silently
        # ignoring it would hide which artifact the deployment really uses.
        raise RuntimeError("SIDECAR_ARTIFACT_BINDING_UNUSED")

    # Each seat's native home comes from the Harness registry, never from the
    # document: the document describes how a room runs, the registry says where
    # a Harness's own state lives. A seat with no declared native home cannot
    # run in the native-home model and is refused when a turn asks for it.
    native_homes = _registry_native_homes()
    for harness_id, deployment in deployments.items():
        deployment["_native_home"] = native_homes.get(harness_id)

    bundle = sidecar_bundle_files(root, additional_files=additional_bundle)

    # Credential sources are *declared* here and read from their own files: the
    # deployment document stays a non-secret artifact, and this is the only
    # place the product server can learn about a credential the operator (or the
    # Desktop that owns the machine's credential records) has placed. The strict
    # key set below is what enforces "no secret in the document" - a `value` or
    # `secret` key is a typed refusal, not an ignored extra.
    declared_credentials = _deployment_credentials(value)

    # The local placement's home root is this Server's own data root: the
    # Server *is* the machine that runs those turns. It is a machine-local
    # fact, never a document field and never a recorded path.
    local_home_root = str(Path(data_root).resolve() / "profiles")

    # Order 66 stage B: per-family guards for the shared session library. The
    # guard reads the library's database files on this machine
    # read-only (through the WAL) and refuses a switch when any credential
    # table is non-empty; families without a whole-db store have no guard.
    shared_store_guards: dict[str, Any] = {}
    for harness_id, deployment in deployments.items():
        if deployment.get("_session_store") != "whole-db":
            continue
        database_files = [
            name for name, kind in deployment["_session_store_shared"]
            if kind == "file" and name.endswith(".db")
        ]
        if not database_files:
            continue
        library = Path(local_home_root) / "_sessions" / harness_id

        def guard(paths=tuple(library / name for name in database_files)):
            from ordessa_server_compat.execution.session_store_guard import guard_shared_store

            for path in paths:
                guard_shared_store(path)

        shared_store_guards[harness_id] = guard

    def factory(records, objects, approvals, notifier, connectors, credentials,
                secret_store, turn_inputs):
        # No gate here: whether a connector is required depends on the placement
        # the workspace names, and that is resolved per turn.
        def port_factory(context, on_event):
            try:
                deployment = deployments[context["harness_type"]]
            except KeyError as exc:
                raise RuntimeError("HARNESS_DEPLOYMENT_UNAVAILABLE") from exc
            frozen = json.loads(objects.read(context["config_object_digest"]))
            execution = dict(frozen.get("execution") or {})
            descriptor = registry.get(context["harness_type"])
            credential_id = execution.get("credentialId") or context.get("credential_id")
            credential = None
            if credential_id is not None:
                record = credentials.get(credential_id, kind=descriptor.credential_kind)
                if secret_store is None:
                    raise RuntimeError("CREDENTIAL_STORE_UNAVAILABLE")
                try:
                    credential = secret_store.read(record["secret_locator"])
                except Exception as exc:  # Order 120: resolve at this layer
                    # The credential cannot be read on this machine. Fail here,
                    # before the capability gate and any spawn, so the transcript
                    # gets a typed, actionable reason (``CREDENTIAL_NOT_AVAILABLE``)
                    # rather than a KeyError collapsing into EXECUTION_FAILED. The
                    # id is non-sensitive; the secret value is never logged.
                    _log = logging.getLogger(__name__)
                    _log.warning(
                        "credential %s is unavailable for execution (harness %s): %s",
                        credential_id, context.get("harness_type"), exc)
                    raise RuntimeError("CREDENTIAL_NOT_AVAILABLE") from exc
            # The native home: no restore, no upload. The Harness reopens its
            # own durable directory on the machine that runs this turn; the
            # record's locator (kept once a turn has run) survives renames,
            # and the first turn of a Session derives it from the role name.
            native_home = deployment.get("_native_home")
            if not native_home:
                raise RuntimeError(
                    f"HARNESS_NATIVE_HOME_UNDECLARED: {context['harness_type']}"
                )
            home_locator = context.get("home_locator") or _profile_home_locator(
                context.get("profile_name") or context["harness_type"], native_home,
                profile_id=context.get("profile_id"),
            )
            # The workspace record says where this turn belongs; that fact - and
            # only that fact - decides which channel stages and starts it.
            kind = context.get("env_kind")
            placement = resolve_placement(
                kind, has_connector=connectors.get(kind) is not None,
            )
            audit_window = _window_of_state_target(
                deployment["_state_target"], native_home,
            )
            # The sandbox is resolved by name, never imported here: the name
            # comes from the deployment, the process environment, or the one
            # documented default provider id. An unresolvable name is a typed
            # refusal, not a silent run without isolation.
            # The default provider follows the placement (the machine that runs
            # the turn), not the host: a WSL/SSH guest is Linux even when the
            # Server itself sits on Windows (order 090). The name is still
            # resolved, never imported.
            sandbox_port = resolve_sandbox_port(
                _sandbox_provider_name(deployment, placement.kind))
            asset_files: dict[str, bytes] = {}
            profile_id_for_assets = context.get("profile_id")
            # A composition whose ledger has never been opened cannot hold a
            # binding: the ownership check is the file itself, not a guess.
            if (profile_id_for_assets
                    and Path(records.database.path).exists()):
                from ordessa_server_compat.assets.rendering import McpRenderError, render_for_family
                from ordessa_server_compat.hooks.rendering import (
                    HookRenderError,
                    hooks_target_for,
                    merge_fragments,
                    render_hooks_fragment,
                )

                profile_spec = _registry_profile_spec(context["harness_type"])
                # One document per declared target; JSON targets collect keyed
                # fragments and merge, TOML targets concatenate their tables.
                json_documents: dict[str, dict[str, dict]] = {}
                toml_fragments: dict[str, list[str]] = {}

                for binding in turn_inputs.assets.bindings(
                        profile_id_for_assets, enabled_only=True):
                    if binding["kind"] != "mcp":
                        continue
                    definition = turn_inputs.mcp_assets.read(
                        asset_id=binding["assetId"], revision=binding["revision"])
                    if not turn_inputs.mcp_assets.verify(
                            asset_id=binding["assetId"], revision=binding["revision"],
                            expected_digest=binding["digest"]):
                        raise RuntimeError(
                            "ASSET_DIGEST_MISMATCH: the stored MCP definition "
                            "no longer matches its recorded digest"
                        )
                    stdio = definition.get("transport", {}).get("stdio")
                    references = dict((stdio or {}).get("env") or {})
                    if references:
                        raise RuntimeError(
                            "MCP_CREDENTIAL_INJECTION_UNVERIFIED: this server "
                            f"carries credential references {sorted(references)} "
                            "and this family's injection path is not pinned yet"
                        )
                    try:
                        target, rendered = render_for_family(
                            definition, profile_spec=profile_spec, resolved_env={})
                    except McpRenderError as refusal:
                        raise RuntimeError(f"{refusal.code}: {refusal.message}") from refusal
                    if not target.startswith("/runtime/home/"):
                        raise RuntimeError(
                            "ASSET_SLOT_UNSUPPORTED: the declared MCP target is "
                            "outside the guest home"
                        )
                    if target.endswith(".toml"):
                        toml_fragments.setdefault(target, []).append(rendered)
                    else:
                        key = getattr(profile_spec, "mcp_key", None) or "mcpServers"
                        document = json.loads(rendered)
                        json_documents.setdefault(target, {}).setdefault(key, {}).update(
                            document.get(key, {}))

                # Order 59: enabled hooks join the same assembly, in the
                # family's own document shape.
                enabled = turn_inputs.hooks.enabled_for_family(context["harness_type"])
                if enabled:
                    target, key = hooks_target_for(profile_spec)
                    if target is None:
                        raise RuntimeError(
                            "HOOK_TARGET_UNSUPPORTED: this family declares "
                            "no hook document target"
                        )
                    fragment = render_hooks_fragment(
                        context["harness_type"],
                        [row["model"] for row in enabled],
                    )
                    if target.endswith(".json"):
                        json_documents.setdefault(target, {})[key or "hooks"] = fragment
                    else:
                        raise RuntimeError(
                            "HOOK_TARGET_UNSUPPORTED: hooks need a JSON target"
                        )

                # Order 65 C: a Profile that may delegate gets the bridge as a
                # synthesized MCP server entry, carrying an attempt-scoped
                # token. Zero grants: no entry (no always-failing tools).
                bridge_entry = None
                if profile_id_for_assets:
                    from ordessa_server_compat.profiles.subagents import (
                        grant_edges, has_delegation,
                    )

                    edges = grant_edges(turn_inputs.profiles.subagent_grants())
                    if has_delegation(edges, profile_id_for_assets):
                        import uuid as _uuid

                        token = _uuid.uuid4().hex
                        turn_inputs.delegation_tokens[token] = {
                            "turnId": context.get("id"),
                            "profileId": profile_id_for_assets,
                        }
                        bridge_command = [
                            "/usr/bin/node",
                            "/runtime/view/agentbox-sidecar/runtime/subagent-bridge.mjs",
                        ]
                        bridge_entry = {
                            "command": bridge_command[0],
                            "args": bridge_command[1:],
                            "env": {
                                "AGENTBOX_BRIDGE_URL": self_url_of(),
                                "AGENTBOX_BRIDGE_TOKEN": token,
                            },
                            "name": "agentbox-subagents",
                            "target": _bridge_target(profile_spec),
                        }

                # The bridge creates its own document when the turn has no
                # other MCP content: a granted Profile always gets the tools.
                if bridge_entry is not None:
                    bridge_target = str(bridge_entry["target"] or "")
                    if bridge_target.endswith(".json"):
                        key = getattr(profile_spec, "mcp_key", None) or "mcpServers"
                        json_documents.setdefault(bridge_target, {}).setdefault(key, {})[
                            bridge_entry["name"]
                        ] = {
                            "command": bridge_entry["command"],
                            "args": list(bridge_entry["args"]),
                            "env": dict(bridge_entry["env"]),
                        }
                    elif bridge_target.endswith(".toml"):
                        lines = [
                            f"[mcp_servers.{bridge_entry['name']}]",
                            f'command = "{bridge_entry["command"]}"',
                            "args = [" + ", ".join(
                                f'"{item}"' for item in bridge_entry["args"]) + "]",
                        ]
                        for env_name, env_value in sorted(bridge_entry["env"].items()):
                            lines.append(f'{env_name} = "{env_value}"')
                        toml_fragments.setdefault(bridge_target, []).append(
                            "\n".join(lines) + "\n")
                    else:
                        raise RuntimeError(
                            "SUBAGENT_BRIDGE_TARGET_UNSUPPORTED: this family "
                            "declares no MCP document for the bridge"
                        )

                projected = {
                    str(target_value)
                    for _source, target_value in deployment.get("_projection_mounts", ())
                }
                for target, fragments in sorted(json_documents.items()):
                    if target in projected:
                        raise RuntimeError(
                            "ASSET_SLOT_CONFLICT: a read-only projection already "
                            "covers the declared target " + target
                        )
                    try:
                        text = merge_fragments(
                            target, [(key, value) for key, value in fragments.items()])
                    except HookRenderError as refusal:
                        raise RuntimeError(f"{refusal.code}: {refusal.message}") from refusal
                    asset_files[target[len("/runtime/home/"):]] = text.encode("utf-8")
                for target, parts in sorted(toml_fragments.items()):
                    if target in projected:
                        raise RuntimeError(
                            "ASSET_SLOT_CONFLICT: a read-only projection already "
                            "covers the declared target " + target
                        )
                    asset_files[target[len("/runtime/home/"):]] = (
                        "\n".join(part.rstrip("\n") for part in parts) + "\n"
                    ).encode("utf-8")
            subscription = None
            subscription_asset: dict[str, bytes] = {}
            account_id = context.get("account_id")
            if account_id:
                declared = deployment.get("_subscription_files") or ()
                if not declared:
                    raise RuntimeError(
                        "SUBSCRIPTION_UNSUPPORTED: this Harness declares no "
                        "subscription login-state files"
                    )
                # The accounts half is built by the compatibility core's own
                # plugin and handed to this factory as a declared input; the
                # closure reads it per turn.
                if turn_inputs.account_assets is None:
                    raise RuntimeError("ACCOUNT_STORE_UNAVAILABLE")
                _record = turn_inputs.accounts.get(account_id)
                locator, digest = turn_inputs.accounts.asset_reference(account_id)
                if locator is not None:
                    subscription_asset = turn_inputs.account_assets.read_asset(
                        locator=locator, declared=declared)
                subscription = {
                    "account_id": account_id,
                    "materialized_digest": digest,
                    "files": tuple(declared),
                }
            if placement.channel in {WSL_CHANNEL, SSH_CHANNEL}:
                launcher = WorkerSidecarLauncher(
                    connectors[placement.kind],
                    workspace={
                        "distribution": context["distribution"],
                        "remote_user": context["remote_user"],
                        "connection_id": context["connection_id"],
                        "remote_path": context["remote_path"],
                    },
                    bundle=bundle, credential=credential,
                    executable_authorizations=deployment["_executable_authorizations"],
                    executable_mounts=deployment["_executable_mounts"],
                    runtime_artifact_authorizations=deployment["_runtime_artifact_authorizations"],
                    runtime_artifact_mounts=deployment["_runtime_artifact_mounts"],
                    projection_mounts=deployment["_projection_mounts"],
                    home_locator=home_locator,
                    native_home=native_home,
                    profile_id=context["profile_id"],
                    harness_type=context["harness_type"],
                    audit_window=audit_window,
                    state_ephemeral_paths=deployment["_state_ephemeral_paths"],
                    protected_state_paths=deployment["_protected_state_paths"],
                    timeout_ms=deployment["_timeout_ms"],
                    sandbox_port=sandbox_port,
                    session_store_harness=(
                        context["harness_type"]
                        if deployment["_session_store"] in {"sessions-subtree", "whole-db"} else None
                    ),
                    session_store_target=(
                        deployment["_state_target"]
                        if deployment["_session_store"] in {"sessions-subtree", "whole-db"} else None
                    ),
                    session_store_shared=deployment["_session_store_shared"],
                    subscription_files=(subscription or {}).get("files", ()),
                    asset_files=asset_files,
                    usage_probe=deployment["_usage_probe"],
                )
            else:
                launcher = LocalSidecarLauncher(
                    workspace_path=context.get("normalized_path") or context["remote_path"],
                    bundle=bundle, credential=credential,
                    executable_mounts=deployment["_executable_mounts"],
                    runtime_artifact_mounts=deployment["_runtime_artifact_mounts"],
                    projection_mounts=deployment["_projection_mounts"],
                    home_root=local_home_root,
                    home_locator=home_locator,
                    native_home=native_home,
                    profile_id=context["profile_id"],
                    harness_type=context["harness_type"],
                    state_target=deployment["_state_target"],
                    state_ephemeral_paths=deployment["_state_ephemeral_paths"],
                    protected_state_paths=deployment["_protected_state_paths"],
                    sandbox_port=sandbox_port,
                    session_store_harness=(
                        context["harness_type"]
                        if deployment["_session_store"] in {"sessions-subtree", "whole-db"} else None
                    ),
                    session_store_target=(
                        deployment["_state_target"]
                        if deployment["_session_store"] in {"sessions-subtree", "whole-db"} else None
                    ),
                    session_store_shared=deployment["_session_store_shared"],
                    subscription_files=(subscription or {}).get("files", ()),
                    subscription_asset=subscription_asset,
                    asset_files=asset_files,
                    usage_probe=deployment["_usage_probe"],
                )
            capability_documents, capability_grants, authorized, binding = (
                _capability_material(context, deployment)
            )
            return SidecarHarnessPort(
                launcher,
                subscription=subscription,
                account_plumbing=(
                    (turn_inputs.accounts, turn_inputs.account_assets)
                    if subscription is not None else None
                ),
                environment={"AGENTBOX_SIDECAR_ISOLATED": "1"},
                profile=context["harness_type"], adapter=deployment["adapter"],
                model=execution.get("model"),
                capability_documents=capability_documents,
                capability_grants=capability_grants,
                capability_authorized_providers=authorized,
                capability_binding=binding,
                credential_environment=(
                    descriptor.credential_environment if credential is not None else None
                ),
                preferred_auth_method=deployment.get("preferredAuthMethod"),
                # A recorded native id is reopened only when the harness
                # declares durable state (a native-home window) and a turn has
                # already recorded a locator under it. Anything less - a
                # pre-home Session, a seat with no declared window - opens a
                # fresh native session, and the changed native id says so
                # instead of pretending a reopen succeeded.
                resume_native_id=(
                    context.get("checkpoint_native_id")
                    if context.get("home_locator") and deployment["_state_target"]
                    else None
                ),
                # The sidecar's own working state (a bridge's session index)
                # lives inside the home window: it must survive the attempt,
                # because the next turn's resume reads it from the same durable
                # directory the room binds. It was an ephemeral /tmp path when
                # state travelled as bytes; the home replaces both.
                state_directory=deployment["_state_target"]
                or f"/runtime/home/{native_home}",
                directory="/workspace",
                native_platform=placement.kind if kind else None,
                home_locator=home_locator,
                # 静态上限只能来自已校验的注册声明（不依赖 port 的默认值）。
                declared_capabilities=descriptor.capability_claims,
                usage_probe=deployment["_usage_probe"],
                on_event=on_event,
            )

        return SidecarExecutionBackend(
            records, objects, approvals, port_factory=port_factory,
            on_event=notifier.notify,
        )

    # T014-S1d: the deployment composition names its plugins directly, the
    # same way the native composition above does. These facts used to ride
    # `build_runtime`'s business-kwarg copy of the product's compat funnel;
    # the funnel now has exactly one home (this call site and
    # `products/server`'s `default_plugins`), and the host carries none.
    from ordessa_harness.server_acp.plugin import AcpChannelServerPlugin
    from ordessa_server_compat.plugin import ServerCompatPlugin
    from ordessa_workspace.plugin import WorkspaceServerPlugin

    compat = ServerCompatPlugin(
        harnesses=registry, execution_factory=factory,
        home_concurrency={
            harness_id: deployment["_home_concurrency"]
            for harness_id, deployment in deployments.items()
        },
        shared_store_guards=shared_store_guards,
        subscription_files_for=lambda harness: (
            deployments.get(harness, {}).get("_subscription_files") or ()
        ),
        declared_credentials=declared_credentials,
    )
    runtime = build_runtime(
        data_root, secret_store=secret_store,
        server_plugins=(WorkspaceServerPlugin(), compat, AcpChannelServerPlugin()),
    )
    return runtime
