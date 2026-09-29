# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (src/ordessa_model_provider/plugin.py, verbatim)
"""The Model Provider domain plugin: owner of ``providerModels.*``.

Registration contract (`specs/002-model-provider/contracts/backend-wire.md`):
the six wire methods with the exact shapes, error codes and projections the
existing consumers observe, registered once under ``ordessa.model-provider``.
The plugin host refuses a second owner for any of these ids at activation
(``DuplicateMethodError`` is the single-owner gate, spec G2); unloading the
plugin removes exactly its methods while the records stay (G3, US-8).

Optional cooperation travels as constructor-injected ports (the composition
wires them; the host contract keeps optional edges out of ``requires``):
``harnesses`` (the harness registry the legacy composition already supplied),
``reference_port`` (absent -> archive refuses ``REFERENCE_STATE_UNKNOWN``,
FR-ARCH-2) and ``secret_store`` (probe-time credential pull, Order 55).
The catalog is exported as the ``model_provider.catalog`` provided port.
"""
from __future__ import annotations

from typing import Any, Mapping

from server_plugin_api import (
    ServerMethodDescriptor,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
    WIRE_ERROR_FAMILIES_API_VERSION,
    WIRE_ERROR_FAMILIES_POINT_ID,
    Contribution,
    ContributionBatch,
)

from ordessa_model_provider.catalog import ModelCatalogService
from ordessa_model_provider.choices import (
    ADAPTER_MISSING, CONFIG_REVISION_CONFLICT, CREDENTIAL_UNRESOLVED,
    MODEL_NOT_FOUND, OPERATION_UNKNOWN, PROVIDER_ARCHIVED, PROVIDER_NOT_FOUND,
    PROTOCOL_UNSUPPORTED, RESUME_UNAVAILABLE, SELECTION_UNSUPPORTED,
    TARGET_STALE, VERIFICATION_MISMATCH, VERSION_UNVERIFIED,
    ModelChoiceService,
)
from ordessa_model_provider.records import ProviderModelRecords
from ordessa_server.errors import ServerError
from ordessa_server.wire.errors import WireError
# foundation@8844c475bc adaptation: the wire's shared param-shape helpers live
# in the contract package and the domain-shape validators in the compat
# package (host handlers.py docstring, T014-S2c) - the frozen refusal strings
# cannot drift between the host wall and this handler.
from ordessa_server_compat.wire_validators import assignments as _assignments
from ordessa_server_compat.wire_validators import models as _models
from server_plugin_api.wire_shape import bounded as _bounded
from server_plugin_api.wire_shape import request_id as _request_id
from server_plugin_api.wire_shape import version as _version

PLUGIN_ID = "ordessa.model-provider"

#: 014 PB-4 (REQ-Z3-7): the frozen 13-code → wire-family mapping, self-published
#: through ``wire.error-families`` (api-requests.md REQ-Z3-7 list, verbatim).
#: Before this contribution the codes rode ``details.internalCode`` with a
#: temporary UNAVAILABLE family; after publication the transport resolves them
#: exactly, with no host-table edit and no UNAVAILABLE masquerade.
_ERROR_FAMILIES = {
    PROVIDER_NOT_FOUND: "NOT_FOUND",
    MODEL_NOT_FOUND: "NOT_FOUND",
    PROVIDER_ARCHIVED: "CONFLICT_REQUEST",
    CONFIG_REVISION_CONFLICT: "CONFLICT_VERSION",
    SELECTION_UNSUPPORTED: "CAPABILITY_UNSUPPORTED",
    OPERATION_UNKNOWN: "OUTCOME_UNKNOWN",
    ADAPTER_MISSING: "CAPABILITY_UNSUPPORTED",
    VERSION_UNVERIFIED: "CAPABILITY_UNSUPPORTED",
    TARGET_STALE: "CONFLICT_REQUEST",
    RESUME_UNAVAILABLE: "CAPABILITY_UNSUPPORTED",
    VERIFICATION_MISMATCH: "OUTCOME_UNKNOWN",
    CREDENTIAL_UNRESOLVED: "UNAUTHENTICATED",
    PROTOCOL_UNSUPPORTED: "CAPABILITY_UNSUPPORTED",
}


