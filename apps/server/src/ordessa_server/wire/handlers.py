"""wire/1 method dispatch — the contract's edge, and the TRANSITIONAL core adapter.

Since the plugin-host boundary (batch 1), the one dispatch table is the plugin
host's method registry: shape, handler, availability and owner travel as one
atomic descriptor, and `dispatch`/`hello` read only from it. This module now
carries two things:

- the host-owned `server.hello` method, and
- `WireService` acting as the **transitional core adapter** (`ordessa.transition-core`):
  the business domains that have not yet moved behind the plugin boundary are
  registered through the registry by `TransitionCorePlugin`, here, exactly
  once. This adapter is a bridge for wire/1 stability, NOT evidence that
  business ownership has moved; its remaining domains are listed in
  `docs/server-host-baseline.md` and each later batch retires a slice.
  The Workspace domain already moved: see `plugin_host/workspace_plugin.py`.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import re
import shutil
import mimetypes
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping

from ordessa_server.errors import ServerError
from ordessa_server.execution import CancelOutcome
from ordessa_server.execution.artifact_store import ArtifactStoreError
from ordessa_server.records import canonical, digest, reject_sensitive_keys
from ordessa_server.wire.envelope import CursorCodec
from ordessa_server.wire.errors import WireError, family_for
from ordessa_server.accounts.records import account_view
from ordessa_server.assets.records import asset_view
from ordessa_server.hooks.records import hook_view
from ordessa_server.hooks.triggers import trigger_view
from ordessa_server.wire.projection import (
    event_frame,
    execution_state,
    profile_record,
    session_record,
)


WIRE_VERSION = "wire/1"

#: The transitional adapter's declared param shapes. The plugin host's method
#: registry is the one live table (shape + handler + availability + owner);
#: this literal is what `TransitionCorePlugin` declares from, and order-097's
#: gates compare it against the registry so a declaration that never reached
#: the registry stays visible. The five `workspaces.*` shapes moved with the
#: Workspace plugin (`plugin_host/workspace_plugin.py`).
_PARAM_SHAPES = {
    "server.hello": ({"clientVersions", "clientPresentationSupports"}, set()),
    "executions.list": ({"requestId"}, {"limit"}),
    "executions.get": ({"requestId", "executionId"}, set()),
    "acp.channel.open": ({"harnessId", "projectId"}, {"requestId"}),
    "acp.channel.release": ({"connectionId"}, {"requestId"}),
    "profiles.list": ({"includeArchived"}, set()),
    "profiles.create": ({"requestId", "displayName", "harness"}, {"credentialId"}),
    "profiles.update": ({"requestId", "profileId", "expectedVersion", "displayName"}, set()),
    "profiles.updateConfig": ({"requestId", "profileId", "expectedVersion", "values"}, set()),
    "profiles.archive": ({"requestId", "profileId", "expectedVersion"}, set()),
    "profiles.clone": ({"requestId", "profileId", "displayName"}, {"harness"}),
    "profiles.memory": ({"requestId", "profileId"}, set()),
    "profiles.subagentGrants": ({"profileId"}, set()),
    "profiles.grantSubagent": ({"requestId", "profileId", "childProfileId"}, set()),
    "profiles.revokeSubagent": ({"requestId", "profileId", "childProfileId"}, set()),
    "profiles.setPermissions": (
        {"requestId", "profileId", "expectedVersion", "preset", "rules"}, set()),
    "providerModels.list": ({"includeArchived"}, set()),
    "providerModels.create": (
        {"requestId", "displayName", "harness", "provider", "credentialId",
         "configuration", "models"},
        {"provenance"},
    ),
    "providerModels.update": (
        {"requestId", "providerModelId", "expectedVersion", "displayName", "credentialId",
         "configuration", "models"},
        {"provenance"},
    ),
    "providerModels.archive": (
        {"requestId", "providerModelId", "expectedVersion"}, set(),
    ),
    "assets.list": (set(), set()),
    "assets.publishSkill": ({"requestId", "assetId", "revision", "sourcePath"}, set()),
    "assets.publishMcp": ({"requestId", "assetId", "revision", "definition"}, set()),
    "assets.publishPlugin": ({"requestId", "assetId", "revision", "sourcePath"}, set()),
    "assets.bind": ({"requestId", "profileId", "assetId"}, {"revision", "enabled"}),
    "assets.unbind": ({"requestId", "profileId", "assetId"}, set()),
    "assets.bindings": ({"profileId"}, set()),
    "assets.syncCatalog": ({"requestId", "sourceId", "sourcePath"}, set()),
    "assets.catalog": ({"sourceId"}, set()),
    "assets.installFromCatalog": ({"requestId", "sourceId", "entryName", "revision"}, set()),
    "assets.probe": ({"definition"}, set()),
    "hooks.list": ({"requestId"}, {"family"}),
    "hooks.create": ({"requestId", "family", "name", "model"}, {"source"}),
    "hooks.update": ({"requestId", "hookId", "model"}, set()),
    "hooks.setEnabled": ({"requestId", "hookId", "enabled"}, set()),
    "hooks.delete": ({"requestId", "hookId"}, set()),
    "hooks.triggers": ({"requestId"}, {"hookId", "limit"}),
    "accounts.list": (set(), set()),
    "accounts.create": ({"requestId", "harness", "accountIdentifier"}, set()),
    "accounts.bind": ({"requestId", "profileId", "expectedVersion", "accountId"}, set()),
    "accounts.importAsset": ({"requestId", "accountId", "sourcePath"}, set()),
    "providerModels.probeModels": (
        {"requestId", "baseUrl"}, {"credentialId", "provenance"},
    ),
    "providerModels.probeConnection": (
        {"requestId", "baseUrl"}, {"credentialId"},
    ),
    "providerArtifacts.list": (
        {"harness"}, set(),
    ),
    "providerArtifacts.install": (
        {"requestId", "harness", "version", "sourceToken", "digest"}, set(),
    ),
    "providerArtifacts.rollback": (
        {"requestId", "harness", "version"}, set(),
    ),
    "usage.aggregate": (
        {"sessions"}, {"since", "until"},
    ),
    "usage.export": (
        {"sessions"}, {"format"},
    ),
    "config.describe": ({"profileId", "workspaceId"}, set()),
    "config.resolve": ({"profileId", "workspaceId", "overrides"}, set()),
    "sessions.list": ({"includeArchived"}, {"workspaceId", "page"}),
    "sessions.update": (
        {"requestId", "sessionId", "expectedVersion"},
        {"displayName", "pinned", "workspaceId"},
    ),
    "sessions.archive": ({"requestId", "sessionId", "expectedVersion"}, set()),
    "sessions.switchProfile": (
        {"requestId", "sessionId", "profileId", "expectedVersion"}, set(),
    ),
    "sessions.createAndSend": (
        {"requestId", "workspaceId", "profileId", "overrides", "message"}, set(),
    ),
    "sessions.send": ({"requestId", "sessionId", "overrides", "message"}, set()),
    "sendOutcome.query": ({"requestId"}, set()),
    "queue.get": ({"sessionId"}, set()),
    "queue.withdraw": ({"requestId", "sessionId", "itemId", "expectedVersion"}, set()),
    "runs.stop": ({"requestId", "sessionId", "executionId"}, set()),
    "approvals.decide": (
        {"requestId", "approvalId", "expectedVersion", "decision", "scope"}, set(),
    ),
    "history.snapshot": ({"sessionId"}, {"cursor", "page"}),
}


def _require(params: Mapping[str, Any], *names: str) -> None:
    missing = [name for name in names if name not in params]
    if missing:
        raise WireError("INVALID_REQUEST", f"params is missing {', '.join(missing)}")


def _slug(value: Any, name: str) -> str:
    """A lowercase slug: the asset id every store and binding shares."""
    import re as _re

    if not isinstance(value, str) or _re.match(r"[a-z0-9][a-z0-9._-]{0,63}\Z", value) is None:
        raise WireError("INVALID_REQUEST", f"{name} must be a lowercase slug")
    return value


def _positive(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise WireError("INVALID_REQUEST", f"{name} must be a positive integer")
    return value


def _bounded(value: Any, name: str, limit: int = 4096) -> str:
    if not isinstance(value, str) or not (0 < len(value) <= limit):
        raise WireError("INVALID_REQUEST", f"{name} must be a bounded string")
    return value


def _request_id(value: Any) -> str:
    result = _bounded(value, "requestId")
    if len(result) < 8:
        raise WireError("INVALID_REQUEST", "requestId must contain at least 8 characters")
    return result


def _version(value: Any, name: str = "expectedVersion") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not (0 <= value <= 2**53 - 1):
        raise WireError("INVALID_REQUEST", f"{name} must be a non-negative safe integer")
    return value


def _overrides(params: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    value = params.get("overrides")
    if value is None:
        return None
    if not isinstance(value, list):
        raise WireError("INVALID_REQUEST", "overrides must be a list of control assignments")
    for item in value:
        if (not isinstance(item, Mapping) or set(item) != {"controlId", "value"}
                or not isinstance(item["controlId"], str)):
            raise WireError("INVALID_REQUEST", "each override needs controlId and value")
    reject_sensitive_keys(value)
    reject_sensitive_keys({item["controlId"]: item["value"] for item in value})
    return [dict(item) for item in value]


def _assignments(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise WireError("INVALID_REQUEST", f"{name} must be a list of control assignments")
    result = []
    for item in value:
        if (not isinstance(item, Mapping) or set(item) != {"controlId", "value"}
                or not isinstance(item["controlId"], str) or not item["controlId"]):
            raise WireError("INVALID_REQUEST", f"each {name} item needs controlId and value")
        result.append(dict(item))
    reject_sensitive_keys(result)
    reject_sensitive_keys({item["controlId"]: item["value"] for item in result})
    return result


def _models(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise WireError("INVALID_REQUEST", "models must be a list")
    result = []
    allowed = {"modelId", "displayName", "availability", "unavailableReason"}
    for item in value:
        if not isinstance(item, Mapping) or set(item) != allowed:
            raise WireError("INVALID_REQUEST", "each model has an invalid shape")
        availability = item["availability"]
        reason = item["unavailableReason"]
        if availability not in {"unknown", "available", "unavailable"}:
            raise WireError("INVALID_REQUEST", "model availability is invalid")
        if reason is not None and not isinstance(reason, str):
            raise WireError("INVALID_REQUEST", "unavailableReason must be a string or null")
        result.append({
            "modelId": _bounded(item["modelId"], "modelId", 256),
            "displayName": _bounded(item["displayName"], "displayName", 256),
            "availability": availability, "unavailableReason": reason,
        })
    return result


#: The artifact store speaks its own codes; the wire speaks twelve families.
#: These are the store's facts that a client can act on, so they must not
#: arrive as a 500 - and the internal code stays in `details` because the
#: projection is a narrowing, not a replacement of what went wrong.
#: `CONFLICT_REQUEST` for an already-installed version follows the precedent
#: `ENTERPRISE_STATE_CONFLICT` sets in errors.py: the world is not the shape
#: the request assumed.
_ARTIFACT_FAMILIES = {
    "ARTIFACT_VERSION_MISSING": "NOT_FOUND",
    "ARTIFACT_SOURCE_MISSING": "NOT_FOUND",
    "ARTIFACT_VERSION_EXISTS": "CONFLICT_REQUEST",
}


#: The asset/catalog surface answers typed refusals with `CatalogError(code, message)`
#: and everything else with whatever Python raised. Order 147 (`AUD-B-037`) is the
#: record of what the five copies of `except Exception as refusal` did with that:
#: they wrote `INVALID_REQUEST: <ClassName>: <str(exc)>`, so a permission or disk
#: failure on the Server told the client its request was illegal, and the raw text
#: carried absolute paths (including the data root) out over the wire.
_LOG = logging.getLogger(__name__)
_CODE_SHAPE = re.compile(r"[A-Z][A-Z0-9_]{2,127}")


def _asset_refusal(exc: BaseException) -> WireError:
    """One path for the asset surface's refusals - five copies were five truths.

    A code that is shaped like a registered domain code keeps its own words: the
    family `errors.family_for` assigns it, the same `code: message` text the
    surface has always sent, and `details.internalCode` so the precise code is
    structured rather than embedded prose (the shape order 115 fixed).

    Anything else is a Server-side fault, not the caller's mistake: it answers
    `UNAVAILABLE` with a machine-readable `internalCode` of the exception *type*
    only. The raw text goes to the Server log, never to the client - which is
    what `_safe_code` does in `execution/sidecar_backend.py`.
    """
    code = getattr(exc, "code", None)
    if isinstance(code, str) and _CODE_SHAPE.fullmatch(code):
        message = str(getattr(exc, "message", "the asset surface refused the request"))
        return WireError(family_for(code), f"{code}: {message}",
                         {"internalCode": code, "retryable": family_for(code) == "UNAVAILABLE"})
    _LOG.warning("asset surface raised %s: %s", type(exc).__name__, exc)
    return WireError("UNAVAILABLE", "the asset surface could not complete the request",
                     {"internalCode": type(exc).__name__, "retryable": True})


def _artifact_error(exc: ArtifactStoreError) -> WireError:
    return WireError(
        _ARTIFACT_FAMILIES.get(exc.code, "INVALID_REQUEST"),
        str(exc),
        {"internalCode": exc.code},
    )


#: What a user can actually do about each send blocker, in wire terms that exist
#: today. A recovery state has no entry because no method in the 64 clears it —
#: inventing one is a product decision (approval queue), not a projection detail,
#: and "there is nothing you can do from here" is the honest answer (order 117).
_BINDING_ACTIONS: Mapping[str, tuple[str, ...]] = {
    "CREDENTIAL_NOT_FOUND": ("provision_the_credential_on_this_host",
                             "point_the_model_at_an_available_credential"),
    # Order 152 (`R-0080`, ACC-R5-4): the identity resolves and the kind is right,
    # but this host cannot open the secret - which the freeze path alone cannot see.
    "CREDENTIAL_NOT_RESOLVABLE": ("provision_the_credential_on_this_host",
                                  "point_the_model_at_an_available_credential"),
    "CREDENTIAL_RESOLVABILITY_UNKNOWN": ("provision_the_credential_on_this_host",),
    "PROVIDER_MODEL_NOT_FOUND": ("choose_an_available_model",),
    "PROVIDER_MODEL_UNUSABLE": ("choose_an_available_model",),
    "PROVIDER_MODEL_REFERENCE_MISSING": ("choose_an_available_model",),
    "MODEL_UNAVAILABLE": ("choose_an_available_model",),
    "PROFILE_CONFIGURATION_INVALID": ("choose_a_model",),
}


#: Which directory a model-slot reference points at. One string, and the gate
#: in `tests/server/test_config_describe_slots_125.py` is the thing that keeps
#: `model_configs` a single table rather than a guess.
SLOT_TABLE = "providerModels"


def _model_reference_list(value: Any) -> list[dict[str, str]]:
    """Every Provider/Model reference inside a control value, in document order.

    A control may hold one reference (the shape order 60 shipped) or a list of
    them (R-0013's v2 multi-slot). This mirrors
    `model_configs.service._model_references`, and a gate compares the two on
    fixed samples so the copy cannot drift silently.
    """
    found: list[dict[str, str]] = []
    if isinstance(value, Mapping):
        if isinstance(value.get("providerId"), str) and isinstance(value.get("modelId"), str):
            found.append({"providerId": str(value["providerId"]),
                          "modelId": str(value["modelId"])})
        for nested in value.values():
            found += _model_reference_list(nested)
    elif isinstance(value, list):
        for nested in value:
            found += _model_reference_list(nested)
    return found


class _CallReader:
    """One wire call's worth of object reads, de-duplicated by digest (order 147).

    `AUD-B-040` measured `profiles.list` walking the model resolution once *per
    row*: with 40 profiles over a single provider whose model list is 285 KB,
    one call issued 80 `objects.read`s and re-hashed 11 MB, because `read()`
    verifies the digest by re-hashing the whole object and nothing memoised it.
    Memoising on the digest does not weaken that check - the digest *is* the
    immutability argument - and it is scoped to one call, so no projection can
    outlive the composition that produced it.
    """

    def __init__(self, objects: Any) -> None:
        self._objects = objects
        self._bytes: dict[str, bytes] = {}
        self._parsed: dict[str, Any] = {}
        self._indexes: dict[str, dict[str, Any]] = {}
        self._records: dict[str, Any] = {}

    def read(self, digest: str) -> bytes:
        cached = self._bytes.get(digest)
        if cached is None:
            cached = self._objects.read(digest)
            self._bytes[digest] = cached
        return cached

    def parsed(self, digest: str) -> Any:
        cached = self._parsed.get(digest)
        if cached is None:
            cached = json.loads(self.read(digest))
            self._parsed[digest] = cached
        return cached

    def index(self, digest: str, *, section: str, field: str) -> dict[str, Any]:
        """`modelId -> model`, built once per object instead of a linear scan per row."""
        cached = self._indexes.get(digest)
        if cached is None:
            items = self.parsed(digest).get(section) or []
            cached = {str(item[field]): item for item in items if field in item}
            self._indexes[digest] = cached
        return cached

    def record(self, provider_id: str, fetch: Callable[[], Any]) -> Any:
        if provider_id not in self._records:
            self._records[provider_id] = fetch()
        return self._records[provider_id]


TRANSITIONAL_ADAPTER_ID = "ordessa.transition-core"
HOST_OWNER_ID = "server.host"

#: The transitional adapter's method declarations: wire id -> the WireService
#: attribute that handles it, in the exact order the old `_handlers` dict
#: listed them (minus the five `workspaces.*` methods, which moved to the
#: Workspace plugin). `TransitionCorePlugin` turns each row into one atomic
#: descriptor on the registry — this mapping is a declaration, not a table.
_ADAPTER_METHODS: dict[str, str] = {
    "server.hello": "hello",
    "executions.list": "executions_list",
    "executions.get": "executions_get",
    "acp.channel.open": "acp_channel_open",
    "acp.channel.release": "acp_channel_release",
    "profiles.list": "profiles_list",
    "profiles.create": "profiles_create",
    "profiles.update": "profiles_update",
    "profiles.updateConfig": "profiles_update_config",
    "profiles.archive": "profiles_archive",
    "profiles.clone": "profiles_clone",
    "profiles.setPermissions": "profiles_set_permissions",
    "profiles.memory": "profiles_memory",
    "profiles.subagentGrants": "profiles_subagent_grants",
    "profiles.grantSubagent": "profiles_grant_subagent",
    "profiles.revokeSubagent": "profiles_revoke_subagent",
    "providerModels.list": "provider_models_list",
    "providerModels.create": "provider_models_create",
    "providerModels.update": "provider_models_update",
    "providerModels.archive": "provider_models_archive",
    "providerModels.probeModels": "provider_models_probe_models",
    "assets.list": "assets_list",
    "assets.publishSkill": "assets_publish_skill",
    "assets.publishMcp": "assets_publish_mcp",
    "assets.publishPlugin": "assets_publish_plugin",
    "assets.bind": "assets_bind",
    "assets.unbind": "assets_unbind",
    "assets.bindings": "assets_bindings",
    "assets.syncCatalog": "assets_sync_catalog",
    "assets.catalog": "assets_catalog",
    "assets.installFromCatalog": "assets_install_from_catalog",
    "assets.probe": "assets_probe",
    "hooks.list": "hooks_list",
    "hooks.create": "hooks_create",
    "hooks.update": "hooks_update",
    "hooks.setEnabled": "hooks_set_enabled",
    "hooks.delete": "hooks_delete",
    "hooks.triggers": "hooks_triggers",
    "accounts.list": "accounts_list",
    "accounts.create": "accounts_create",
    "accounts.bind": "accounts_bind",
    "accounts.importAsset": "accounts_import_asset",
    "providerModels.probeConnection": "provider_models_probe_connection",
    "providerArtifacts.list": "provider_artifacts_list",
    "providerArtifacts.install": "provider_artifacts_install",
    "providerArtifacts.rollback": "provider_artifacts_rollback",
    "usage.aggregate": "usage_aggregate",
    "usage.export": "usage_export",
    "config.describe": "config_describe",
    "config.resolve": "config_resolve",
    "sessions.list": "sessions_list",
    "sessions.update": "sessions_update",
    "sessions.archive": "sessions_archive",
    "sessions.createAndSend": "sessions_create_and_send",
    "sessions.send": "sessions_send",
    "sessions.switchProfile": "sessions_switch_profile",
    "sendOutcome.query": "send_outcome_query",
    "queue.get": "queue_get",
    "queue.withdraw": "queue_withdraw",
    "runs.stop": "runs_stop",
    "approvals.decide": "approvals_decide",
    "history.snapshot": "history_snapshot",
}

#: The families whose support state depends on the execution port being
#: composed (the one rule the old `_capability` carried that still belongs to
#: the adapter; the Workspace blockers moved with the Workspace plugin).
_EXECUTION_GATE_FAMILY = frozenset({
    "sessions.list", "sessions.update", "sessions.archive",
    "sessions.createAndSend", "sessions.send", "sessions.switchProfile",
    "sendOutcome.query",
})


class WireService:
    """Dispatches wire/1 methods through the plugin host's method registry."""

    def __init__(
        self, *, server_id_provider: Callable[[], str], profiles, sessions,
        queue, approvals, harnesses, objects, execution, cursor_secret: bytes,
        method_registry=None,
        stream_routes=None,
        model_configs=None,
        token_required: bool = True,
        artifact_store=None,
        usage_aggregator=None,
        accounts=None,
        account_assets=None,
        subscription_files_for=None,
        asset_records=None,
        skill_assets=None,
        mcp_assets=None,
        plugin_assets=None,
        catalogs=None,
        hooks=None,
        hook_triggers=None,
        connectors=None,
        data_root=None,
        native_execution_provider=None,
    ) -> None:
        self._server_id_provider = server_id_provider
        self.native_execution_provider = native_execution_provider
        #: The managed ACP channel registry (seam doc `docs/acp-channel-minimal-seam.md`).
        #: Composed post-construction by whichever composition offers channels - the
        #: same precedent as `native_execution_provider` above; a Server without one
        #: answers the two `acp.channel.*` methods as typed unsupported, never 500.
        self.acp_channels = None
        self.artifact_store = artifact_store
        self.usage_aggregator = usage_aggregator
        #: Order 56's managed subscription accounts (records + assets). None
        #: when the composition has no secret store: the methods refuse typed.
        self.accounts = accounts
        self.account_assets = account_assets
        #: Order 58's asset catalogue and the two stores.
        self.asset_records = asset_records
        self.skill_assets = skill_assets
        self.mcp_assets = mcp_assets
        #: Order 59: the code-asset store (OpenCode-style plugin files).
        self.plugin_assets = plugin_assets
        #: Order 58 G7: directory-shaped source snapshots.
        self.catalogs = catalogs
        #: Order 59: the managed-hook ledger and its trigger facts.
        self.hooks = hooks
        self.hook_triggers = hook_triggers
        #: Order 62: the placement connectors (the WSL one answers a Git
        #: status through its own fixed command).
        self.connectors = connectors
        #: Order 63: the local home root, for the read-only memory face.
        self.data_root = data_root
        #: Order 56: harness -> its declared subscription login-state files,
        #: read from the deployment set the composition loaded.
        self.subscription_files_for = subscription_files_for or (lambda _harness: ())
        #: Workspace facts reach the remaining transitional domains only
        #: through a resolver the composition binds after activation; it reads
        #: the plugin host live, so unloading the Workspace plugin unbinds the
        #: port too. None resolver = the domain can never be present.
        self._workspace_resolver = None
        self._registry = method_registry
        #: The host's stream-route registry (ACP today): resolution of owned
        #: endpoints only — origin/bearer checks and close semantics stay in
        #: the host transport, which is where the wire reads it from.
        self.stream_routes = stream_routes
        self._adapter_owner = TRANSITIONAL_ADAPTER_ID
        # The host-owned discovery method; every other row arrives through a
        # plugin's registration (Workspace plugin, then the transitional
        # adapter — order preserved from the baseline dispatch table).
        from server_plugin_api import ServerMethodDescriptor

        self._registry.register(ServerMethodDescriptor(
            method_id="server.hello",
            required_params=frozenset({"clientVersions", "clientPresentationSupports"}),
            optional_params=frozenset(),
            handler=self.hello, owner=HOST_OWNER_ID,
        ))
        self.profiles = profiles
        self.sessions = sessions
        self.queue = queue
        self.approvals = approvals
        self.harnesses = harnesses
        self.objects = objects
        self.execution = execution
        self.model_configs = model_configs
        self.codec = CursorCodec(cursor_secret)
        self.token_required = token_required
    # -- the one dispatch table: registry views and lifecycle primitives ----

    @property
    def _handlers(self) -> dict[str, Callable[[Mapping[str, Any]], Any]]:
        """The registry's `{method_id: handler}` view, in registry order.

        Reading is the only thing this offers: the live table is the registry,
        and mutating it goes through `retire`/`replace_handler`/`amend_shape`
        (or a plugin's own unload), never by editing a copy.
        """
        return self._registry.handler_view()

    def retire(self, method_id: str) -> None:
        """Remove one of the adapter's own methods from the live table.

        This is the plugin-unload primitive applied to the transitional
        adapter; real plugins get the same effect through host unload.
        """
        self._registry.unregister(method_id, owner=self._adapter_owner)

    def replace_handler(self, method_id: str, handler: Callable) -> None:
        """Rebind one of the adapter's own methods on the live registry."""
        from server_plugin_api import ServerMethodDescriptor

        descriptor = self._registry.lookup(method_id)
        if descriptor is None or descriptor.owner != self._adapter_owner:
            raise WireError("INVALID_REQUEST", f"{method_id} is not an adapter method")
        self._registry.unregister(method_id, owner=self._adapter_owner)
        self._registry.register(ServerMethodDescriptor(
            method_id=method_id, required_params=descriptor.required_params,
            optional_params=descriptor.optional_params, handler=handler,
            owner=self._adapter_owner, availability=descriptor.availability,
        ))

    def amend_shape(self, method_id: str, *, required: "frozenset[str] | set[str]",
                    optional: "frozenset[str] | set[str]") -> None:
        """Re-declare one of the adapter's own param shapes on the registry."""
        from server_plugin_api import ServerMethodDescriptor

        descriptor = self._registry.lookup(method_id)
        if descriptor is None or descriptor.owner != self._adapter_owner:
            raise WireError("INVALID_REQUEST", f"{method_id} is not an adapter method")
        self._registry.unregister(method_id, owner=self._adapter_owner)
        self._registry.register(ServerMethodDescriptor(
            method_id=method_id, required_params=frozenset(required),
            optional_params=frozenset(optional), handler=descriptor.handler,
            owner=self._adapter_owner, availability=descriptor.availability,
        ))

    def bind_workspace_resolution(self, resolver: Callable[[], Any] | None) -> None:
        """Bind how workspace facts are resolved (a zero-arg callable reading
        the plugin host live, or None to declare the domain absent)."""
        self._workspace_resolver = resolver

    @property
    def workspaces(self):
        """The Workspace plugin's live resolution port, or None when absent."""
        if self._workspace_resolver is None:
            return None
        return self._workspace_resolver()

    def dispatch(self, method: str, params: Mapping[str, Any]) -> Any:
        descriptor = self._registry.lookup(method)
        if descriptor is None:
            raise WireError("INVALID_REQUEST", f"{method} is not a wire/1 method")
        missing = descriptor.required_params - set(params)
        extra = set(params) - descriptor.required_params - descriptor.optional_params
        if missing or extra:
            reason = "missing " + ", ".join(sorted(missing)) if missing else (
                "unexpected " + ", ".join(sorted(extra))
            )
            raise WireError("INVALID_REQUEST", f"params shape is invalid: {reason}")
        if "requestId" in params:
            _request_id(params["requestId"])
        try:
            return descriptor.handler(params)
        except WireError:
            # A typed refusal is the contract answering, not a crash: the wall
            # below must never re-project it onto `UNAVAILABLE`.
            raise
        except ServerError as exc:
            raise WireError.from_server_error(exc) from exc
        except Exception as exc:  # noqa: BLE001 - the wire contract, not the caller's convenience
            # The last wall of the error family (order 115): anything else that
            # escapes a handler still leaves this Server as a JSON-RPC error
            # object. The exception's *text* never goes out — it can name a host
            # path or a credential locator — only its type, as `internalCode`.
            raise WireError(
                "UNAVAILABLE", "this Server could not answer the request",
                {"internalCode": type(exc).__name__, "retryable": True},
            ) from exc

    # -- discovery ---------------------------------------------------------

    def hello(self, params: Mapping[str, Any]) -> dict[str, Any]:
        _require(params, "clientVersions", "clientPresentationSupports")
        versions = params["clientVersions"]
        presentations = params["clientPresentationSupports"]
        if (not isinstance(versions, list) or not versions
                or any(not isinstance(item, str) for item in versions)
                or not isinstance(presentations, list)
                or any(not isinstance(item, str) for item in presentations)):
            raise WireError("INVALID_REQUEST", "clientVersions must be a non-empty list")
        capabilities = []
        # The table is the plugin host's method registry: a method no plugin
        # registered does not exist here, and one that exists must never go
        # undeclared (a hand-maintained list had fallen 37 methods behind).
        # Iteration order is registration order — host, then each plugin in
        # activation order — so the list stays deterministic for a client that
        # caches it. `server.hello` declares itself - the discovery entry
        # point that said "I do not exist" would be the one lie here.
        for item in self._registry.descriptors():
            supported, reason = (
                item.availability() if item.availability is not None else (True, None))
            entry: dict[str, Any] = {"id": item.method_id, "supported": supported}
            if not supported:
                entry["reason"] = reason
            capabilities.append(entry)
        auth = {"required": True, "schemes": ["session_token"]} if self.token_required else {"required": False}
        harnesses = []
        # The family directory is a deployment fact - which harnesses this Server
        # can run - so it comes from the registry, never from the records: a
        # fresh deployment has no records, and deriving the list from them was
        # what left a client with nothing to choose. `registered()` is already
        # sorted by id, so this is the registry's own order rather than a second
        # sort that could later disagree with it. Only what a family *declares*
        # is published, and a declaration that is absent stays absent.
        for harness_id in self.harnesses.registered():
            descriptor = self.harnesses.get(harness_id)
            entry: dict[str, Any] = {"id": harness_id}
            if descriptor.credential_kind is not None:
                entry["credentialKind"] = descriptor.credential_kind
            if descriptor.model_control_id is not None:
                entry["modelControlId"] = descriptor.model_control_id
            harnesses.append(entry)
        result = {
            "serverId": self._server_id_provider(),
            "protocolVersion": WIRE_VERSION,
            "capabilities": capabilities,
            "auth": auth,
            "harnesses": harnesses,
        }
        if self.native_execution_provider is not None:
            native = self.native_execution_provider()
            if (not isinstance(native, Mapping) or native.get("mode") != "native"
                    or native.get("harness") not in self.harnesses.registered()
                    or not isinstance(native.get("profileId"), str) or not native["profileId"]):
                raise WireError("SERVER_NATIVE_IDENTITY_INVALID", "native execution identity is unavailable")
            result["nativeExecution"] = dict(native)
        return result

    def _capability(self, capability_id: str) -> tuple[bool, str | None]:
        """Support state for one id, read from its registered descriptor.

        So this answers two questions and no third: does the method exist (the
        registry, the only thing that can say no to a call), and does its
        availability predicate hold. Whether a call would then *succeed* is a
        third question these rules do not ask - a family with no blocker rule
        says `true` even when its call path is broken, which is why an
        unwritten rule is a gap to file, not something to guess here. An id
        that is not registered at all is an existence refusal at dispatch,
        never a support claim.
        """
        item = self._registry.lookup(capability_id)
        if item is None:
            return False, "UNKNOWN_METHOD"
        if item.availability is not None:
            return item.availability()
        return True, None

    # -- profiles ----------------------------------------------------------

    def profiles_list(self, params: Mapping[str, Any]) -> dict[str, Any]:
        include = params.get("includeArchived", False)
        if not isinstance(include, bool):
            raise WireError("INVALID_REQUEST", "includeArchived must be a boolean")
        items = []
        # One reader per call: `profiles.list` used to re-resolve the same provider
        # and the same model list for every row (order 147, `AUD-B-040`).
        read = _CallReader(self.objects)
        for row in self.profiles.records.list(include_archived=include):
            items.append(self._profile(row, read))
        return {"items": items, "nextCursor": None}

    def _profile(self, row: Mapping[str, Any], read: _CallReader | None = None) -> dict[str, Any]:
        item = profile_record(row)
        descriptor = (
            self.harnesses.get(row["harness_type"])
            if row["harness_type"] in self.harnesses else None
        )
        item["capabilities"] = {
            str(key): bool(value)
            for key, value in (descriptor.capability_claims if descriptor else {}).items()
            if isinstance(value, bool)
        }
        item["sendability"] = self._sendability(row, item, read)
        return item

    # -- sendability (order 117, QA-009) -----------------------------------

    def _profile_bindings(self, row: Mapping[str, Any],
                          read: _CallReader | None = None,
                          ) -> tuple[list[dict[str, Any]], bool]:
        """Re-walk the model resolution a turn would do, and say what it would hit.

        `freeze_execution_configuration` (`model_configs/service.py:134-180`) is
        the code that decides whether a Profile can actually run: it reads the
        model control out of the Profile's configuration object, resolves the
        provider record, then the model, then the credential. A client could only
        learn the outcome by sending a message, so this walks the same chain and
        reports the first thing it would trip on — the *rules* are copied here,
        not imported, because `model_configs/**` is the runtime line's surface
        (charter §3); `test_a_blocker_the_freeze_path_would_hit_is_named` is what
        keeps the two from drifting.
        """
        empty: tuple[list[dict[str, Any]], bool] = ([], False)
        read = read or _CallReader(self.objects)
        descriptor = (
            self.harnesses.get(row["harness_type"])
            if row["harness_type"] in self.harnesses else None
        )
        if descriptor is None:
            # An unregistered harness is a different visible fact (capabilities);
            # nothing here can say whether a model would resolve.
            return [], True
        control_id = getattr(descriptor, "model_control_id", None)
        if control_id is None:
            return empty  # this harness takes no provider/model reference at all
        if self.model_configs is None:
            return [], True
        digest = row.get("config_object_digest")
        if not digest:
            return [{
                "providerModelId": None, "modelId": None,
                "state": "blocked", "reason": "PROFILE_CONFIGURATION_INVALID",
                "detail": f"control {control_id} selects no Provider/Model configuration",
            }], False
        try:
            document = read.parsed(digest)
        except Exception:  # noqa: BLE001 - unreadable configuration is unknown, not fine
            return [], True
        reference = (document.get("configuration") or {}).get(control_id)
        if (not isinstance(reference, Mapping) or not isinstance(reference.get("providerId"), str)
                or not isinstance(reference.get("modelId"), str) or not reference["modelId"]):
            return [{
                "providerModelId": None, "modelId": None,
                "state": "blocked", "reason": "PROFILE_CONFIGURATION_INVALID",
                "detail": f"control {control_id} must select a Provider/Model configuration",
            }], False
        binding: dict[str, Any] = {
            "providerModelId": reference["providerId"], "modelId": reference["modelId"],
            "controlId": control_id, "state": "ready", "reason": None, "detail": None,
        }
        try:
            provider = read.record(
                binding["providerModelId"],
                lambda: self.model_configs.records.get(binding["providerModelId"]),
            )
        except ServerError as error:
            binding["state"] = "blocked"
            binding["reason"] = ("PROVIDER_MODEL_NOT_FOUND" if error.code == "PROVIDER_MODEL_NOT_FOUND"
                                 else "PROFILE_CONFIGURATION_INVALID")
            binding["detail"] = str(error.message)[:200]
            return [binding], False
        except Exception:  # noqa: BLE001
            return [], True
        if provider["archived_at"] is not None or provider["harness_type"] != row["harness_type"]:
            binding["state"] = "blocked"
            binding["reason"] = "PROVIDER_MODEL_UNUSABLE"
            binding["detail"] = ("archived" if provider["archived_at"] is not None
                                 else "the provider record belongs to a different harness")
            return [binding], False
        try:
            models = read.index(provider["models_object_digest"],
                                section="models", field="modelId")
        except Exception:  # noqa: BLE001
            return [binding], True
        model = models.get(binding["modelId"])
        if model is None:
            binding["state"] = "blocked"
            binding["reason"] = "PROVIDER_MODEL_REFERENCE_MISSING"
            binding["detail"] = "the referenced model is not on that provider record"
            return [binding], False
        if model.get("availability") == "unavailable":
            binding["state"] = "blocked"
            binding["reason"] = "MODEL_UNAVAILABLE"
            binding["detail"] = str(model.get("unavailableReason") or "")[:200]
            return [binding], False
        credential_id = provider.get("credential_id")
        binding["credentialId"] = credential_id
        kind = getattr(descriptor, "credential_kind", None)
        if kind is not None and credential_id is not None:
            # The same kind-scoped lookup the freeze path performs: a credential
            # that exists but is not of the kind this harness takes is just as
            # unsendable as one that is absent, and `exists()` alone would call
            # it ready. `test_a_binding..._is_the_wrong_kind...` holds that open.
            try:
                record = self.model_configs.credentials.get(credential_id, kind=kind)
            except ServerError as error:
                binding["state"] = "blocked"
                binding["reason"] = error.code
                binding["detail"] = (
                    f"this host has no credential {credential_id} of kind {kind}")[:200]
                return [binding], False
            except Exception:  # noqa: BLE001
                return [binding], True
            # Order 152 (`R-0080`, ACC-R5-4): the identity resolving is not the same
            # fact as this host being able to *open* its secret. A Windows DPAPI
            # locator cannot be read on Linux, yet the row exists and the kind
            # matches, so the chain above still said `ready` and the user only found
            # out by getting `EXECUTION_FAILED` after typing. Ask the store, and
            # never let an unresolvable credential read as sendable.
            store = getattr(self.model_configs, "secret_store", None)
            if store is not None:
                locator = record.get("secret_locator") if isinstance(record, Mapping) else None
                if not locator:
                    # No address to try: the resolvability query cannot be formed,
                    # which is `unknown`, never `ready`.
                    binding["state"] = "unknown"
                    binding["reason"] = "CREDENTIAL_RESOLVABILITY_UNKNOWN"
                    binding["detail"] = (
                        f"credential {credential_id} carries no locator to resolve "
                        f"on this host")[:200]
                    return [binding], False
                try:
                    store.read(locator)  # discard: the value must never leave this probe
                except Exception:  # noqa: BLE001 - cannot open it here is a real blocker
                    binding["state"] = "blocked"
                    binding["reason"] = "CREDENTIAL_NOT_RESOLVABLE"
                    binding["detail"] = (
                        f"credential {credential_id} is registered but its secret is "
                        f"not readable on this host (e.g. a locator from another OS)")[:200]
                    return [binding], False
        return [binding], False

    def _sendability(self, row: Mapping[str, Any], projected: Mapping[str, Any],
                     read: _CallReader | None = None) -> dict[str, Any]:
        """Can this Profile take a message here, answered **before** one is sent.

        QA-009's complaint is that both blockers existed only as a failure after
        the user had typed: 409 `PROFILE_RECOVERY_REQUIRED` at accept, and a
        credential that was never provisioned on this host arriving as
        `EXECUTION_FAILED` inside the turn. The accept-time behaviour is
        unchanged — this only says it out loud earlier — and every fact that
        could not be read is reported as `unknown`, never as "sendable".
        """
        checks: list[dict[str, Any]] = []
        recovery = projected.get("recoveryPending")
        if recovery is True:
            checks.append({
                "key": "recovery", "state": "blocked",
                "reason": "PROFILE_RECOVERY_REQUIRED",
                "message": "this Profile is waiting on a recovery the Server has not completed",
                # No wire method clears this state today: saying so is the honest
                # part of "what can the user do" (the clearing face is a product
                # decision in the approval queue, not something to invent here).
                "actions": [],
            })
        elif recovery is False:
            checks.append({"key": "recovery", "state": "ready", "reason": None,
                           "message": None, "actions": []})
        else:
            checks.append({"key": "recovery", "state": "unknown",
                           "reason": "RECOVERY_STATE_UNREADABLE",
                           "message": "this Server could not read the recovery state",
                           "actions": []})
        bindings, unreadable = self._profile_bindings(row, read)
        for binding in bindings:
            checks.append({
                "key": "model:" + (binding.get("providerModelId")
                                   or binding.get("controlId") or "unset"),
                "state": binding["state"],
                "reason": binding.get("reason"),
                "message": binding.get("detail"),
                "actions": _BINDING_ACTIONS.get(binding.get("reason") or "", []),
                "credentialId": binding.get("credentialId"),
            })
        if unreadable:
            checks.append({"key": "model", "state": "unknown", "reason": "CONFIGURATION_UNREADABLE",
                           "message": "this Server could not read the Profile's configuration",
                           "actions": []})
        for state in ("blocked", "unknown"):
            hit = next((item for item in checks if item["state"] == state), None)
            if hit is not None:
                return {
                    "state": state,
                    "reason": hit["reason"],
                    "message": hit["message"],
                    "actions": sorted({action for item in checks for action in item["actions"]}),
                    "checks": checks,
                }
        return {"state": "ready", "reason": None, "message": None, "actions": [], "checks": checks}

    # -- managed hooks (Order 59) ------------------------------------------

    def _require_hooks(self):
        if self.hooks is None or self.hook_triggers is None:
            raise WireError("UNAVAILABLE", "the hook ledger is not composed")
        return self.hooks, self.hook_triggers

    def _require_workspace_resolution(self):
        """The Workspace plugin's provided port, or a typed refusal.

        The remaining session/ACP/attachment paths read workspace facts only
        through the port the Workspace plugin provides; when that plugin is
        not composed, the honest answer is a typed refusal, never an
        AttributeError collapsing into a 500.
        """
        if self.workspaces is None:
            raise WireError("UNAVAILABLE", "workspace resolution is not composed")
        return self.workspaces

    def hooks_list(self, params: Mapping[str, Any]) -> dict[str, Any]:
        _require(params, "requestId")
        hooks, _triggers = self._require_hooks()
        family = params.get("family")
        if family is not None:
            family = _bounded(family, "family", 64)
        return {"hooks": [hook_view(row) for row in hooks.list(family=family)]}

    def hooks_create(self, params: Mapping[str, Any]) -> dict[str, Any]:
        hooks, _triggers = self._require_hooks()
        model = params["model"]
        if not isinstance(model, Mapping):
            raise WireError("INVALID_REQUEST", "model must be an object")
        try:
            _kind, created = hooks.create(
                key=_request_id(params["requestId"]),
                request_digest=digest({
                    "family": params["family"], "name": params["name"], "model": model}),
                family=_bounded(params["family"], "family", 64),
                name=_bounded(params["name"], "name", 128),
                model=model,
                source=params.get("source"),
            )
        except ServerError as exc:
            raise WireError.from_server_error(exc) from exc
        return {"hook": hook_view(hooks.get(created["hook_id"]))}

    def hooks_update(self, params: Mapping[str, Any]) -> dict[str, Any]:
        hooks, _triggers = self._require_hooks()
        model = params["model"]
        if not isinstance(model, Mapping):
            raise WireError("INVALID_REQUEST", "model must be an object")
        try:
            updated = hooks.update(
                hook_id=_bounded(params["hookId"], "hookId"), model=model)
        except ServerError as exc:
            raise WireError.from_server_error(exc) from exc
        return {"hook": hook_view(hooks.get(updated["hook_id"]))}

    def hooks_set_enabled(self, params: Mapping[str, Any]) -> dict[str, Any]:
        hooks, _triggers = self._require_hooks()
        enabled = params["enabled"]
        if not isinstance(enabled, bool):
            raise WireError("INVALID_REQUEST", "enabled must be a boolean")
        try:
            updated = hooks.set_enabled(
                hook_id=_bounded(params["hookId"], "hookId"), enabled=enabled)
        except ServerError as exc:
            raise WireError.from_server_error(exc) from exc
        return {"hook": hook_view(hooks.get(updated["hook_id"]))}

    def hooks_delete(self, params: Mapping[str, Any]) -> dict[str, Any]:
        hooks, _triggers = self._require_hooks()
        try:
            removed_triggers = hooks.delete(hook_id=_bounded(params["hookId"], "hookId"))
        except ServerError as exc:
            raise WireError.from_server_error(exc) from exc
        return {"deleted": True, "triggersRemoved": removed_triggers}

    def hooks_triggers(self, params: Mapping[str, Any]) -> dict[str, Any]:
        _require(params, "requestId")
        _hooks, triggers = self._require_hooks()
        hook_id = params.get("hookId")
        if hook_id is not None:
            hook_id = _bounded(hook_id, "hookId")
        limit = params.get("limit", 100)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise WireError("INVALID_REQUEST", "limit must be 1..500")
        return {"triggers": [trigger_view(row) for row in triggers.list(
            hook_id=hook_id, limit=limit)]}

    # -- managed assets (Order 58) -----------------------------------------

    def _require_catalogs(self):
        if self.catalogs is None:
            raise WireError("UNAVAILABLE", "no catalogue store is composed")
        return self.catalogs

    def assets_sync_catalog(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Snapshot one directory-shaped source (list now, install later)."""
        from pathlib import Path as _Path

        catalogs = self._require_catalogs()
        try:
            snapshot = catalogs.sync(
                source_id=_slug(params["sourceId"], "sourceId"),
                source_path=_Path(_bounded(params["sourcePath"], "sourcePath", 4096)),
            )
        except Exception as refusal:  # noqa: BLE001 - typed by the store
            raise _asset_refusal(refusal) from refusal
        return {"catalog": self._catalog_view(snapshot)}

    def assets_catalog(self, params: Mapping[str, Any]) -> dict[str, Any]:
        catalogs = self._require_catalogs()
        snapshot = catalogs.snapshot(_slug(params["sourceId"], "sourceId"))
        if snapshot is None:
            raise WireError("NOT_FOUND", "that source has no snapshot yet")
        return {"catalog": self._catalog_view(snapshot)}

    def _catalog_view(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        records, _skills, _mcp = self._require_assets()
        installed = {
            f"{row['kind']}:{row['name']}": row["digest"] for row in records.list()
        }
        return {
            "sourcePath": snapshot["source_path"],
            "digest": snapshot["digest"],
            "entries": self._require_catalogs().annotate(snapshot, installed=installed),
        }

    def assets_install_from_catalog(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Install one catalogue entry (a user action), provenance pinned."""
        catalogs = self._require_catalogs()
        records, skills, mcp = self._require_assets()
        source_id = _slug(params["sourceId"], "sourceId")
        snapshot = catalogs.snapshot(source_id)
        if snapshot is None:
            raise WireError("NOT_FOUND", "that source has no snapshot yet")
        try:
            installed = catalogs.install_entry(
                snapshot=snapshot,
                entry_name=_slug(params["entryName"], "entryName"),
                revision=_positive(params["revision"], "revision"),
                records=records, skills=skills, mcp=mcp,
            )
        except Exception as refusal:  # noqa: BLE001 - typed by the store
            raise _asset_refusal(refusal) from refusal
        return {"installed": installed}

    def assets_probe(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """One bounded stdio handshake probe; no config write, no model call."""
        from ordessa_server.assets.mcp import McpAssetError, canonical_definition
        from ordessa_server.assets.mcp_probe import McpProbeError, probe_stdio

        try:
            canonical = canonical_definition(params["definition"])
        except McpAssetError as refusal:
            raise WireError("INVALID_REQUEST", f"{refusal.code}: {refusal.message}")
        transport = canonical["transport"]
        if "stdio" not in transport:
            raise WireError("INVALID_REQUEST", "only stdio servers can be probed yet")
        body = transport["stdio"]
        try:
            facts = probe_stdio(body["command"], args=body["args"])
        except McpProbeError as refusal:
            raise WireError("UNAVAILABLE", f"{refusal.code}: {refusal.message}")
        return {"probe": facts}

    def _require_assets(self):
        if self.asset_records is None or self.skill_assets is None or self.mcp_assets is None:
            raise WireError("UNAVAILABLE", "the asset stores are not composed")
        return self.asset_records, self.skill_assets, self.mcp_assets

    def assets_list(self, params: Mapping[str, Any]) -> dict[str, Any]:
        del params
        records, _skills, _mcp = self._require_assets()
        return {"assets": [asset_view(row) for row in records.list()]}

    def assets_publish_skill(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Install one skill directory (a host path) as a revision."""
        from pathlib import Path as _Path

        records, skills, _mcp = self._require_assets()
        asset_id = _slug(params["assetId"], "assetId")
        revision = _positive(params["revision"], "revision")
        source = _Path(_bounded(params["sourcePath"], "sourcePath", 4096))
        try:
            facts = skills.install(source, asset_id=asset_id, revision=revision)
        except Exception as refusal:  # noqa: BLE001 - typed by the store
            raise _asset_refusal(refusal) from refusal
        published = records.publish(
            key=_request_id(params["requestId"]),
            request_digest=digest({"assetId": asset_id, "revision": revision,
                                   "sourcePath": params["sourcePath"]}),
            kind="skill", name=facts["name"], revision=revision,
            digest=facts["tree_digest"], description=facts["description"],
            source=f"local:{source.name}", asset_id=asset_id,
        )[1]
        return {"asset": asset_view({**published, "id": published["asset_id"],
                                     "latest_revision": published["latest_revision"]})}

    def assets_publish_mcp(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Store one standard MCP server definition as a revision."""
        from ordessa_server.assets.mcp import definition_digest

        records, _skills, mcp = self._require_assets()
        asset_id = _slug(params["assetId"], "assetId")
        revision = _positive(params["revision"], "revision")
        definition = params["definition"]
        try:
            canonical = mcp.install(definition, asset_id=asset_id, revision=revision)
        except Exception as refusal:  # noqa: BLE001 - typed by the store
            raise _asset_refusal(refusal) from refusal
        published = records.publish(
            key=_request_id(params["requestId"]),
            request_digest=digest({"assetId": asset_id, "revision": revision,
                                   "definition": definition}),
            kind="mcp", name=canonical["name"], revision=revision,
            digest=definition_digest(mcp.read(asset_id=asset_id, revision=revision)),
            asset_id=asset_id,
        )[1]
        return {"asset": asset_view({**published, "id": published["asset_id"],
                                     "latest_revision": published["latest_revision"]})}

    def assets_publish_plugin(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Store one code asset (a plugin file) with its digest and preview.

        No form ever assembles this code: the user supplies the file, the
        store keeps it verbatim, and the response carries a bounded preview so
        the UI can show what was stored without reading it back from disk.
        """
        from pathlib import Path as _Path

        if self.plugin_assets is None:
            raise WireError("UNAVAILABLE", "no plugin asset store is composed")
        records, _skills, _mcp = self._require_assets()
        asset_id = _slug(params["assetId"], "assetId")
        revision = _positive(params["revision"], "revision")
        source = _Path(_bounded(params["sourcePath"], "sourcePath", 4096))
        try:
            facts = self.plugin_assets.install(
                source, asset_id=asset_id, revision=revision)
        except Exception as refusal:  # noqa: BLE001 - typed by the store
            raise _asset_refusal(refusal) from refusal
        published = records.publish(
            key=_request_id(params["requestId"]),
            request_digest=digest({"assetId": asset_id, "revision": revision,
                                   "sourcePath": params["sourcePath"]}),
            kind="plugin", name=asset_id, revision=revision, digest=facts["digest"],
            source=f"local:{source.name}", asset_id=asset_id,
        )[1]
        return {"asset": asset_view({**published, "id": published["asset_id"],
                                     "latest_revision": published["latest_revision"]}),
                "preview": facts["preview"]}

    def assets_bind(self, params: Mapping[str, Any]) -> dict[str, Any]:
        records, _skills, _mcp = self._require_assets()
        revision = params.get("revision")
        if revision is not None:
            revision = _positive(revision, "revision")
        enabled = params.get("enabled", True)
        if not isinstance(enabled, bool):
            raise WireError("INVALID_REQUEST", "enabled must be a boolean")
        binding = records.bind(
            profile_id=_bounded(params["profileId"], "profileId"),
            asset_id=_slug(params["assetId"], "assetId"),
            revision=revision, enabled=enabled,
        )
        return {"binding": binding}

    def assets_unbind(self, params: Mapping[str, Any]) -> dict[str, Any]:
        records, _skills, _mcp = self._require_assets()
        records.unbind(
            profile_id=_bounded(params["profileId"], "profileId"),
            asset_id=_slug(params["assetId"], "assetId"),
        )
        return {"unbound": True}

    def assets_bindings(self, params: Mapping[str, Any]) -> dict[str, Any]:
        records, _skills, _mcp = self._require_assets()
        return {"bindings": records.bindings(
            _bounded(params["profileId"], "profileId"))}

    # -- managed subscription accounts (Order 56) --------------------------

    def _require_accounts(self):
        if self.accounts is None or self.account_assets is None:
            raise WireError(
                "UNAVAILABLE",
                "managed subscription accounts need a platform secret store",
            )
        return self.accounts, self.account_assets

    def accounts_list(self, params: Mapping[str, Any]) -> dict[str, Any]:
        del params
        accounts, _assets = self._require_accounts()
        return {"accounts": [account_view(row) for row in accounts.list()]}

    def accounts_create(self, params: Mapping[str, Any]) -> dict[str, Any]:
        accounts, _assets = self._require_accounts()
        _kind, created = accounts.create(
            key=_request_id(params["requestId"]),
            request_digest=digest({
                "harness": params["harness"],
                "accountIdentifier": params["accountIdentifier"],
            }),
            harness_type=_bounded(params["harness"], "harness", 64),
            account_identifier=_bounded(params["accountIdentifier"], "accountIdentifier", 128),
        )
        # The record layer speaks snake_case rows; the wire view is the one
        # projection, so replay and fresh creation answer identically.
        return {"account": account_view(accounts.get(created["account_id"]))}

    def accounts_bind(self, params: Mapping[str, Any]) -> dict[str, Any]:
        accounts, _assets = self._require_accounts()
        account_id = params["accountId"]
        if account_id is not None:
            account_id = _bounded(account_id, "accountId")
            accounts.get(account_id)  # 404 before the profile write
        try:
            _status, body = self.profiles.records.bind_account(
                profile_id=_bounded(params["profileId"], "profileId"),
                account_id=account_id,
                expected_version=_version(params["expectedVersion"]),
                key=_request_id(params["requestId"]),
                request_digest=digest({
                    "profileId": params["profileId"], "accountId": account_id,
                }),
            )
            row = body["profile"]
        except ServerError as exc:
            raise self._profile_error(exc) from exc
        return {"profile": self._profile(row)}

    def accounts_import_asset(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Import one login-state file as the account's asset.

        The path is a host path the operator (or the Desktop) names, and the
        same rules as the credential import apply: a real regular file, no
        links, bounded; the bytes go straight into the platform secret store
        and only the reference comes back.
        """
        from pathlib import Path as _Path

        accounts, assets = self._require_accounts()
        account_id = _bounded(params["accountId"], "accountId")
        account = accounts.get(account_id)
        source = _Path(_bounded(params["sourcePath"], "sourcePath", 4096))
        if source.is_symlink() or not source.is_file():
            raise WireError("INVALID_REQUEST", "sourcePath must be a regular file")
        size = source.stat().st_size
        if size <= 0 or size > 256 * 1024:
            raise WireError("INVALID_REQUEST", "the login-state file is empty or oversized")
        harness = str(account["harness_type"])
        declared = self._subscription_files_for(harness)
        if not declared:
            raise WireError(
                "INVALID_REQUEST",
                f"the {harness!r} family declares no subscription login-state files",
            )
        # The import names one file; it is the only one that can be declared
        # here, so a mismatch is a refusal rather than a partial asset.
        name = declared[0] if len(declared) == 1 else None
        if name is None:
            raise WireError(
                "INVALID_REQUEST",
                "importing one file into a multi-file login state is not supported",
            )
        payload = source.read_bytes()
        # Order 129 (`AUD-B-012`): the locked contract requires `requestId`, and the
        # two sibling methods (`accounts.create`, `accounts.bind`) run theirs through
        # the idempotency layer. This handler never read the key, so a retry of one
        # import executed a second time instead of replaying - and a second execution
        # mints a second locator, because `write_asset` names a fresh one per call.
        key = _request_id(params["requestId"])
        request_digest = digest({
            "accountId": account_id, "sourcePath": str(source), "size": size,
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
        scope = "accounts.importAsset"
        # Not a fresh `IdempotentRecords`: this is the instance `accounts.create`
        # already uses, so the family really does share one path and one table.
        idempotency = accounts.idempotency
        prior = idempotency.get(scope, key, request_digest)
        if prior is not None:
            # The receipt is the answer, so a replay is byte-identical to the
            # first response rather than a second observation of the record.
            return prior[1]
        locator, digest_value = assets.write_asset(
            account_id=account_id, files={name: payload}, kind="subscription",
        )
        accounts.record_asset(
            account_id, locator=locator, digest=digest_value,
            state=str(account["state"]),
        )
        body = {"account": account_view(accounts.get(account_id))}
        # `save` re-checks inside its own transaction and returns the winner's
        # receipt, so two racing first attempts cannot both claim the key. The
        # window that remains is the side effect between the check here and the
        # insert there: closing it needs the asset write inside the same
        # transaction, which lives in `assets/**` and not in this order's surface.
        idempotency.save(scope, key, request_digest, 200, body)
        return body

    def _subscription_files_for(self, harness: str) -> tuple[str, ...]:
        """The family's declared subscription files, from the deployment."""
        return tuple(self.subscription_files_for(harness) or ())

    def profiles_create(self, params: Mapping[str, Any]) -> dict[str, Any]:
        # `credentialId` is optional and nullable: a Harness whose credential
        # cannot ride a model control (Hermes declares none) needs the role
        # itself to carry one, and a role without one stays expressible.
        credential_id = params.get("credentialId")
        if credential_id is not None:
            credential_id = _bounded(credential_id, "credentialId")
        row = self.profiles.create_wire(
            _request_id(params["requestId"]),
            display_name=_bounded(params["displayName"], "displayName", 128),
            harness=_bounded(params["harness"], "harness", 64),
            credential_id=credential_id,
        )
        return {"profile": self._profile(row)}

    def profiles_subagent_grants(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Who this Profile may call, and who may call it (order 65 A).

        The list is the authorization partition's data: the UI shows exactly
        the granted edges and nothing else.
        """
        profile_id = _bounded(params["profileId"], "profileId")
        self.profiles.records.get(profile_id)
        grants = [
            {"childProfileId": row["child_profile_id"]}
            for row in self.profiles.records.subagent_grants(parent_id=profile_id)
        ]
        with self.profiles.records.database.read() as conn:
            callers = [
                {"parentProfileId": row["parent_profile_id"]}
                for row in conn.execute(
                    "SELECT parent_profile_id FROM server_subagent_grants "
                    "WHERE child_profile_id=? ORDER BY parent_profile_id", (profile_id,),
                ).fetchall()
            ]
        return {"subagentGrants": grants, "callableBy": callers}

    def profiles_grant_subagent(self, params: Mapping[str, Any]) -> dict[str, Any]:
        try:
            grant = self.profiles.records.grant_subagent(
                parent_id=_bounded(params["profileId"], "profileId"),
                child_id=_bounded(params["childProfileId"], "childProfileId"),
            )
        except ServerError as exc:
            raise self._profile_error(exc) from exc
        return {"grant": grant}

    def profiles_revoke_subagent(self, params: Mapping[str, Any]) -> dict[str, Any]:
        try:
            self.profiles.records.revoke_subagent(
                parent_id=_bounded(params["profileId"], "profileId"),
                child_id=_bounded(params["childProfileId"], "childProfileId"),
            )
        except ServerError as exc:
            raise self._profile_error(exc) from exc
        return {"revoked": True}

    def profiles_memory(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Read the Profile's declared memory files (order 63).

        The home is resolved the same way a turn resolves it (name + identity
        + the registry's native home); a family that declares no memory paths
        answers `available: false` so the UI hides the partition. Only the
        local placement can be read here; a remote home answers the typed
        unavailable reason instead of pretending.
        """
        from pathlib import Path as _Path

        from ordessa_server.bootstrap.runtime import (
            _profile_home_locator, _registry_native_homes, _registry_profile_spec,
        )
        from ordessa_server.profiles.memory import memory_paths_for, read_memory

        _require(params, "requestId", "profileId")
        profile = self.profiles.records.get(_bounded(params["profileId"], "profileId"))
        harness = str(profile["harness_type"])
        spec = _registry_profile_spec(harness)
        declared = memory_paths_for(spec)
        if not declared:
            return {"memory": {"available": False, "reason": None, "files": [],
                               "note": "this family declares no memory paths"}}
        native_home = _registry_native_homes().get(harness)
        if not native_home:
            return {"memory": {"available": False, "reason": "MEMORY_HOME_MISSING",
                               "files": []}}
        locator = profile.get("home_locator") or _profile_home_locator(
            profile.get("name") or harness, native_home,
            profile_id=profile.get("id"))
        if self.data_root is None:
            return {"memory": {"available": False, "reason": "MEMORY_UNAVAILABLE",
                               "files": []}}
        # The declared paths are guest-home-relative, which is exactly the
        # role-relative mapping every other home face uses.
        role_segment = locator.split("/", 1)[0]
        home = _Path(self.data_root) / "profiles" / role_segment
        if not home.is_dir():
            return {"memory": {"available": False, "reason": "MEMORY_HOME_MISSING",
                               "files": []}}
        return {"memory": read_memory(home, declared=declared)}

    def profiles_set_permissions(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Write the profile's permission posture (order 60 A/G2).

        The rules are validated by the record layer before storage, so an
        illegal key or action answers with its own code and nothing is saved.
        """
        rules = params["rules"]
        if not isinstance(rules, list):
            raise WireError("INVALID_REQUEST", "rules must be a list")
        try:
            updated = self.profiles.records.set_permissions(
                profile_id=_bounded(params["profileId"], "profileId"),
                preset=_bounded(params["preset"], "preset", 32),
                rules=rules,
                expected_version=_version(params["expectedVersion"]),
                key=_request_id(params["requestId"]),
                request_digest=digest({
                    "profileId": params["profileId"], "preset": params["preset"],
                    "rules": rules,
                }),
            )
        except ServerError as exc:
            raise self._profile_error(exc) from exc
        return {"profile": self._profile(updated[1]["profile"])}

    def executions_list(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """The in-flight executions of ours, straight from the ledger.

        Read-only: no cancellation surface, no machine-level process view, and
        a bounded row count (over the bound is a typed refusal, never a
        silently shorter list).
        """
        from ordessa_server.execution.inventory import (
            MAX_EXECUTIONS, InventoryError, list_executions,
        )

        _require(params, "requestId")
        limit = params.get("limit", MAX_EXECUTIONS)
        try:
            rows = list_executions(
                self.sessions.records.database, execution_port=self.execution,
                limit=limit)
        except InventoryError as refusal:
            raise WireError("INVALID_REQUEST", f"{refusal.code}: {refusal.message}") from refusal
        return {"executions": rows}

    def executions_get(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """One execution's run record, read as a run ended or is in flight.

        `channel_run_view` is the single adaptation point where the ledger's
        real terminal facts become the channel-run vocabulary; nothing else
        in this Server translates them, and a run that has not ended is
        reported as exactly that.
        """
        from ordessa_server.acp_channel import channel_run_view

        _require(params, "requestId", "executionId")
        row = self.sessions.records.get_turn_context(
            _bounded(params["executionId"], "executionId"))
        return channel_run_view(row)

    def acp_channel_open(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Establish or re-acquire the managed bidirectional ACP channel.

        Every refusal happens before any launch: this Server's native
        identity, the Project record, and the authoritative working dir are
        all checked first, so a rejected request starts no process and writes
        no run. A pair that already holds a live channel returns that same
        connection - the binding never moves underneath a client.
        """
        _require(params, "harnessId", "projectId")
        if self.acp_channels is None:
            raise WireError("CAPABILITY_UNSUPPORTED", "this Server composes no managed ACP channel")
        harness_id = _bounded(params["harnessId"], "harnessId", 64)
        identity = self.native_execution_provider() if self.native_execution_provider else None
        if (not isinstance(identity, Mapping) or identity.get("mode") != "native"
                or identity.get("harness") != harness_id or not identity.get("profileId")):
            raise WireError(
                "CAPABILITY_UNSUPPORTED",
                f"{harness_id} is not the native Harness this Server answers channels for",
            )
        workspace_id = _bounded(params["projectId"], "projectId")
        workspaces = self._require_workspace_resolution()
        row = workspaces.records.get(workspace_id)
        if str(row.get("env_kind") or "") != "local":
            raise WireError("CAPABILITY_UNSUPPORTED", "managed channels are placed on local projects only")
        selected = str(row.get("normalized_path") or "")
        if not selected:
            raise WireError("INVALID_REQUEST", "the project record carries no authoritative path")
        normalized = self._require_workspace_resolution().local.validate(selected)
        if normalized != selected:
            raise ServerError("NATIVE_PROJECT_CHANGED", "selected project changed", status=409)
        return self.acp_channels.acquire(
            harness_id=harness_id, workspace_id=workspace_id,
            profile_id=str(identity["profileId"]), cwd=selected,
        )

    def acp_channel_release(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Release one channel by ownership: its transport stops, its run
        record ends saying `released`, and no in-flight request is answered
        on anyone's behalf. Only the live holder of the id is touched."""
        _require(params, "connectionId")
        if self.acp_channels is None:
            raise WireError("CAPABILITY_UNSUPPORTED", "this Server composes no managed ACP channel")
        result = self.acp_channels.release(_bounded(params["connectionId"], "connectionId"))
        if result is None:
            raise WireError("NOT_FOUND", "no live managed channel carries that connectionId")
        return result

    def profiles_clone(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Clone one Profile into a new one, with the migration report.

        The report is the product surface: what traveled, what did not, and
        why. Session material never appears as migrated (order 60 D).
        """
        from ordessa_server.profiles.clone import plan_migration

        source_id = _bounded(params["profileId"], "profileId")
        name = _bounded(params["displayName"], "displayName", 128)
        records = self.profiles.records
        source = records.get(source_id)
        harness = params.get("harness") or source["harness_type"]
        if not isinstance(harness, str):
            raise WireError("INVALID_REQUEST", "harness must be a string")
        harness = _bounded(harness, "harness", 64)
        from ordessa_server.bootstrap.runtime import _registry_profile_spec

        profile_spec = _registry_profile_spec(harness)
        if profile_spec is None:
            raise WireError("INVALID_REQUEST", f"the {harness!r} family is not registered")
        bindings = self._asset_bindings_for(source_id)
        hooks = self.hooks.list() if self.hooks is not None else []
        try:
            report = plan_migration(
                source=source, target_harness=harness, asset_bindings=bindings,
                hooks=hooks, registry_profile=profile_spec,
            )
            clone = records.clone_from(
                source_id=source_id, name=name, harness_type=harness, report=report)
        except ServerError as exc:
            raise self._profile_error(exc) from exc
        # The plan's migrated asset entries are exactly what gets rebound: the
        # report and the rows cannot disagree because one is derived from the
        # other.
        rebound: list[str] = []
        if self.asset_records is not None:
            migrated = [entry["item"] for entry in report["items"]
                        if entry["migrated"] and ":" in entry["item"]]
            rebound = self.asset_records.copy_bindings(
                source_profile_id=source_id, target_profile_id=clone["id"],
                items=migrated)
        report["reboundAssets"] = rebound
        return {"profile": self._profile(clone), "migration": report}

    def _asset_bindings_for(self, profile_id: str) -> list[dict[str, Any]]:
        """The (kind, name, revision) triples a clone's plan needs."""
        if self.asset_records is None:
            return []
        with self.asset_records.database.read() as conn:
            return [
                {"kind": row["kind"], "name": row["name"], "revision": int(row["revision"])}
                for row in conn.execute(
                    "SELECT a.kind,a.name,b.revision FROM server_profile_assets b "
                    "JOIN server_assets a ON a.id=b.asset_id WHERE b.profile_id=?",
                    (profile_id,),
                ).fetchall()
            ]

    def profiles_update(self, params: Mapping[str, Any]) -> dict[str, Any]:
        try:
            row = self.profiles.update_display_name(
                _request_id(params["requestId"]),
                profile_id=_bounded(params["profileId"], "profileId"),
                expected_version=_version(params["expectedVersion"]),
                display_name=_bounded(params["displayName"], "displayName", 128),
            )
        except ServerError as exc:
            raise self._profile_error(exc) from exc
        return {"profile": self._profile(row)}

    def profiles_update_config(self, params: Mapping[str, Any]) -> dict[str, Any]:
        values = _assignments(params.get("values"), "values")
        try:
            row = self.profiles.update_configuration(
                _request_id(params["requestId"]),
                profile_id=_bounded(params["profileId"], "profileId"),
                expected_version=_version(params["expectedVersion"]), values=values,
            )
        except ServerError as exc:
            raise self._profile_error(exc) from exc
        return {
            "profile": self._profile(row), "configVersion": int(row["config_revision"]),
            "effectiveFor": "next_send",
        }

    def profiles_archive(self, params: Mapping[str, Any]) -> dict[str, Any]:
        try:
            row = self.profiles.archive(
                _request_id(params["requestId"]),
                profile_id=_bounded(params["profileId"], "profileId"),
                expected_version=_version(params["expectedVersion"]),
            )
        except ServerError as exc:
            raise self._profile_error(exc) from exc
        return {"profile": self._profile(row)}

    def _profile_error(self, exc: ServerError) -> WireError:
        error = WireError.from_server_error(exc)
        current = getattr(exc, "current", None)
        if current is not None:
            error.current = self._profile(current)
        return error

    def provider_models_list(self, params: Mapping[str, Any]) -> dict[str, Any]:
        self._require_model_configs()
        include = params["includeArchived"]
        if not isinstance(include, bool):
            raise WireError("INVALID_REQUEST", "includeArchived must be a boolean")
        return {"items": self.model_configs.list(include_archived=include), "nextCursor": None}

    def provider_models_create(self, params: Mapping[str, Any]) -> dict[str, Any]:
        self._require_model_configs()
        body = self._provider_model_body(params, creating=True)
        body.update(self._provenance(params) or {})
        record = self.model_configs.create(_request_id(params["requestId"]), body)
        return {"providerModel": record}

    # -- Order 57: harness runtime artifact management ---------------------

    def _artifact_store(self):
        if self.artifact_store is None:
            raise WireError(
                "UNAVAILABLE",
                "this composition has no artifact management face",
                {"internalCode": "ARTIFACT_STORE_UNAVAILABLE"},
            )
        return self.artifact_store

    def provider_artifacts_list(self, params: Mapping[str, Any]) -> dict[str, Any]:
        harness = _bounded(params["harness"], "harness", 64)
        store = self._artifact_store()
        try:
            versions = store.installed(harness)
            return {
                "harness": harness,
                "versions": [
                    {"version": version, **store.summary(harness, version)}
                    for version in versions
                ],
                "current": store.current_reference(harness),
            }
        except ArtifactStoreError as exc:
            raise _artifact_error(exc) from exc

    def provider_artifacts_install(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Install a version the execution side has staged under the store's
        incoming area. The digest is re-derived from the staged copy before
        anything is visible; the declared digest must match."""
        harness = _bounded(params["harness"], "harness", 64)
        version = _bounded(params["version"], "version", 64)
        token = _bounded(params["sourceToken"], "sourceToken")
        digest = _bounded(params["digest"], "digest", 128)
        store = self._artifact_store()
        try:
            source = store.incoming_dir(token)
            receipt = store.install(harness, version, source, digest)
        except ArtifactStoreError as exc:
            raise _artifact_error(exc) from exc
        shutil.rmtree(source, ignore_errors=True)
        return {"harness": harness, "version": version,
                "digest": receipt["digest"], "entries": receipt["entries"]}

    def provider_artifacts_rollback(self, params: Mapping[str, Any]) -> dict[str, Any]:
        harness = _bounded(params["harness"], "harness", 64)
        version = _bounded(params["version"], "version", 64)
        store = self._artifact_store()
        try:
            store.rollback(harness, version)
            return {"harness": harness, "current": store.current_reference(harness)}
        except ArtifactStoreError as exc:
            raise _artifact_error(exc) from exc

    def usage_aggregate(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Order 53: per-session usage aggregation over the ledger.

        Read-only: sums only what the families' own stores reported, with an
        explicit unknown-turn count for everything else. No estimation, no
        cross-session leakage.
        """
        if self.usage_aggregator is None:
            raise WireError(
                "UNAVAILABLE",
                "this composition exposes no usage-aggregation face",
                {"internalCode": "USAGE_AGGREGATOR_UNAVAILABLE"},
            )
        session_ids = params.get("sessions") or []
        if not isinstance(session_ids, list) or not all(
            isinstance(item, str) for item in session_ids
        ):
            raise WireError("INVALID_REQUEST", "sessions must be a list of ids")
        result = self.usage_aggregator.aggregate_by_session(session_ids)
        return {"sessions": [
            {"sessionId": sid, **entry} for sid, entry in result.items()
        ]}

    def usage_export(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Order 53: export the same aggregate as a JSON document."""
        return self.usage_aggregate(params)

    def provider_models_probe_models(self, params: Mapping[str, Any]) -> dict[str, Any]:
        self._require_model_configs()
        self._provenance(params)  # validate the optional provenance, if given
        return self.model_configs.probe_models({
            "baseUrl": _bounded(params["baseUrl"], "baseUrl", 512),
            "credentialId": params.get("credentialId"),
        })

    def provider_models_probe_connection(self, params: Mapping[str, Any]) -> dict[str, Any]:
        self._require_model_configs()
        self._provenance(params)
        return self.model_configs.probe_connection({
            "baseUrl": _bounded(params["baseUrl"], "baseUrl", 512),
            "credentialId": params.get("credentialId"),
        })

    def provider_models_update(self, params: Mapping[str, Any]) -> dict[str, Any]:
        self._require_model_configs()
        record_id = _bounded(params["providerModelId"], "providerModelId")
        try:
            body = self._provider_model_body(params, creating=False)
            body.update(self._provenance(params) or {})
            record = self.model_configs.update(
                record_id, _version(params["expectedVersion"]),
                _request_id(params["requestId"]),
                body,
            )
        except ServerError as exc:
            error = WireError.from_server_error(exc)
            current = getattr(exc, "current", None)
            if current is not None:
                error.current = self.model_configs.project(current)
            raise error from exc
        return {"providerModel": record}

    def provider_models_archive(self, params: Mapping[str, Any]) -> dict[str, Any]:
        self._require_model_configs()
        try:
            record = self.model_configs.archive(
                _bounded(params["providerModelId"], "providerModelId"),
                _version(params["expectedVersion"]), _request_id(params["requestId"]),
            )
        except ServerError as exc:
            error = WireError.from_server_error(exc)
            references = getattr(exc, "references", None)
            if references is not None:
                error.details["referenceIds"] = list(references)
            raise error from exc
        return {"providerModel": record}

    #: Order 55: where the endpoint facts came from. `fieldsSource` is one of
    #: the three honest answers (a preset catalogue, a pulled model list, or
    #: the user's own hand entry); the endpoint fields themselves are optional
    #: and stay absent when their source does not supply them.
    #:
    #: These are wire field names, and they stay wire field names all the way
    #: into the service body: `service.create/update` reads `body["authStyle"]`
    #: and hands the SQL column name to the repository, which is the only place
    #: allowed to know one. A handler that translated to columns here would
    #: write nothing at all and still answer 200.
    _PROVENANCE_ENUMS = {
        "authStyle": {"api_key", "oauth", "none"},
        "wireApi": {"chat_completions", "responses"},
        "fieldsSource": {"preset", "pulled", "manual"},
    }
    _PROVENANCE_FIELDS = ("baseUrl", "authStyle", "wireApi", "fieldsSource")

    @classmethod
    def _provenance(cls, params: Mapping[str, Any]) -> dict[str, str | None] | None:
        """Order 112: a field the request did not name keeps its stored value;
        a field it named as `null` is a request to *clear* it. Collapsing the
        two is how a user's edit gets eaten: the row keeps the old fact, the
        answer is 200, and nothing says the clear was ignored."""
        raw = params.get("provenance")
        if raw is None:
            return None
        if (not isinstance(raw, Mapping)
                or not set(raw) <= set(cls._PROVENANCE_FIELDS)):
            raise WireError("INVALID_REQUEST", "provenance carries unknown fields")
        provenance: dict[str, str | None] = {}
        for field in cls._PROVENANCE_FIELDS:
            if field not in raw:
                continue
            value = raw[field]
            if value is None:
                provenance[field] = None
                continue
            value = _bounded(str(value), f"provenance.{field}", 512)
            allowed = cls._PROVENANCE_ENUMS.get(field)
            if allowed is not None and value not in allowed:
                raise WireError(
                    "INVALID_REQUEST", f"provenance.{field} is not a known value",
                )
            provenance[field] = value
        return provenance or None

    def _provider_model_body(
        self, params: Mapping[str, Any], *, creating: bool,
    ) -> dict[str, Any]:
        body = {
            "displayName": _bounded(params["displayName"], "displayName", 128),
            "credentialId": params["credentialId"],
            "configuration": _assignments(params["configuration"], "configuration"),
            "models": _models(params["models"]),
        }
        if body["credentialId"] is not None:
            body["credentialId"] = _bounded(body["credentialId"], "credentialId")
        if creating:
            body["harness"] = _bounded(params["harness"], "harness", 64)
            body["provider"] = _bounded(params["provider"], "provider", 128)
        return body

    def _require_model_configs(self) -> None:
        if self.model_configs is None:
            raise WireError("UNAVAILABLE", "Provider/Model configuration storage is unavailable")

    # -- configuration -----------------------------------------------------

    def config_describe(self, params: Mapping[str, Any]) -> dict[str, Any]:
        _require(params, "profileId", "workspaceId")
        profile = self.profiles.records.get(_bounded(params["profileId"], "profileId"))
        controls = self._controls(profile)
        return {"descriptor": {
            "profileId": profile["id"],
            "workspaceId": params["workspaceId"],
            "controls": controls,
            "securityLockedIds": self._locked_controls(profile),
            "effectTiming": "next_send",
        }}

    def config_resolve(self, params: Mapping[str, Any]) -> dict[str, Any]:
        _require(params, "profileId", "workspaceId", "overrides")
        profile = self.profiles.records.get(_bounded(params["profileId"], "profileId"))
        overrides = _overrides(params) or []
        known = {control["controlId"] for control in self._controls(profile)}
        invalid = [
            {"controlId": item["controlId"], "reason": "unknown_control"}
            for item in overrides if item["controlId"] not in known
        ]
        invalid += [
            {"controlId": item["controlId"], "reason": "security_locked"}
            for item in overrides if item["controlId"] in self._locked_controls(profile)
        ]
        if invalid:
            return {"outcome": "rejected", "invalidControls": invalid}
        effective = self._effective_values(profile, overrides)
        return {"outcome": "resolved", "effective": [
            {"controlId": control_id, "value": value} for control_id, value in effective.items()
        ]}

    def _configuration(self, profile: Mapping[str, Any]) -> dict[str, Any]:
        stored = json.loads(self.objects.read(profile["config_object_digest"]))
        return dict(stored.get("configuration") or {})

    def _controls(self, profile: Mapping[str, Any]) -> list[dict[str, Any]]:
        harness = profile["harness_type"]
        controls: list[dict[str, Any]] = []
        configured = self._configuration(profile)
        if harness in self.harnesses:
            descriptor = self.harnesses.get(harness)
            for control_id, values in sorted((descriptor.control_options or {}).items()):
                current = configured.get(control_id)
                references = _model_reference_list(current)
                holds_reference = bool(references) and self.model_configs is not None
                # The control the deployment names as its model control takes a
                # Provider/Model reference and declares no static values for it
                # (the reference comes from the directory, and
                # `freeze_execution_configuration` refuses anything else). As an
                # enum of an empty list it offered a first-time reader nothing to
                # choose, and a brand-new Profile could not be given a model at
                # all; as a slot it says what it wants, and the client fills it
                # from the directory it already holds. A declared value list means
                # this really is an enumeration and stays one.
                if (descriptor.model_control_id == control_id and not values
                        and self.model_configs is not None):
                    controls.append({
                        "kind": "model_slot", "controlId": control_id, "editable": True,
                        "slots": self._slot_entries(control_id, references, current),
                    })
                    continue
                if holds_reference:
                    controls.append({
                        "kind": "model_slot", "controlId": control_id, "editable": True,
                        "slots": self._slot_entries(control_id, references, current),
                    })
                    continue
                controls.append({
                    "kind": "enum", "controlId": control_id,
                    "values": list(values), "editable": True,
                    **({"currentValue": current} if isinstance(current, str) else {}),
                })
        for control_id, value in sorted(configured.items()):
            if any(control["controlId"] == control_id for control in controls):
                continue
            control = {
                "kind": "boolean" if isinstance(value, bool) else "string",
                "controlId": control_id, "editable": True,
                "currentValue": value,
            }
            if control["kind"] == "string":
                control["multiline"] = False
            controls.append(control)
        return controls

    def _slot_entries(self, control_id: str, references: list[dict[str, str]],
                      current: Any) -> list[dict[str, Any]]:
        """One entry per Provider/Model reference a model control holds (order 125).

        Before this, a control holding a *list* of references projected exactly
        one slot built from `control_id` alone, so a client could not see past
        the first seat - 092's G8 named that shape ("只投影第一个槽必须门红").

        The legacy single-reference shape is emitted **verbatim**
        (`{"name": control_id, "model": ...}`) because order 60's wire test pins
        that dict key for key; only a value that is actually a list gains the
        table-reference keys. A reference that no longer resolves is not papered
        over: `model_configs.reference` raises typed, same as before.
        """
        if self.model_configs is None:
            return [{"name": control_id, "model": None}]
        if not isinstance(current, list):
            one = references[0] if references else None
            return [{"name": control_id,
                     "model": (self.model_configs.reference(one["providerId"], one["modelId"])
                               if one else None)}]
        entries = []
        for index, reference in enumerate(references):
            model = self.model_configs.reference(reference["providerId"], reference["modelId"])
            entries.append({
                "name": f"{control_id}[{index}]", "slotIndex": index,
                "table": SLOT_TABLE, "providerId": reference["providerId"],
                "modelId": reference["modelId"], "model": model,
            })
        return entries

    def _locked_controls(self, profile: Mapping[str, Any]) -> list[str]:
        """Controls a security rule pins; they can never be overridden."""
        harness = profile["harness_type"]
        if harness in self.harnesses:
            return list(self.harnesses.get(harness).security_locked_controls or ())
        return []

    def _effective_values(
        self, profile: Mapping[str, Any], overrides: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """接入默认 < Profile 默认 < 明确临时覆盖, with locks applied last."""
        discovered: dict[str, Any] = {}
        harness = profile["harness_type"]
        if harness in self.harnesses:
            descriptor = self.harnesses.get(harness)
            for control_id, values in (descriptor.control_options or {}).items():
                if values:
                    discovered[control_id] = values[0]
        effective = {**discovered, **self._configuration(profile)}
        for item in overrides:
            effective[item["controlId"]] = item["value"]
        for control_id in self._locked_controls(profile):
            configured = self._configuration(profile)
            if control_id in configured:
                effective[control_id] = configured[control_id]
        return effective

    # -- sessions -----------------------------------------------------------

    def sessions_list(self, params: Mapping[str, Any]) -> dict[str, Any]:
        _require(params, "includeArchived")
        include_archived = params["includeArchived"]
        if not isinstance(include_archived, bool):
            raise WireError("INVALID_REQUEST", "includeArchived must be a boolean")
        workspace_id = params.get("workspaceId")
        if workspace_id is not None:
            workspace_id = _bounded(workspace_id, "workspaceId")
        page = params.get("page") or {}
        if not isinstance(page, Mapping) or set(page) - {"cursor", "limit"}:
            raise WireError("INVALID_REQUEST", "page shape is invalid")
        limit = page.get("limit", 200)
        if isinstance(limit, bool) or not isinstance(limit, int) or not (1 <= limit <= 500):
            raise WireError("INVALID_REQUEST", "page.limit must be between 1 and 500")
        catalog_scope = "sessions_" + digest({
            "workspaceId": workspace_id, "includeArchived": include_archived,
        }).split(":", 1)[1][:24]
        after_rowid = 0
        if page.get("cursor") is not None:
            _scope, after_rowid = self.codec.decode(
                str(page["cursor"]), expected_session=catalog_scope,
            )
        rows = self.sessions.records.list_sessions(
            workspace_id=workspace_id, include_archived=include_archived,
            after_rowid=after_rowid, limit=limit + 1,
        )
        has_more = len(rows) > limit
        visible = rows[:limit]
        next_cursor = None
        if has_more and visible:
            next_cursor = self.codec.encode(catalog_scope, int(visible[-1]["catalog_rowid"]))
        return {
            "items": [session_record(row) for row in visible],
            "nextCursor": next_cursor,
        }

    def sessions_update(self, params: Mapping[str, Any]) -> dict[str, Any]:
        _require(params, "requestId", "sessionId", "expectedVersion")
        supplied = {name for name in ("displayName", "pinned", "workspaceId") if name in params}
        if not supplied:
            raise WireError("INVALID_REQUEST", "a Session update must change at least one field")
        display_name = None
        if "displayName" in params:
            display_name = _bounded(params["displayName"], "displayName", 512)
        pinned = params.get("pinned")
        if "pinned" in params and not isinstance(pinned, bool):
            raise WireError("INVALID_REQUEST", "pinned must be a boolean")
        workspace_id = None
        if "workspaceId" in params:
            workspace_id = _bounded(params["workspaceId"], "workspaceId")
        session_id = _bounded(params["sessionId"], "sessionId")
        expected_version = _version(params["expectedVersion"])
        request_body = {
            "sessionId": session_id, "expectedVersion": expected_version,
            **({"displayName": display_name} if "displayName" in params else {}),
            **({"pinned": pinned} if "pinned" in params else {}),
            **({"workspaceId": workspace_id} if "workspaceId" in params else {}),
        }
        updated = self.sessions.records.update_session(
            session_id=session_id, expected_version=expected_version,
            request_id=_bounded(params["requestId"], "requestId"),
            request_digest=digest(request_body), display_name=display_name,
            pinned=pinned if "pinned" in params else None,
            workspace_id=workspace_id,
        )
        return {"session": updated}

    def sessions_archive(self, params: Mapping[str, Any]) -> dict[str, Any]:
        _require(params, "requestId", "sessionId", "expectedVersion")
        session_id = _bounded(params["sessionId"], "sessionId")
        expected_version = _version(params["expectedVersion"])
        archived = self.sessions.records.archive_session(
            session_id=session_id, expected_version=expected_version,
            request_id=_bounded(params["requestId"], "requestId"),
            request_digest=digest({
                "sessionId": session_id, "expectedVersion": expected_version,
            }),
        )
        return {"session": archived}

    def sessions_create_and_send(self, params: Mapping[str, Any]) -> dict[str, Any]:
        _require(params, "requestId", "workspaceId", "profileId", "message", "overrides")
        workspace_id = _bounded(params["workspaceId"], "workspaceId")
        workspace = self._require_workspace_resolution().records.get(workspace_id)
        message = self._message(params["message"], workspace)
        overrides = _overrides(params) or []
        request_id = _bounded(params["requestId"], "requestId")
        digest_value = digest({
            "workspaceId": params["workspaceId"], "profileId": params["profileId"],
            "message": message, "overrides": overrides,
        })
        public_message = self._public_message(message)
        outcome, body = self.sessions.accept_intent(
            session_id=None,
            workspace_id=workspace_id,
            profile_id=_bounded(params["profileId"], "profileId"),
            request_id=request_id, request_digest=digest_value,
            message_object_digest=self._publish_message(message),
            public_message=public_message, overrides=overrides,
            # The first accepted user message is a deterministic fallback
            # title, not a claim that the Agent generated a summary.  Native
            # clients otherwise receive only an opaque Server session id.
            display_name=(" ".join(public_message["text"].split())[:72]
                          if self.sessions.native_profile_identity is not None else None),
        )
        if outcome == "accepted" and body.get("executionId"):
            self.sessions.file_core_records(body["executionId"])
            self._dispatch(body["executionId"])
        if outcome in {"accepted", "replay"}:
            session = self.sessions.records.get_session(body["sessionId"])
            return {
                "outcome": "accepted",
                "session": session_record({
                    "id": session["session_id"], "version": session["version"],
                    "workspace_id": session["workspace_id"], "profile_id": session["profile_id"],
                    "display_name": session.get("display_name") or session["session_id"],
                    "pinned": session.get("pinned", False),
                    "archived_at": session.get("archived_at"),
                    "created_at": session["created_at"], "updated_at": session["updated_at"],
                }),
                "executionId": body["executionId"],
                "configVersion": body["configVersion"],
            }
        return {
            "outcome": "rejected_before_accept",
            "reason": body.get("reason", "rejected"),
            "invalidControls": body.get("invalidControls"),
        }

    def sessions_send(self, params: Mapping[str, Any]) -> dict[str, Any]:
        _require(params, "requestId", "sessionId", "message", "overrides")
        overrides = _overrides(params) or []
        request_id = _bounded(params["requestId"], "requestId")
        session_id = _bounded(params["sessionId"], "sessionId")
        session = self.sessions.records.get_session(session_id)
        workspace = self._require_workspace_resolution().records.get(session["workspace_id"])
        message = self._message(params["message"], workspace)
        digest_value = digest({
            "sessionId": session_id, "message": message, "overrides": overrides,
        })
        public_message = self._public_message(message)
        outcome, body = self.sessions.accept_intent(
            session_id=session_id, workspace_id=None,
            profile_id=session["profile_id"], request_id=request_id,
            request_digest=digest_value,
            message_object_digest=self._publish_message(message),
            public_message=public_message, overrides=overrides,
        )
        if outcome == "accepted" and body.get("executionId"):
            self.sessions.file_core_records(body["executionId"])
            self._dispatch(body["executionId"])
        if outcome == "replay":
            return {
                "outcome": "accepted",
                "executionId": body.get("executionId"),
                "configVersion": body.get("configVersion"),
                "queueItemId": body.get("queueItemId"),
            }
        return {
            "outcome": "accepted",
            "executionId": body.get("executionId"),
            "configVersion": body.get("configVersion"),
            "queueItemId": body.get("queueItemId"),
        }

    def sessions_switch_profile(self, params: Mapping[str, Any]) -> dict[str, Any]:
        _require(params, "requestId", "sessionId", "profileId", "expectedVersion")
        request_id = _bounded(params["requestId"], "requestId")
        session_id = _bounded(params["sessionId"], "sessionId")
        profile_id = _bounded(params["profileId"], "profileId")
        outcome, body = self.sessions.records.switch_profile(
            session_id=session_id, profile_id=profile_id,
            expected_version=_version(params["expectedVersion"]), request_id=request_id,
            request_digest=digest({"sessionId": session_id, "profileId": profile_id,
                                   "expectedVersion": params["expectedVersion"]}),
        )
        if outcome == "replay":
            return body
        return body

    def send_outcome_query(self, params: Mapping[str, Any]) -> dict[str, Any]:
        _require(params, "requestId")
        return self.sessions.records.intent_outcome(_bounded(params["requestId"], "requestId"))

    def queue_get(self, params: Mapping[str, Any]) -> dict[str, Any]:
        _require(params, "sessionId")
        items = self.queue.list(_bounded(params["sessionId"], "sessionId"))
        return {"items": [self._queue_item(item) for item in items]}

    def queue_withdraw(self, params: Mapping[str, Any]) -> dict[str, Any]:
        _require(params, "requestId", "sessionId", "itemId", "expectedVersion")
        request_id = _bounded(params["requestId"], "requestId")
        status, body = self.queue.withdraw(
            session_id=_bounded(params["sessionId"], "sessionId"),
            item_id=_bounded(params["itemId"], "itemId"),
            expected_version=_version(params["expectedVersion"]), request_id=request_id,
            request_digest=digest({
                "sessionId": params["sessionId"], "itemId": params["itemId"],
                "expectedVersion": params["expectedVersion"],
            }),
        )
        if body.get("outcome") == "withdrawn":
            return {"outcome": "withdrawn", "item": self._queue_item(body["item"])}
        item = body.get("item")
        return {
            "outcome": "too_late", "reason": body.get("reason", "too_late"),
            "item": self._queue_item(item) if item else None,
        }

    def _queue_item(self, item: Mapping[str, Any]) -> dict[str, Any]:
        body = dict(item["message"]) if isinstance(item.get("message"), Mapping) else self._stored_message(item["messageText"])
        return {
            "itemId": item["itemId"], "version": item["version"],
            "submittedAt": item["submittedAt"], "message": body,
            "profileId": item["profileId"], "configVersion": item["configVersion"],
            "state": item["state"],
        }

    # -- runs and approvals --------------------------------------------------

    def runs_stop(self, params: Mapping[str, Any]) -> dict[str, Any]:
        _require(params, "requestId", "sessionId", "executionId")
        session_id = _bounded(params["sessionId"], "sessionId")
        execution_id = _bounded(params["executionId"], "executionId")
        context = self.sessions.records.get_turn_context(execution_id)
        if context["session_id"] != session_id:
            raise WireError("NOT_FOUND", "Execution does not belong to this Session")
        terminal = self.sessions.records.TERMINAL_TURN_STATES
        if context["state"] in terminal:
            return {
                "outcome": "already_finished", "executionId": execution_id,
                "reason": context.get("error_code") or context["state"],
            }
        if self.execution is None:
            return {"outcome": "unconfirmed", "reason": "EXECUTION_CAPABILITY_UNAVAILABLE"}
        self.sessions.records.record_cancel_request(execution_id)
        cancel_outcome = self.execution.cancel_execution(execution_id)
        accepted = cancel_outcome == CancelOutcome.CONFIRMED_STOPPED
        # The same rule the REST cancel applies: an active turn that is asked to
        # stop takes its delegated children with it, whether or not this
        # process's own stop could be confirmed.
        self.sessions.cancel_descendants(execution_id)
        if not accepted:
            # Stop was asked for but the process could not be confirmed stopped;
            # saying "stopped" here would be a lie.
            return {"outcome": "unconfirmed", "reason": "STOP_NOT_CONFIRMED"}
        return {"outcome": "stop_requested", "executionId": execution_id}

    def approvals_decide(self, params: Mapping[str, Any]) -> dict[str, Any]:
        _require(params, "requestId", "approvalId", "decision", "scope", "expectedVersion")
        decision = params["decision"]
        if decision not in {"allow", "deny"}:
            raise WireError("INVALID_REQUEST", "decision must be allow or deny")
        scope = params["scope"]
        if not isinstance(scope, Mapping) or scope.get("kind") not in {"once", "bounded"}:
            raise WireError("INVALID_REQUEST", "scope must be once or a bounded grant")
        if scope["kind"] == "once" and set(scope) != {"kind"}:
            raise WireError("INVALID_REQUEST", "once scope has unexpected fields")
        if scope["kind"] == "bounded" and (
            set(scope) != {"kind", "until", "environmentId"}
            or scope.get("until") != "session_end"
            or not (scope.get("environmentId") is None
                    or isinstance(scope.get("environmentId"), str)
                    and scope.get("environmentId"))
        ):
            raise WireError("INVALID_REQUEST", "bounded scope is invalid")
        request_id = _bounded(params["requestId"], "requestId")
        _status, body = self.approvals.decide(
            approval_id=_bounded(params["approvalId"], "approvalId"),
            decision=decision, scope=dict(scope),
            expected_version=_version(params["expectedVersion"]), request_id=request_id,
        )
        if body.get("outcome") == "recorded" and hasattr(self.execution, "decide_approval"):
            # The Server decision is committed first.  A transport failure may
            # fail the execution, but can never execute an unrecorded grant.
            self.execution.decide_approval(
                params["approvalId"], decision, dict(scope),
            )
        return body

    # -- history ------------------------------------------------------------

    def history_snapshot(self, params: Mapping[str, Any]) -> dict[str, Any]:
        _require(params, "sessionId")
        session_id = _bounded(params["sessionId"], "sessionId")
        page = params.get("page") or {}
        if not isinstance(page, Mapping) or set(page) - {"cursor", "limit"}:
            raise WireError("INVALID_REQUEST", "page shape is invalid")
        limit = page.get("limit", 200)
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise WireError("INVALID_REQUEST", "page.limit must be an integer")
        if not (1 <= limit <= 500):
            raise WireError("INVALID_REQUEST", "page.limit must be between 1 and 500")
        live_cursor = params.get("cursor")
        older_cursor = page.get("cursor")
        if live_cursor is not None and older_cursor is not None:
            raise WireError(
                "INVALID_REQUEST", "live resume and backward page cursors are mutually exclusive",
            )
        after = None
        before = None
        if live_cursor is not None:
            _session, after = self.codec.decode(str(live_cursor), expected_session=session_id)
        if older_cursor is not None:
            _session, before = self.codec.decode_older(
                str(older_cursor), expected_session=session_id,
            )
        try:
            rows, head, has_older = self.sessions.records.history_page(
                session_id, after=after, before=before, limit=limit,
            )
        except ServerError as exc:
            if exc.code == "EVENT_CURSOR_AHEAD":
                # An out-of-range cursor is answered with an explicit resync
                # rather than silently dropping events.
                return {"outcome": "resync_required", "reason": "cursor_beyond_history"}
            raise
        frames = [frame for frame in (event_frame(row, self.codec) for row in rows) if frame]
        # Forward recovery advances by the returned raw log rows so additional
        # batches remain readable. Initial/backward snapshots join live at the
        # head read in the same SQLite snapshot, closing the subscribe window.
        resume_seq = (
            int(rows[-1]["seq"]) if after is not None and rows else
            after if after is not None else head
        )
        next_older = None
        if has_older and rows:
            next_older = self.codec.encode_older(session_id, int(rows[0]["seq"]))
        return {
            "outcome": "snapshot",
            "frames": frames,
            "resumeCursor": self.codec.encode(session_id, resume_seq),
            "olderCursor": next_older,
        }

    def event_stream_batch(
        self, session_id: str, cursor: str | None, *, limit: int = 200,
    ) -> tuple[list[dict[str, Any]], str]:
        """Read the next persisted wire frame batch for the live channel."""
        after = 0
        if cursor:
            _session, after = self.codec.decode(cursor, expected_session=session_id)
        try:
            rows = self.sessions.records.raw_events(session_id, after, limit=limit)
        except ServerError as exc:
            if exc.code == "EVENT_CURSOR_AHEAD":
                raise WireError("INVALID_REQUEST", "event cursor is beyond current history") from exc
            raise
        frames = [frame for frame in (event_frame(row, self.codec) for row in rows) if frame]
        next_seq = int(rows[-1]["seq"]) if rows else after
        return frames, self.codec.encode(session_id, next_seq)

    # -- helpers ------------------------------------------------------------

    def _message(self, value: Any, workspace: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(value, Mapping) or "text" not in value or "attachments" not in value:
            raise WireError("INVALID_REQUEST", "message needs text and attachments")
        text = value["text"]
        if not isinstance(text, str) or not (1 <= len(text) <= 4096):
            raise WireError("INVALID_REQUEST", "message.text must be between 1 and 4096 characters")
        attachments = value["attachments"]
        if not isinstance(attachments, list):
            raise WireError("INVALID_REQUEST", "message.attachments must be a list")
        if len(attachments) > 32:
            raise WireError("INVALID_REQUEST", "message has too many attachments")
        resolved = []
        total = 0
        for item in attachments:
            if not isinstance(item, Mapping) or set(item) != {"ref", "displayName", "mediaKind"}:
                raise WireError("INVALID_REQUEST", "attachment shape is invalid")
            if (not isinstance(item["ref"], str) or len(item["ref"]) > 4096
                    or not isinstance(item["displayName"], str)
                    or len(item["displayName"]) > 512):
                raise WireError("INVALID_REQUEST", "attachment names are invalid")
            if item["mediaKind"] not in {"file", "image", "other"}:
                raise WireError("INVALID_REQUEST", "attachment mediaKind is invalid")
            relative = PurePosixPath(item["ref"])
            if (relative.is_absolute() or not relative.parts
                    or any(part in {"", ".", ".."} for part in relative.parts)
                    or relative.as_posix() != item["ref"]):
                raise WireError("INVALID_REQUEST", "attachment ref must be a normalized workspace path")
            try:
                content, content_digest = self._require_workspace_resolution().read_workspace_file(
                    workspace, relative.as_posix(),
                )
            except Exception as exc:
                raise WireError("INVALID_REQUEST", "attachment is outside the authorized workspace or unreadable") from exc
            total += len(content)
            if total > 8 * 1024 * 1024:
                raise WireError("INVALID_REQUEST", "attachments exceed the bounded message size")
            record = self.objects.publish(content)
            if record.digest != content_digest:
                raise WireError("OUTCOME_UNKNOWN", "attachment changed during capture")
            resolved.append({
                **dict(item), "_contentDigest": record.digest, "_size": record.size,
                "_mime": mimetypes.guess_type(str(item["displayName"]))[0]
                or ("image/png" if item["mediaKind"] == "image" else "application/octet-stream"),
            })
        return {"text": text, "attachments": resolved}

    def _publish_message(self, message: Mapping[str, Any]) -> str:
        return self.objects.publish(canonical({"schema_version": 1, "message": dict(message)})).digest

    @staticmethod
    def _public_message(message: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "text": str(message.get("text", "")),
            "attachments": [
                {key: item[key] for key in ("ref", "displayName", "mediaKind")}
                for item in message.get("attachments", ())
            ],
        }

    def _stored_message(self, digest_value: str) -> dict[str, Any]:
        stored = json.loads(self.objects.read(digest_value))
        message = dict(stored.get("message") or stored)
        message["attachments"] = [
            {key: item[key] for key in ("ref", "displayName", "mediaKind")}
            for item in message.get("attachments", ())
        ]
        return message

    def _dispatch(self, execution_id: str) -> None:
        try:
            # INC1c c-5/s-c2: the effective configuration is frozen at
            # acceptance, so dispatch carries nothing but the execution id
            # (the legacy overrides parameter and its mapping helper retired
            # with the joint signature note).
            self.execution.accept(execution_id)
        except Exception:
            # Dispatch failures are durable execution facts recorded by the
            # execution port; acceptance itself stays a valid receipt.
            pass
