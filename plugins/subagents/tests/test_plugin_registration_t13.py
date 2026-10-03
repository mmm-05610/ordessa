"""T13 / G21 — the server-side registration face of this domain.

Requirement rows: `specs/011-q3-subagents/tasks.md` T13 ("产品启用唯一服务/贡献，
删除仅本域重复逻辑，保持旧授权边归属"), `docs/design/native-subagents/contracts.md`
§C1 (the service surface, "服务鉴权上下文给 principal，客户端不可自报"), §C5 (typed
refusals, an unknown result stays queryable) and `specs/011-q3-subagents/
api-requests.md` SR-7 (composition is C0's surface, so this file verifies the
plugin against the *contract* types and a host-shaped context, never against a
live product).

Evidence level: L1 — the real `server_plugin_api` dataclasses, the real
`DefinitionService`/`DefinitionStore`, a real file store under `tmp_path`, and no
mock of a seam this plugin claims to consume.

Nine locks, each with the counter-example it exists to catch:

1. the descriptor/registration are the contract's, with the fields the contract
   declares — and the two §C1 surfaces nothing in this composition can back
   (`approveAssignmentUpdate`, `inspectNative`) are **not advertised**;
2. the readiness claims are honest: ten methods registered, nine ready,
   `resolvePreview` refuses and says so;
3. the store root is derived from the host's data root under the plugin id —
   never CWD-relative, never an absolute user path, and nothing is written at
   activation;
4. only the ports this domain genuinely uses are read (the store is file-backed,
   so `database`/`idempotency` must stay untouched — a false dependency is a
   dependency);
5. **G07**: a client-supplied `principal` / `serverScope` / `projectId` is a real
   refusal at both layers (declared shape *and* the handler's own gate), it
   writes nothing, and the successful path carries only server-attested identity
   — including the provenance stamp of a published revision;
6. every mutation carries `expectedRowVersion` + `operationKey`, and a missing
   one is refused by *this face* with the wire param name (the service's own
   refusal names the snake_case field, so a red test here cannot be mistaken for
   the service answering);
7. absent-authority behaviour (rollout R07): reads and content CRUD work with no
   authorizer wired; a permission-bearing publish and every apply/invoke-shaped
   call refuse, naming the missing seam;
8. §C5 refusals keep their code and item-level reason, converge onto a real
   wire/1 family, and an unknown outcome stays an `OUTCOME_UNKNOWN` the caller
   can re-query — never a silent success;
9. disposal/uninstall hides rather than deletes: the files survive, a second
   activation reads them back, and this plugin's teardown touches no other
   domain's object.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

import pytest

TESTS_DIR = Path(__file__).resolve().parent
SRC_DIR = TESTS_DIR.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from server_plugin_api import (  # noqa: E402
    PLUGIN_METHOD_ID,
    SERVER_PLUGIN_API_VERSION,
    ServerMethodDescriptor,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
    WireError,
)

from ordessa_assets_subagents import decoder, dto, errors, scopes  # noqa: E402
from ordessa_assets_subagents.plugin import (  # noqa: E402
    DOMAIN_DIR,
    IMPORT_DIR,
    PLUGIN_ID,
    STORE_DIR,
    NativeSubagentsServerPlugin,
)
from ordessa_assets_subagents.wire import (  # noqa: E402
    ASSIGNMENT_SOURCE_PORT,
    CEILING_AUTHORITY_PORT,
    CONTEXT_PORT,
    IMPORT_ROOT_PORT,
    IMPORT_ROOT_UNAPPROVED,
    RESOLVE_PREVIEW_UNWIRED,
    SELF_REPORTED_IDENTITY_KEYS,
    SERVICE_PORT,
    SubagentsWire,
    DeploymentAttestation,
)

ADVERTISED = (
    "assets.subagents.create", "assets.subagents.get", "assets.subagents.list",
    "assets.subagents.saveRevision", "assets.subagents.archive",
    "assets.subagents.restore", "assets.subagents.clone",
    "assets.subagents.importPreview", "assets.subagents.approveImport",
    "assets.subagents.resolvePreview",
)

#: The §C1 members this slice does not back, so this face must stay silent about
#: them: an advertised method with no answer behind it is the failure mode.
NOT_ADVERTISED = (
    "assets.subagents.approveAssignmentUpdate", "assets.subagents.inspectNative",
    "assets.subagents.apply", "assets.subagents.invoke", "assets.subagents.run",
)


# -- builders ---------------------------------------------------------------


class PortProbe(dict):
    """A host-port mapping that records what a plugin actually reads."""

    def __init__(self, values: Mapping[str, Any]) -> None:
        super().__init__(values)
        self.read: list[str] = []

    def __getitem__(self, key: str) -> Any:
        self.read.append(str(key))
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:
        self.read.append(str(key))
        return super().get(key, default)


class FakeRequestContext:
    """A composed `assets.subagents.context@1`: identity, scope and ceiling.

    Only what the real port would know: who the caller is, which project the
    server verified, and what the principal may declare. It never reads a param.
    """

    def __init__(self, *, principal: str = "u:alice", server_scope: str = "server:lab",
                 verified_project: str | None = None,
                 ceiling: "tuple[str, ...] | frozenset[str]" = frozenset()) -> None:
        self.authorization_context = scopes.AuthorizationContext.issued_by_service(
            scopes.Principal(principal), scopes.ServerScope(server_scope),
            None if verified_project is None else scopes.ProjectId(verified_project),
        )
        self.ceiling = frozenset(ceiling)

    def authorization(self) -> scopes.AuthorizationContext:
        return self.authorization_context

    def verify_principal(self, principal: str, *, server_scope: str) -> bool:
        return (principal == self.authorization_context.principal.id
                and server_scope == self.authorization_context.server_scope.id)

    def permission_ceiling(self, principal: str, server_scope: str) -> frozenset[str]:
        if not self.verify_principal(principal, server_scope=server_scope):
            return frozenset()
        return self.ceiling


def build(plugin: NativeSubagentsServerPlugin | None = None, *,
          data_root: Path, ports: "Mapping[str, Any] | None" = None,
          ) -> "tuple[ServerPluginRegistration, NativeSubagentsServerPlugin]":
    instance = plugin or NativeSubagentsServerPlugin()
    # a PortProbe is passed through as itself: copying it would erase the very
    # read log the port-usage test measures
    read_ports = ports if isinstance(ports, PortProbe) else dict(ports or {})
    context = ServerPluginContext(
        plugin_id=PLUGIN_ID, data_root=data_root, ports=read_ports,
    )
    return instance.build(context), instance


def by_id(registration: ServerPluginRegistration) -> "dict[str, ServerMethodDescriptor]":
    return {item.method_id: item for item in registration.methods}


def call(registration: ServerPluginRegistration, method_id: str,
         params: Mapping[str, Any]) -> Any:
    """Invoke one handler directly (the plugin's own guards, no transport)."""
    return by_id(registration)[method_id].handler(dict(params))


def dispatch(registration: ServerPluginRegistration, method_id: str,
             params: Mapping[str, Any]) -> Any:
    """Invoke through the host's declared-shape wall, as `WireService.dispatch`
    does (`apps/server/src/ordessa_server/wire/handlers.py:165-179`): a missing
    required or an undeclared extra param never reaches the handler."""
    descriptor = by_id(registration)[method_id]
    missing = descriptor.required_params - set(params)
    extra = set(params) - descriptor.required_params - descriptor.optional_params
    if missing or extra:
        reason = ("missing " + ", ".join(sorted(missing)) if missing else
                  "unexpected " + ", ".join(sorted(extra)))
        raise WireError("INVALID_REQUEST", f"params shape is invalid: {reason}")
    return descriptor.handler(dict(params))


def base_params(**overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "requestId": "req-create-0001", "slug": "code-reviewer",
        "displayName": "Code reviewer", "description": "Read-only reviewer.",
        "originScope": "public", "originOwner": "local",
        "operationKey": "op-create-0001", "expectedRowVersion": 0,
    }
    params.update(overrides)
    return params


def revision_params(definition_id: str, number: int = 1, **overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "requestId": f"req-publish-{number}-0001", "definitionId": definition_id,
        "revision": number, "roleBody": "Cite file and line for every finding.",
        "operationKey": f"op-publish-{number}", "expectedRowVersion": number,
    }
    params.update(overrides)
    return params


def created(registration: ServerPluginRegistration, **overrides: Any) -> dict[str, Any]:
    answer = call(registration, "assets.subagents.create", base_params(**overrides))
    return answer["definition"]


def refusal(excinfo: "pytest.ExceptionInfo[WireError]") -> WireError:
    error = excinfo.value
    assert isinstance(error, WireError), f"expected a typed WireError, got {error!r}"
    return error


def document(name: str = "code-reviewer",
             description: str = "Reviews code read-only.",
             body: str = "Cite file and line for every finding.") -> str:
    return "\n".join(["---", f"name: {name}", f"description: {description}",
                      "---", body, ""])


# -- 1: the descriptor and the registration are the contract's ---------------


def test_the_descriptor_declares_the_plugin_id_and_no_hard_dependency(tmp_path):
    plugin = NativeSubagentsServerPlugin()
    descriptor = plugin.descriptor()

    assert isinstance(descriptor, ServerPluginDescriptor)
    assert descriptor.id == PLUGIN_ID == "ordessa.assets-subagents"
    assert descriptor.display_name and descriptor.version
    assert descriptor.api_version == SERVER_PLUGIN_API_VERSION
    # Optional cooperation travels as ports, not as a startup dependency: this
    # domain installs without workspace / harness / permissions / profile.
    assert descriptor.requires == ()


def test_the_registration_is_the_contract_shape_with_one_provided_port(tmp_path):
    registration, plugin = build(data_root=tmp_path)

    assert isinstance(registration, ServerPluginRegistration)
    assert isinstance(registration.methods, tuple)
    assert registration.http_routes == ()
    assert registration.stream_routes == ()
    # T13 "产品启用唯一服务": exactly one port leaves this plugin, and it is the
    # service Profile/Chat/Settings consume — not a second resolver.
    assert set(registration.provided_ports) == {SERVICE_PORT}
    assert registration.provided_ports[SERVICE_PORT] is plugin.service
    assert registration.start_hooks == () and registration.stop_hooks == ()
    assert callable(registration.disposal)
    # Nothing is contributed to an open point this slice cannot honour.
    assert registration.contributions.contributions == ()


def test_every_method_id_is_a_valid_wire_id_and_owned_by_this_plugin(tmp_path):
    registration, _ = build(data_root=tmp_path)

    assert tuple(by_id(registration)) == ADVERTISED
    ids = [item.method_id for item in registration.methods]
    assert ids == list(ADVERTISED), f"method order is the declaration, got {ids}"
    for item in registration.methods:
        assert PLUGIN_METHOD_ID.fullmatch(item.method_id), item.method_id
        # The host refuses a descriptor whose owner is not the registering
        # plugin (`host.py:586`), so an honest owner is a precondition.
        assert item.owner == PLUGIN_ID
        assert isinstance(item.required_params, frozenset)
        assert isinstance(item.optional_params, frozenset)
        assert not (item.required_params & item.optional_params)
        assert item.availability is not None, (
            f"{item.method_id} carries no support claim: hello could only guess")
        # no identity may be requested as a param, on either half of the shape
        overlap = ((item.required_params | item.optional_params)
                   & SELF_REPORTED_IDENTITY_KEYS)
        assert overlap == frozenset(), f"{item.method_id} asks for {sorted(overlap)}"


@pytest.mark.parametrize("method_id", NOT_ADVERTISED)
def test_a_surface_this_composition_cannot_back_is_not_advertised(tmp_path, method_id):
    registration, _ = build(data_root=tmp_path)
    assert method_id not in by_id(registration), (
        f"{method_id} would be advertised with nothing behind it: "
        "`DefinitionService.approve_assignment_update`/`inspect_native` still "
        "raise NotImplementedError and no assignment store exists")


# -- 2: the readiness claims --------------------------------------------------


def test_reads_and_content_crud_claim_ready_and_resolvepreview_does_not(tmp_path):
    registration, _ = build(data_root=tmp_path)
    claims = {item.method_id: item.availability() for item in registration.methods}

    supported = [key for key in ADVERTISED if claims[key][0]]
    assert supported == [key for key in ADVERTISED if key != "assets.subagents.resolvePreview"]
    assert claims["assets.subagents.resolvePreview"] == (False, RESOLVE_PREVIEW_UNWIRED)


def test_the_unavailable_method_refuses_instead_of_answering_an_invented_set(tmp_path):
    registration, _ = build(data_root=tmp_path)

    with pytest.raises(WireError) as info:
        call(registration, "assets.subagents.resolvePreview",
             {"requestId": "req-resolve-0001", "target": {"harnessId": "claude"}})
    error = refusal(info)
    assert (error.family, error.details["internalCode"]) == (
        "CONFLICT_REFERENCE", errors.REFERENCE_UNRESOLVED)
    assert error.details["item"] == "assignments"
    # the refusal names the seams a reviewer has to close, not a generic failure
    assert ASSIGNMENT_SOURCE_PORT in error.details["detail"]
    assert CEILING_AUTHORITY_PORT in error.details["detail"]


def test_availability_never_gates_dispatch(tmp_path):
    """Order 097's rule: support state and existence are two questions. A method
    hello calls unsupported must still answer the request — with its own typed
    refusal — instead of becoming an unknown method."""
    registration, _ = build(data_root=tmp_path)
    descriptor = by_id(registration)["assets.subagents.resolvePreview"]
    assert descriptor.availability()[0] is False

    with pytest.raises(WireError) as info:
        dispatch(registration, "assets.subagents.resolvePreview",
                 {"requestId": "req-resolve-0002", "target": "claude"})
    assert refusal(info).details["internalCode"] == errors.REFERENCE_UNRESOLVED


# -- 3: the store root --------------------------------------------------------


def test_the_store_root_is_under_the_host_data_root_not_the_cwd(tmp_path):
    data_root = tmp_path / "data-root"
    registration, plugin = build(data_root=data_root)

    root = plugin.service.store.root
    assert root == data_root / DOMAIN_DIR / STORE_DIR
    # the only facts that named it: the host's data root and the plugin id
    assert root.is_relative_to(data_root)
    assert root.relative_to(data_root) == Path(DOMAIN_DIR) / STORE_DIR
    assert Path(DOMAIN_DIR).is_absolute() is False
    assert data_root in root.parents
    assert root != Path.cwd() / DOMAIN_DIR / STORE_DIR
    assert (data_root / DOMAIN_DIR / IMPORT_DIR) != root, (
        "the import location and the store must not be the same directory: the "
        "store refuses its own paths as import sources")
    assert registration.methods


def test_activation_writes_nothing_and_disposal_deletes_nothing(tmp_path):
    data_root = tmp_path / "data-root"
    registration, plugin = build(data_root=data_root)
    assert not data_root.exists(), (
        "a plugin that never served a request must not have created a directory")

    definition = created(registration)
    path = data_root / DOMAIN_DIR / STORE_DIR / "definitions"
    assert path.is_dir(), "the store wrote outside its own subtree"
    stored = list(path.rglob("definition.json"))
    assert [p.name for p in stored] == ["definition.json"]

    registration.disposal()
    assert plugin.service is None
    assert stored[0].is_file(), "unregistering deleted a stored definition (§C5: hide, not delete)"
    assert list(path.rglob("definition.json")) == stored


# -- 4: only the ports this domain uses ---------------------------------------


def test_the_plugin_reads_no_storage_port_it_does_not_use(tmp_path):
    ports = PortProbe({"server.instance_id": "box7"})
    build(data_root=tmp_path, ports=ports)
    read = set(ports.read)

    assert "server.instance_id" in read
    # file-backed store: the host's storage primitives stay untouched
    assert read.isdisjoint({"database", "idempotency", "credentials", "secret_store",
                            "objects", "notifier", "core.binding", "connectors",
                            "workspace.local_provider", "cursor.codec"}), sorted(read)
    # and the optional seams are asked for by name, never through a locator
    assert CONTEXT_PORT in read and IMPORT_ROOT_PORT in read


def test_a_deployment_without_any_composed_seam_still_builds(tmp_path):
    """R07: "缺 Profile/Chat 等可选 glue 时按各包语义工作"."""
    registration, _ = build(data_root=tmp_path, ports={})
    definition = created(registration)
    attested = DeploymentAttestation.for_instance("")

    assert definition["definitionId"]
    assert definition["serverScope"] == attested.authorization().server_scope.id
    assert definition["serverScope"] == "server:local"


def test_the_default_attestation_grants_no_permission_and_binds_no_project():
    attestation = DeploymentAttestation.for_instance("box7")
    authorization = attestation.authorization()

    assert authorization.principal.id == "local:box7"
    assert authorization.server_scope.id == "server:box7"
    assert authorization.verified_project is None
    assert attestation.permission_ceiling("local:box7", "server:box7") == frozenset()
    assert attestation.verify_principal("local:box7", server_scope="server:box7")
    assert not attestation.verify_principal("u:victim", server_scope="server:box7")
    # an unusable instance id degrades to the deployment's own label, never a
    # path or a user name
    assert DeploymentAttestation.for_instance("/home/maoqh/project").authorization(
    ).principal.id == "local:local"


# -- 5: G07 — identity is never self-reported ---------------------------------


@pytest.mark.parametrize("forged", [
    {"principal": "u:victim"}, {"serverScope": "server:other"},
    {"projectId": "proj-stolen"}, {"profileId": "prof-victim"},
    {"userId": "u:victim"}, {"sub": "u:victim"}, {"source": {"origin": "git-revision"}},
    {"PRINCIPAL": "u:victim"},
])
def test_a_self_reported_identity_is_refused_and_writes_nothing(tmp_path, forged):
    registration, plugin = build(data_root=tmp_path)
    params = {**base_params(), **forged}
    forged_key = next(iter(forged))

    with pytest.raises(WireError) as info:
        call(registration, "assets.subagents.create", params)
    error = refusal(info)
    assert (error.family, error.details["internalCode"]) == (
        "FORBIDDEN", errors.PERMISSION_EXCEEDS_CEILING)
    assert error.details["item"].lower() == forged_key.lower()
    assert "§C1" in error.details["detail"]
    assert plugin.service.store.list_definitions() == [], (
        "the forged request was refused *after* it wrote — that is the silent "
        "overwrite this guard exists to rule out")


def test_the_declared_shape_itself_excludes_an_identity_param(tmp_path):
    """Two layers, both real: even before the handler's own gate, the host's
    shape wall refuses a param the declaration never asked for."""
    registration, _ = build(data_root=tmp_path)

    with pytest.raises(WireError) as info:
        dispatch(registration, "assets.subagents.create",
                 {**base_params(), "principal": "u:victim"})
    error = refusal(info)
    assert error.family == "INVALID_REQUEST"
    assert "unexpected principal" in error.message


def test_only_the_server_attested_identity_reaches_the_stored_row(tmp_path):
    context = FakeRequestContext(principal="u:alice", server_scope="server:lab")
    plugin = NativeSubagentsServerPlugin(attestation=context)
    registration, _ = build(plugin, data_root=tmp_path)

    definition = created(registration)
    assert definition["serverScope"] == "server:lab"
    row = plugin.service.get_definition(definition["definitionId"])
    assert row.server_scope == "server:lab"
    # and the attested caller is the one the service authenticated: a replay
    # under a different principal does not read as this row's author
    assert plugin.service.authority.verify_principal(
        "u:alice", server_scope="server:lab") is True
    assert plugin.service.authority.verify_principal(
        "u:bob", server_scope="server:lab") is False


def test_a_project_owned_definition_needs_the_server_verified_binding(tmp_path):
    context = FakeRequestContext(verified_project="proj-alpha")
    plugin = NativeSubagentsServerPlugin(attestation=context)
    registration, _ = build(plugin, data_root=tmp_path)

    granted = created(registration, originScope="project", originOwner="proj-alpha")
    assert granted["originOwner"] == "proj-alpha"

    with pytest.raises(WireError) as info:
        created(registration, originScope="project", originOwner="proj-other",
                operationKey="op-create-0002", slug="other-reviewer")
    error = refusal(info)
    assert (error.family, error.details["internalCode"]) == (
        "FORBIDDEN", errors.PERMISSION_EXCEEDS_CEILING)
    assert len(plugin.service.list_definitions(include_archived=True)) == 1, (
        "the forged project wrote a row anyway")


def test_a_profile_owned_definition_refuses_until_the_profile_attests_it(tmp_path):
    context = FakeRequestContext(verified_project="proj-alpha")
    registration, plugin = build(
        NativeSubagentsServerPlugin(attestation=context), data_root=tmp_path)

    with pytest.raises(WireError) as info:
        created(registration, originScope="profile", originOwner="prof-1")
    error = refusal(info)
    assert error.details["internalCode"] == errors.PERMISSION_EXCEEDS_CEILING
    assert CONTEXT_PORT in error.details["detail"]
    assert plugin.service.list_definitions() == []


def test_a_published_revision_stamps_the_approver_server_side(tmp_path):
    context = FakeRequestContext()
    registration, plugin = build(
        NativeSubagentsServerPlugin(attestation=context), data_root=tmp_path)
    definition = created(registration)

    answer = call(registration, "assets.subagents.saveRevision",
                  revision_params(definition["definitionId"]))
    source = answer["revision"]["source"]
    assert source["approvedByPrincipal"] == "u:alice"
    assert source["origin"] == "user-upload"
    assert not source["originRef"].startswith(("/", "~", ".."))
    # the digest is the server's own read of the body it was handed
    body = answer["revision"]["roleBody"]
    from ordessa_assets_subagents.digest import bytes_digest
    assert source["contentDigest"] == bytes_digest(body.encode("utf-8"))
    stored = plugin.service.get_revision(definition["definitionId"], 1)
    assert decoder.revision_mapping(stored)["content_digest"] == (
        answer["revision"]["contentDigest"])


# -- 6: every mutation carries both concurrency facts -------------------------


@pytest.mark.parametrize("missing", ["operationKey", "expectedRowVersion"])
def test_a_mutation_without_both_keys_is_refused_naming_the_wire_param(
        tmp_path, missing):
    registration, plugin = build(data_root=tmp_path)
    params = {key: value for key, value in base_params().items() if key != missing}

    with pytest.raises(WireError) as info:
        call(registration, "assets.subagents.create", params)
    error = refusal(info)
    assert error.family == "INVALID_REQUEST"
    assert error.details["internalCode"] == errors.DEFINITION_INVALID
    # the wire's own camelCase name: the service would answer `operation_key`
    # (snake_case), so this assertion is what proves *this* guard fired.
    assert error.details["item"] == missing
    assert plugin.service.list_definitions() == []


@pytest.mark.parametrize("method_id,extra", [
    ("assets.subagents.archive", {"definitionId": "def_x"}),
    ("assets.subagents.restore", {"definitionId": "def_x"}),
    ("assets.subagents.clone", {"definitionId": "def_x"}),
    ("assets.subagents.approveImport", {"previewId": "imp_x", "selects": ["a.md"]}),
])
def test_every_mutation_surface_demands_both_keys(tmp_path, method_id, extra):
    registration, _ = build(data_root=tmp_path)
    params = {"requestId": "req-mutation-0001", **extra}

    with pytest.raises(WireError) as info:
        call(registration, method_id, params)
    error = refusal(info)
    assert error.details["internalCode"] == errors.DEFINITION_INVALID
    assert error.details["item"] in {"operationKey", "expectedRowVersion"}


def test_a_missing_key_on_publish_is_refused_before_the_row_is_read(tmp_path):
    registration, plugin = build(data_root=tmp_path)
    definition = created(registration)
    params = revision_params(definition["definitionId"])
    del params["operationKey"]

    with pytest.raises(WireError) as info:
        call(registration, "assets.subagents.saveRevision", params)
    assert refusal(info).details["item"] == "operationKey"
    assert plugin.service.get_definition(definition["definitionId"]).latest_revision == 0


def test_a_non_integer_row_version_is_a_typed_shape_refusal(tmp_path):
    registration, _ = build(data_root=tmp_path)

    with pytest.raises(WireError) as info:
        call(registration, "assets.subagents.create",
             base_params(expectedRowVersion="1"))
    assert refusal(info).family == "INVALID_REQUEST"


# -- 7: absent authority ------------------------------------------------------


def test_reads_and_content_crud_work_with_no_authorizer_wired(tmp_path):
    registration, plugin = build(data_root=tmp_path)
    definition = created(registration)

    published = call(registration, "assets.subagents.saveRevision",
                     revision_params(definition["definitionId"]))["revision"]
    assert published["revision"] == 1 and published["compilable"] is True

    listed = call(registration, "assets.subagents.list", {"requestId": "req-list-0001"})
    assert [item["definitionId"] for item in listed["items"]] == [definition["definitionId"]]

    read = call(registration, "assets.subagents.get",
                {"requestId": "req-get-0001", "definitionId": definition["definitionId"]})
    assert read["revision"]["definitionId"] == definition["definitionId"]

    archived = call(registration, "assets.subagents.archive", {
        "requestId": "req-archive-0001", "definitionId": definition["definitionId"],
        "operationKey": "op-archive-1", "expectedRowVersion": 2,
    })["definition"]
    assert archived["archived"] is True and archived["rowVersion"] == 3

    restored = call(registration, "assets.subagents.restore", {
        "requestId": "req-restore-0001", "definitionId": definition["definitionId"],
        "operationKey": "op-restore-1", "expectedRowVersion": 3,
    })["definition"]
    assert restored["archived"] is False and restored["rowVersion"] == 4

    cloned = call(registration, "assets.subagents.clone", {
        "requestId": "req-clone-0001", "definitionId": definition["definitionId"],
        "operationKey": "op-clone-1", "expectedRowVersion": 4, "slug": "reviewer-copy",
    })["definition"]
    assert cloned["definitionId"] != definition["definitionId"]
    assert len(plugin.service.list_definitions()) == 2


def test_a_permission_bearing_publish_refuses_naming_the_missing_seam(tmp_path):
    registration, plugin = build(data_root=tmp_path)
    definition = created(registration)
    params = revision_params(definition["definitionId"], requestedPermission="read-only")

    with pytest.raises(WireError) as info:
        call(registration, "assets.subagents.saveRevision", params)
    error = refusal(info)
    assert (error.family, error.details["internalCode"]) == (
        "FORBIDDEN", errors.PERMISSION_EXCEEDS_CEILING)
    assert error.details["item"] == "requestedPermission"
    assert CONTEXT_PORT in error.details["detail"] and CEILING_AUTHORITY_PORT in (
        error.details["detail"])
    assert plugin.service.get_definition(definition["definitionId"]).latest_revision == 0, (
        "an unadjudicated permission reached the store")


def test_a_composed_ceiling_authority_litigates_the_same_publish(tmp_path):
    """The seam is real, not a hard-coded no: with a context that carries a
    ceiling, the same publish goes through and the service decides."""
    context = FakeRequestContext(ceiling=("read-only",))
    registration, plugin = build(
        NativeSubagentsServerPlugin(attestation=context), data_root=tmp_path)
    definition = created(registration)

    published = call(registration, "assets.subagents.saveRevision",
                     revision_params(definition["definitionId"],
                                     requestedPermission="read-only"))
    assert published["revision"]["requestedPermission"] == "read-only"
    assert plugin.service.get_definition(definition["definitionId"]).latest_revision == 1


def test_the_harness_apply_path_is_absent_not_implemented(tmp_path):
    """No method here writes a native file or applies a set: `adapters/**` and
    the harness apply seam are not composed, so this face offers no apply verb at
    all (G16/G18/G19 stay open — `api-requests.md` SR-2)."""
    registration, _ = build(data_root=tmp_path)
    assert not [key for key in by_id(registration)
                if any(verb in key for verb in ("apply", "invoke", "run", "reset",
                                                "materialize", "mount"))]


# -- 8: §C5 refusals on the wire ----------------------------------------------


def test_a_stale_row_version_answers_conflict_version(tmp_path):
    registration, _ = build(data_root=tmp_path)
    definition = created(registration)

    with pytest.raises(WireError) as info:
        call(registration, "assets.subagents.saveRevision",
             revision_params(definition["definitionId"], expectedRowVersion=99))
    error = refusal(info)
    assert (error.family, error.details["internalCode"]) == (
        "CONFLICT_VERSION", errors.REVISION_STALE)
    assert error.details["item"] == definition["definitionId"]


def test_a_replayed_operation_key_returns_the_recorded_result(tmp_path):
    registration, plugin = build(data_root=tmp_path)
    first = created(registration)
    second = created(registration)

    assert second == first, "a replayed key must answer the receipt, not a new row"
    assert len(plugin.service.list_definitions()) == 1


def test_the_same_key_with_another_payload_is_a_conflict(tmp_path):
    """Same scope, same key, different payload: §C1's "同键不同 payload 拒绝". The
    receipt answers a conflict instead of writing a second definition."""
    registration, plugin = build(data_root=tmp_path)
    created(registration)

    with pytest.raises(WireError) as info:
        created(registration, description="A different body of work.")
    error = refusal(info)
    assert (error.family, error.details["internalCode"]) == (
        "CONFLICT_REQUEST", errors.ASSIGNMENT_CONFLICT)
    assert error.details["item"] == "operation_key"
    assert len(plugin.service.list_definitions()) == 1


def test_an_unknown_preview_is_queryable_not_a_success(tmp_path):
    registration, _ = build(data_root=tmp_path)

    with pytest.raises(WireError) as info:
        call(registration, "assets.subagents.approveImport", {
            "requestId": "req-approve-0001", "previewId": "imp_never_existed",
            "selects": ["a.md"], "operationKey": "op-approve-1",
            "expectedRowVersion": 0,
        })
    error = refusal(info)
    assert (error.family, error.details["internalCode"]) == (
        "OUTCOME_UNKNOWN", errors.OPERATION_UNKNOWN)
    assert error.details["retryable"] is True, (
        "an unknown outcome must stay re-queryable (§C5)")


def test_a_missing_definition_is_a_typed_refusal_not_an_empty_answer(tmp_path):
    registration, _ = build(data_root=tmp_path)

    with pytest.raises(WireError) as info:
        call(registration, "assets.subagents.get",
            {"requestId": "req-get-0002", "definitionId": "def_absent000000000000"})
    error = refusal(info)
    assert error.family == "INVALID_REQUEST"
    assert error.details["internalCode"] == errors.DEFINITION_INVALID
    assert "no such definition" in error.details["detail"]

    listed = call(registration, "assets.subagents.list", {"requestId": "req-list-0002"})
    assert listed == {"items": [], "nextCursor": None}


def test_every_c5_code_the_domain_can_raise_has_a_wire_family():
    """§C5's list is closed and this face projects all of it: a code with no row
    would surface as the `UNAVAILABLE` fall-through, which is a lie about a
    refusal the domain actually answered."""
    from ordessa_assets_subagents import wire as wire_module
    from server_plugin_api import FAMILIES

    assert set(errors.ERROR_CODES) == set(wire_module.C5_ERROR_FAMILIES)
    unknown = [code for code in wire_module.C5_ERROR_FAMILIES if code not in errors.ERROR_CODES]
    assert unknown == []
    unbacked = [family for family in wire_module.C5_ERROR_FAMILIES.values()
                if family not in FAMILIES]
    assert unbacked == []


# -- 9: the import face -------------------------------------------------------


def test_import_preview_and_approval_read_only_the_plugins_own_root(tmp_path):
    data_root = tmp_path / "data-root"
    registration, plugin = build(data_root=data_root)
    approved = data_root / DOMAIN_DIR / IMPORT_DIR / "library"
    approved.mkdir(parents=True)
    (approved / "reviewer.md").write_text(document(), encoding="utf-8")

    preview = call(registration, "assets.subagents.importPreview", {
        "requestId": "req-preview-0001", "path": "library/reviewer.md",
    })["preview"]
    assert preview["files"][0]["relativePath"] == "reviewer.md"
    assert preview["files"][0]["selectable"] is True
    assert "sourcePath" not in preview, "an absolute host path never leaves the server"

    rows = call(registration, "assets.subagents.approveImport", {
        "requestId": "req-approve-0002", "previewId": preview["previewId"],
        "selects": ["reviewer.md"], "operationKey": "op-approve-2",
        "expectedRowVersion": 0,
    })["definitions"]
    assert [row["slug"] for row in rows] == ["code-reviewer"]
    assert len(plugin.service.list_definitions()) == 1
    # the approval step is the only writer: a preview wrote nothing
    stored = list((data_root / DOMAIN_DIR / STORE_DIR / "definitions").rglob(
        "definition.json"))
    assert len(stored) == 1


def test_an_import_root_inside_the_user_home_is_declared_unsupported(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("ordessa_assets_subagents.wire._home", lambda: home)
    registration, _ = build(data_root=home / ".local/share/ordessa")

    claims = by_id(registration)
    for method_id in ("assets.subagents.importPreview", "assets.subagents.approveImport"):
        assert claims[method_id].availability() == (False, IMPORT_ROOT_UNAPPROVED)
    # and the refusal, not a created directory in the user's tree, is what runs
    with pytest.raises(WireError) as info:
        call(registration, "assets.subagents.importPreview",
             {"requestId": "req-preview-0002", "path": "a.md"})
    assert refusal(info).details["internalCode"] == errors.DEFINITION_INVALID
    assert not (home / ".local/share/ordessa").exists()


def test_an_escaping_import_path_is_refused(tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "secret.md").write_text(document(name="secret-one"), encoding="utf-8")
    registration, _ = build(data_root=tmp_path / "data-root")

    with pytest.raises(WireError) as info:
        call(registration, "assets.subagents.importPreview", {
            "requestId": "req-preview-0003", "path": "../elsewhere/secret.md",
        })
    error = refusal(info)
    assert error.details["internalCode"] == errors.DEFINITION_INVALID
    assert "escapes" in error.details["detail"] or "approved import root" in (
        error.details["detail"])


def test_an_unknown_origin_scope_is_refused_before_any_row(tmp_path):
    registration, plugin = build(data_root=tmp_path)

    with pytest.raises(WireError) as info:
        created(registration, originScope="everyone")
    error = refusal(info)
    assert error.details["internalCode"] == errors.DEFINITION_INVALID
    assert error.details["item"] == "originScope"
    assert plugin.service.list_definitions() == []


def test_the_registration_face_imports_only_the_contract_and_its_own_domain():
    """AGENTS.md rule 3, locked inside this slice: `plugin.py` and `wire.py` may
    name the public contract package, the standard library and this package —
    never the host, the harness, the compat core, the product or another
    plugin's modules. The seams they defer to are port *names*, resolved by the
    host, so no cross-plugin import is needed to reach one.

    (`tests/test_boundaries_t03b.py` owns the package-wide allow-list; this lock
    covers the two files this task added, so the rule holds even while that
    file's list is being widened for `server_plugin_api`.)"""
    import ast

    src = Path(__file__).resolve().parents[1] / "src" / "ordessa_assets_subagents"
    allowed_roots = {"server_plugin_api", "ordessa_assets_subagents"}
    offenders: dict[str, list[str]] = {}
    for name in ("plugin.py", "wire.py"):
        tree = ast.parse((src / name).read_text(encoding="utf-8"))
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
        bad = sorted(root for root in roots
                     if root not in allowed_roots and root not in sys.stdlib_module_names)
        if bad:
            offenders[name] = bad
    assert offenders == {}, (
        f"the registration face reached outside the contract and its own domain: {offenders}")


# -- 10: disposal and re-activation -------------------------------------------


def test_a_second_activation_over_the_same_root_reads_the_library_back(tmp_path):
    data_root = tmp_path / "data-root"
    first, plugin_a = build(data_root=data_root)
    definition = created(first)
    call(first, "assets.subagents.saveRevision",
         revision_params(definition["definitionId"]))
    service_a = plugin_a.service
    first.disposal()
    first.disposal()  # exactly once is the host's rule; a second call is harmless

    second, plugin_b = build(data_root=data_root)
    listed = call(second, "assets.subagents.list",
                  {"requestId": "req-list-0003", "includeArchived": True})["items"]
    assert [row["definitionId"] for row in listed] == [definition["definitionId"]]
    assert listed[0]["latestRevision"] == 1
    assert listed[0]["rowVersion"] == 2
    assert plugin_b.service is not service_a
    # the receipts survived too: a replayed key over the reopened store still
    # answers the recorded result instead of writing a second row
    replayed = created(second)
    assert replayed["definitionId"] == definition["definitionId"]
    assert len(plugin_b.service.list_definitions(include_archived=True)) == 1


def test_disposal_closes_nothing_another_domain_owns(tmp_path):
    """The teardown drops this plugin's own references. An object handed in by
    someone else (the request context, an import root) must stay exactly as it
    was — disposal owns no other domain's lifecycle."""
    class ForeignContext(FakeRequestContext):
        closed = False

        def close(self) -> None:
            self.closed = True

    foreign = ForeignContext()
    registration, plugin = build(
        NativeSubagentsServerPlugin(attestation=foreign), data_root=tmp_path,
    )
    created(registration)
    registration.disposal()

    assert foreign.closed is False, "disposal reached outside this plugin"
    assert foreign.authorization().principal.id == "u:alice"
    assert plugin.service is None


# -- 11: the authorizer wiring arrives by injection (§SR-13b row 4 / §SR-15) --

#: The two collaborators §SR-15 option 3 puts on the composition root: this
#: plugin may not import Q5's provider package to learn the port name or the
#: authority's conflict types, so they come in as inputs and their absence is a
#: named gap, never a stub.
AUTHORIZER_COLLABORATORS_EXPECTED = ("authorizer_port_name",
                                     "authorizer_conflict_types")


def test_an_uninjected_authorizer_wiring_is_reported_as_missing(tmp_path):
    """The honest default: a plugin that was given nothing says so.

    No stub authorizer, no silently-passing port name that would let a health
    check read this face as "authority live". The gap list is the mechanism
    `apply.missing_production_collaborators()` already uses, before *and* after
    `build()`.
    """
    plugin = NativeSubagentsServerPlugin()
    assert plugin.missing_production_collaborators() == AUTHORIZER_COLLABORATORS_EXPECTED
    registration, built = build(plugin, data_root=tmp_path)
    assert registration.methods, "the face stopped working: the probe proved nothing"
    assert built.missing_production_collaborators() == AUTHORIZER_COLLABORATORS_EXPECTED
    bare = SubagentsWire(service=built.service,
                          attestation=DeploymentAttestation.for_instance("probe"),
                          import_root=tmp_path / "i", owner=PLUGIN_ID)
    assert bare.seam_wiring() == {"port_name": None, "conflict_types": ()}, (
        "an uninjected face that fills in a port name itself is the "
        "silently-passing default this lock exists to catch")
    assert bare.missing_production_collaborators() == AUTHORIZER_COLLABORATORS_EXPECTED


def test_the_authorizer_wiring_is_forwarded_verbatim_and_not_invented(tmp_path):
    """Injected → the gaps close, and the values that reach the seam are the
    ones the composition named: no re-spelling, no widening, no default. The
    counter-check is in the test above: uninjected stays `None` here, because
    the seam's documented default is a *name*, and a wire face that filled it in
    would look like a wired authority."""
    class CorrelationLike(Exception):
        pass

    class VersionLike(Exception):
        pass

    plugin = NativeSubagentsServerPlugin(
        authorizer_port_name="permissions.authorizer@1",
        authorizer_conflict_types=(CorrelationLike, VersionLike))
    assert plugin.missing_production_collaborators() == ()
    _registration, built = build(plugin, data_root=tmp_path)
    assert built.missing_production_collaborators() == ()

    wire = SubagentsWire(service=built.service, attestation=DeploymentAttestation(
        scopes.AuthorizationContext.issued_by_service(scopes.Principal("u"),
                                                      scopes.ServerScope("s"))),
        import_root=tmp_path / "imports", owner=PLUGIN_ID,
        authorizer_port_name="permissions.authorizer@1",
        authorizer_conflict_types=(CorrelationLike, VersionLike))
    assert wire.missing_production_collaborators() == ()
    wiring = wire.seam_wiring()
    assert wiring["port_name"] == "permissions.authorizer@1"
    assert wiring["conflict_types"] == (CorrelationLike, VersionLike), (
        "the seam must get exactly the injected types, in order")


def test_an_empty_port_name_injection_is_a_gap_not_a_default(tmp_path):
    """`authorizer_port_name=""` is the host *saying* "no port": the wire keeps
    it as an open collaborator instead of quietly substituting the literal."""
    plugin = NativeSubagentsServerPlugin(authorizer_port_name="   ")
    assert plugin.missing_production_collaborators() == AUTHORIZER_COLLABORATORS_EXPECTED
    registration, built = build(plugin, data_root=tmp_path)
    assert built.missing_production_collaborators() == AUTHORIZER_COLLABORATORS_EXPECTED
    # and what the plugin holds is the blank the host wrote, not the documented
    # literal: the seam then refuses on a name it cannot speak.
    assert plugin._authorizer_port_name == "   ", (
        "the face normalised a blank into the default, which is exactly the "
        "silently-passing wiring this lock forbids")
    assert SubagentsWire(
        service=built.service, attestation=DeploymentAttestation.for_instance("probe"),
        import_root=tmp_path / "i", owner=PLUGIN_ID,
        authorizer_port_name=plugin._authorizer_port_name,
    ).seam_wiring()["port_name"] == "   "
    assert registration.methods


def test_the_missing_seam_refusal_names_the_missing_collaborators(tmp_path):
    """Lock 7, extended: the refusal that already names the ports must also name
    the wiring the composition did not inject, so the operator has one line to
    act on instead of a seam to reverse-engineer."""
    registration, _plugin = build(data_root=tmp_path)
    definition = created(registration)
    with pytest.raises(WireError) as info:
        call(registration, "assets.subagents.saveRevision",
             revision_params(definition["definitionId"],
                             requestedPermission="read-only"))
    detail = refusal(info).details["detail"]
    assert CONTEXT_PORT in detail and CEILING_AUTHORITY_PORT in detail
    for collaborator in AUTHORIZER_COLLABORATORS_EXPECTED:
        assert collaborator in detail, (collaborator, detail)
    assert "is not injected" in detail, detail


def test_a_wired_authorizer_wiring_adds_no_permission_of_its_own(tmp_path):
    """Injecting the two facts does not make the ceiling authority composed:
    `ceiling_authority_wired` is still decided by the request-context port, so
    a deployment that injected the names but wired no authority keeps refusing
    (§SR-6: an absent authority is never a permissive default)."""
    plugin = NativeSubagentsServerPlugin(
        authorizer_port_name="permissions.authorizer@1",
        authorizer_conflict_types=(ValueError,))
    registration, _built = build(plugin, data_root=tmp_path)
    definition = created(registration)
    with pytest.raises(WireError) as info:
        call(registration, "assets.subagents.saveRevision",
             revision_params(definition["definitionId"],
                             requestedPermission="read-only"))
    error = refusal(info)
    assert (error.family, error.details["internalCode"]) == (
        "FORBIDDEN", errors.PERMISSION_EXCEEDS_CEILING)
    assert "authorizer_conflict_types" not in error.details["detail"], (
        "an injected collaborator must not be reported missing: "
        + error.details["detail"])