class ModelProviderPlugin:
    """Registers the Provider/Model configuration domain with the host."""

    def __init__(self, *, harnesses: Any | None = None, reference_port: Any | None = None,
                 secret_store: Any | None = None,
                 harness_config_port: Any | None = None) -> None:
        self._harnesses = harnesses
        self._reference_port = reference_port
        self._secret_store = secret_store
        #: The C2 consumer view (assess/apply/read-back); injected by the
        #: composition when the harness side provides it. Absent -> every
        #: choice verdict is ``unknown`` and reconcile answers
        #: ``unknown-outcome`` - never ``ready``/``confirmed`` (REQ-Z3-2).
        self._harness_config_port = harness_config_port
        self.catalog: ModelCatalogService | None = None

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            id=PLUGIN_ID, display_name="Model Provider",
            version="1", requires=(),
        )

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        ports = context.ports
        database = ports["database"]
        objects = ports["objects"]
        idempotency = ports["idempotency"]
        credentials = ports["credentials"]
        catalog = ModelCatalogService(
            ProviderModelRecords(database, idempotency), objects,
            harnesses=self._harnesses, credentials=credentials,
            reference_port=self._reference_port, secret_store=self._secret_store,
        )
        choices = ModelChoiceService(
            catalog, harness_config_port=self._harness_config_port,
            idempotency=idempotency,
        )
        self.catalog = catalog
        self.choices = choices
        handlers = _Handlers(catalog, choices)
        methods = tuple(
            ServerMethodDescriptor(
                method_id=method_id, required_params=frozenset(required),
                optional_params=frozenset(optional), handler=getattr(handlers, name),
                owner=PLUGIN_ID,
            )
            for method_id, required, optional, name in _METHODS
        )
        return ServerPluginRegistration(
            methods=methods,
            provided_ports={"model_provider.catalog": catalog,
                            "model_provider.choices": choices},
            # 014 PB-4 (REQ-Z3-7): the domain's failure codes self-publish
            # their wire families through the open host point — the mapping
            # lives with the plugin that raises the codes, never in the host
            # table. A conflicting row from another owner refuses at stage.
            contributions=ContributionBatch((
                Contribution(WIRE_ERROR_FAMILIES_POINT_ID,
                             WIRE_ERROR_FAMILIES_API_VERSION, dict(_ERROR_FAMILIES)),
            )),
        )


#: method_id, required, optional, handler name — frozen from the legacy
#: ``_PARAM_SHAPES`` rows (specs/002-model-provider/contracts/backend-wire.md).
_METHODS = (
    ("providerModels.list", {"includeArchived"}, set(), "provider_models_list"),
    ("providerModels.create",
     {"requestId", "displayName", "harness", "provider", "credentialId",
      "configuration", "models"},
     {"provenance"}, "provider_models_create"),
    ("providerModels.update",
     {"requestId", "providerModelId", "expectedVersion", "displayName", "credentialId",
      "configuration", "models"},
     {"provenance"}, "provider_models_update"),
    ("providerModels.archive",
     {"requestId", "providerModelId", "expectedVersion"},
     set(), "provider_models_archive"),
    ("providerModels.probeModels",
     {"requestId", "baseUrl"}, {"credentialId", "provenance"},
     "provider_models_probe_models"),
    ("providerModels.probeConnection",
     {"requestId", "baseUrl"}, {"credentialId"},
     "provider_models_probe_connection"),
    # -- Z3 T01 increments: the versioned ``modelProvider.*`` surface. Names
    # frozen in specs/011-z3-model-provider/t00-freeze.md §8; the legacy six
    # rows above are untouched (MP-12 keeps them wire-faithful).
    ("modelProvider.catalogue", set(), {"includeArchived", "cursor"},
     "model_provider_catalogue"),
    ("modelProvider.saveProviderConfig", {"operationKey", "patch"},
     {"expectedVersion"}, "model_provider_save_provider_config"),
    ("modelProvider.probeProvider",
     {"operationKey", "providerConfigId", "expectedVersion"}, set(),
     "model_provider_probe_provider"),
    ("modelProvider.inspectChoice", {"target", "choice"}, set(),
     "model_provider_inspect_choice"),
    ("modelProvider.chooseForSession", {"target", "choice", "operationKey"},
     {"expectedOverlayRevision"}, "model_provider_choose_for_session"),
    ("modelProvider.queryChoice", {"target"}, set(),
     "model_provider_query_choice"),
    ("modelProvider.reconcileChoice", {"target", "operationId"}, set(),
     "model_provider_reconcile_choice"),
)

#: Order 112: a provenance field the request did not name keeps its stored
#: value; a field named as ``null`` is a request to *clear* it. The enums are
#: the wire's spellings of the dialect/facts vocabulary (kept exactly as the
#: legacy wire spelled them - including the pre-normalization ``wireApi``
#: values, which ``service._validate`` canonicalizes afterwards).
_PROVENANCE_ENUMS = {
    "authStyle": {"api_key", "oauth", "none"},
    "wireApi": {"chat_completions", "responses"},
    "fieldsSource": {"preset", "pulled", "manual"},
}
_PROVENANCE_FIELDS = ("baseUrl", "authStyle", "wireApi", "fieldsSource")


class _Handlers:
    """The wire handler bodies: the six legacy ones behavior-frozen from the
    legacy core wire, plus the Z3 ``modelProvider.*`` surface."""

    def __init__(self, catalog: ModelCatalogService, choices) -> None:
        self._catalog = catalog
        self._choices = choices

    def provider_models_list(self, params: Mapping[str, Any]) -> dict[str, Any]:
        include = params["includeArchived"]
        if not isinstance(include, bool):
            raise WireError("INVALID_REQUEST", "includeArchived must be a boolean")
        return {"items": self._catalog.list(include_archived=include), "nextCursor": None}

    def provider_models_create(self, params: Mapping[str, Any]) -> dict[str, Any]:
        body = self._provider_model_body(params, creating=True)
        body.update(self._provenance(params) or {})
        record = self._catalog.create(_request_id(params["requestId"]), body)
        return {"providerModel": record}

    def provider_models_update(self, params: Mapping[str, Any]) -> dict[str, Any]:
        record_id = _bounded(params["providerModelId"], "providerModelId")
        try:
            body = self._provider_model_body(params, creating=False)
            body.update(self._provenance(params) or {})
            record = self._catalog.update(
                record_id, _version(params["expectedVersion"]),
                _request_id(params["requestId"]),
                body,
            )
        except ServerError as exc:
            error = WireError.from_server_error(exc)
            current = getattr(exc, "current", None)
            if current is not None:
                error.current = self._catalog.project(current)
            raise error from exc
        return {"providerModel": record}

    def provider_models_archive(self, params: Mapping[str, Any]) -> dict[str, Any]:
        try:
            record = self._catalog.archive(
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

    def provider_models_probe_models(self, params: Mapping[str, Any]) -> dict[str, Any]:
        self._provenance(params)  # validate the optional provenance, if given
        return self._catalog.probe_models({
            "baseUrl": _bounded(params["baseUrl"], "baseUrl", 512),
            "credentialId": params.get("credentialId"),
        })

    def provider_models_probe_connection(self, params: Mapping[str, Any]) -> dict[str, Any]:
        self._provenance(params)
        return self._catalog.probe_connection({
            "baseUrl": _bounded(params["baseUrl"], "baseUrl", 512),
            "credentialId": params.get("credentialId"),
        })

    # -- Z3 T01: the modelProvider.* surface ----------------------------------

    def model_provider_catalogue(self, params: Mapping[str, Any]) -> dict[str, Any]:
        include = params.get("includeArchived", False)
        if not isinstance(include, bool):
            raise WireError("INVALID_REQUEST", "includeArchived must be a boolean")
        cursor = params.get("cursor")
        if cursor is not None and (isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0):
            raise WireError("INVALID_REQUEST", "cursor must be a non-negative integer")
        try:
            return self._choices.catalogue(include_archived=include, cursor=cursor)
        except ServerError as exc:
            raise WireError.from_server_error(exc) from exc

    def model_provider_save_provider_config(self, params: Mapping[str, Any]) -> dict[str, Any]:
        operation_key = _request_id(params["operationKey"])
        patch = params["patch"]
        if not isinstance(patch, Mapping) or not patch:
            raise WireError("INVALID_REQUEST", "patch must be a non-empty object")
        provider_config_id = patch.get("providerConfigId")
        try:
            if provider_config_id is None:
                if params.get("expectedVersion") is not None:
                    raise WireError(
                        "INVALID_REQUEST", "expectedVersion applies only to an update")
                body = self._provider_model_body(patch, creating=True)
                body.update(self._provenance(patch) or {})
                record = self._catalog.create(operation_key, body)
            else:
                if params.get("expectedVersion") is None:
                    raise WireError(
                        "INVALID_REQUEST", "an update requires expectedVersion")
                body = self._provider_model_body(patch, creating=False)
                body.update(self._provenance(patch) or {})
                record = self._catalog.update(
                    _bounded(provider_config_id, "providerConfigId"),
                    _version(params["expectedVersion"]), operation_key, body,
                )
        except ServerError as exc:
            if exc.code == "RECORD_VERSION_CONFLICT":
                # The new surface speaks the design's failure-code vocabulary;
                # the current projection still rides the error (MP-08).
                conflict = ServerError(
                    CONFIG_REVISION_CONFLICT,
                    "the config changed before the save; revisit and re-save",
                    status=409,
                )
                raw = getattr(exc, "current", None)
                if raw is not None:
                    conflict.current = self._catalog.project(raw)  # type: ignore[attr-defined]
                raise WireError.from_server_error(conflict) from exc
            raise WireError.from_server_error(exc) from exc
        return {"providerModel": record}

    def model_provider_probe_provider(self, params: Mapping[str, Any]) -> dict[str, Any]:
        from ordessa_server.ids import now

        record_id = _bounded(params["providerConfigId"], "providerConfigId")
        expected_version = _version(params["expectedVersion"])
        try:
            row = self._catalog.records.get(record_id)
        except ServerError as exc:
            if exc.code == "PROVIDER_MODEL_NOT_FOUND":
                missing = ServerError(
                    PROVIDER_NOT_FOUND, "Provider config was not found", status=404)
                raise WireError.from_server_error(missing) from exc
            raise WireError.from_server_error(exc) from exc
        if int(row["version"]) != expected_version:
            conflict = ServerError(
                CONFIG_REVISION_CONFLICT,
                "the config changed before the probe", status=409)
            conflict.current = self._catalog.project(row)  # type: ignore[attr-defined]
            raise WireError.from_server_error(conflict)
        if row["archived_at"] is not None:
            archived = ServerError(PROVIDER_ARCHIVED, "Provider config is archived", status=409)
            raise WireError.from_server_error(archived)
        if not row["base_url"]:
            invalid = ServerError(
                "PROFILE_CONFIGURATION_INVALID",
                "the saved config carries no endpoint fact to probe", status=422)
            raise WireError.from_server_error(invalid)
        # The bounded one-shot probe of the *saved* endpoint; the secret is
        # pulled only inside the call and the fact is written nowhere (MP-04).
        fact = self._catalog.probe_models({
            "baseUrl": row["base_url"], "credentialId": row["credential_id"],
        })
        return {
            "providerConfigId": record_id,
            "configVersion": int(row["version"]),
            "observedAt": now(),
            **fact,
        }

    def model_provider_inspect_choice(self, params: Mapping[str, Any]) -> dict[str, Any]:
        try:
            return self._choices.inspect_choice(params["target"], params["choice"])
        except ServerError as exc:
            raise WireError.from_server_error(exc) from exc

    def model_provider_choose_for_session(self, params: Mapping[str, Any]) -> dict[str, Any]:
        operation_key = _request_id(params["operationKey"])
        overlay = params.get("expectedOverlayRevision")
        if overlay is not None:
            overlay = _bounded(str(overlay), "expectedOverlayRevision", 128)
        try:
            return self._choices.choose_for_session(
                params["target"], params["choice"], operation_key,
                expected_overlay_revision=overlay)
        except ServerError as exc:
            raise WireError.from_server_error(exc) from exc

    def model_provider_query_choice(self, params: Mapping[str, Any]) -> dict[str, Any]:
        try:
            return self._choices.inspect(params["target"])
        except ServerError as exc:
            raise WireError.from_server_error(exc) from exc

    def model_provider_reconcile_choice(self, params: Mapping[str, Any]) -> dict[str, Any]:
        operation_id = params["operationId"]
        if isinstance(operation_id, bool) or not isinstance(operation_id, int):
            raise WireError("INVALID_REQUEST", "operationId must be the queued sequence number")
        try:
            return self._choices.reconcile(params["target"], operation_id)
        except ServerError as exc:
            raise WireError.from_server_error(exc) from exc

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

    @staticmethod
    def _provenance(params: Mapping[str, Any]) -> dict[str, str | None] | None:
        raw = params.get("provenance")
        if raw is None:
            return None
        if (not isinstance(raw, Mapping)
                or not set(raw) <= set(_PROVENANCE_FIELDS)):
            raise WireError("INVALID_REQUEST", "provenance carries unknown fields")
        provenance: dict[str, str | None] = {}
        for field in _PROVENANCE_FIELDS:
            if field not in raw:
                continue
            value = raw[field]
            if value is None:
                provenance[field] = None
                continue
            value = _bounded(str(value), f"provenance.{field}", 512)
            allowed = _PROVENANCE_ENUMS.get(field)
            if allowed is not None and value not in allowed:
                raise WireError(
                    "INVALID_REQUEST", f"provenance.{field} is not a known value",
                )
            provenance[field] = value
        return provenance or None
