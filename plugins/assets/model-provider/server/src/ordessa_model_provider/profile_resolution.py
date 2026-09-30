"""Resolve a saved atomic choice using the injected, current model catalogue.

The composition injects the actual C2 choice schema; this domain never imports
the adapters or Profile. Resolution is preparation, not runtime confirmation.
Secret values, probes, and secret-store access are deliberately absent.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

from ordessa_harness_api import ContractError, ValueSchema, validate_json
from ordessa_server.errors import ServerError
from ordessa_model_provider.choices import (
    CREDENTIAL_UNRESOLVED, MODEL_NOT_FOUND, PROVIDER_ARCHIVED,
    PROVIDER_NOT_FOUND, PROTOCOL_UNSUPPORTED, SELECTION_UNSUPPORTED,
    CONFIG_REVISION_CONFLICT,
)
from ordessa_model_provider.protocols import (
    normalize_model_facts, normalize_protocol, normalize_protocols,
    validate_capabilities, validate_endpoints,
)


@dataclass(frozen=True)
class ResolvedProfileModelChoice:
    """Immutable snapshots with fresh dictionaries on every consumer read."""

    _payload_json: str
    _revisions_json: str

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self._payload_json)

    @property
    def revisions(self) -> dict[str, Any]:
        return json.loads(self._revisions_json)


class ProfileModelChoiceResolver:
    def __init__(self, catalog, *, payload_schema: ValueSchema) -> None:
        self._catalog = catalog
        self._schema = payload_schema

    def resolve(
        self, choice: Mapping[str, Any], *, harness_id: str,
        brand_fields: Mapping[str, Any], protocol: str | None = None,
        required_capabilities: Mapping[str, Any] | None = None,
    ) -> ResolvedProfileModelChoice:
        """Resolve exactly {harnessId, providerConfigId, modelId}.

        ``brand_fields`` contains server-observed instance facts. In particular
        provider_in_instance and credential_changed must be explicit booleans.
        No default can imply those observations. More than one common protocol
        requires an explicit selection. Revisions fence preparation; they do
        not claim that the runtime has applied the returned payload.
        """
        if (not isinstance(choice, Mapping)
                or set(choice) != {"harnessId", "providerConfigId", "modelId"}
                or any(not isinstance(v, str) or not v.strip() or "\x00" in v
                       for v in choice.values())):
            raise ServerError("PROFILE_FACET_VALUE_INVALID", "invalid atomic model choice", status=422)
        if choice["harnessId"] != harness_id:
            raise ServerError("PROFILE_HARNESS_MISMATCH", "choice belongs to another Harness", status=422)
        catalog = self._catalog
        if harness_id not in catalog.harnesses:
            raise ServerError("HARNESS_UNAVAILABLE", "Harness is not registered", status=422)
        if not isinstance(brand_fields, Mapping) or any(
            not isinstance(brand_fields.get(key), bool)
            for key in ("provider_in_instance", "credential_changed")
        ):
            raise ServerError("RUNTIME_FACTS_UNVERIFIED", "explicit observed instance facts required", status=422)
        try:
            fields = validate_json(brand_fields)
        except ContractError as error:
            raise ServerError("PROFILE_CONFIGURATION_INVALID", "invalid non-secret brand facts", status=422) from error
        try:
            row = dict(catalog.records.get(choice["providerConfigId"]))
        except ServerError as error:
            if error.code == "PROVIDER_MODEL_NOT_FOUND":
                raise ServerError(PROVIDER_NOT_FOUND, "Provider config was not found", status=404) from error
            raise
        if row["archived_at"] is not None:
            raise ServerError(PROVIDER_ARCHIVED, "Provider config is archived", status=409)
        if row["harness_type"] not in (None, harness_id):
            raise ServerError(SELECTION_UNSUPPORTED, "Provider config belongs to another Harness", status=422)
        projection = catalog.project(row)
        matches = [model for model in projection["models"] if model.get("modelId") == choice["modelId"]]
        if not matches:
            raise ServerError(MODEL_NOT_FOUND, "Model is not in the provider config", status=404)
        if len(matches) != 1:
            raise ServerError("PROVIDER_MODEL_INVALID", "model ids must be unique", status=422)
        model = normalize_model_facts(matches[0])
        if model.get("availability") != "available":
            raise ServerError(SELECTION_UNSUPPORTED, "Model availability is not confirmed", status=422)
        required = validate_capabilities(required_capabilities) or {}
        actual = model.get("capabilities") or {}
        if any(key not in actual or actual[key] != value for key, value in required.items()):
            raise ServerError(SELECTION_UNSUPPORTED, "Model capability requirement is not confirmed", status=422)
        provider_protocols = normalize_protocols(projection.get("protocols") or [])
        harness_protocols = normalize_protocols(list(catalog.harnesses.wire_protocols(harness_id)))
        common = set(provider_protocols) & set(harness_protocols)
        if model.get("protocols") is not None:
            common &= set(model["protocols"])
        if protocol is not None:
            selected = normalize_protocol(protocol)
            if selected not in common:
                raise ServerError(PROTOCOL_UNSUPPORTED, "Selected protocol is not declared by every participant", status=422)
        elif len(common) == 1:
            selected = next(iter(common))
        else:
            code = "PROTOCOL_AMBIGUOUS" if common else PROTOCOL_UNSUPPORTED
            raise ServerError(code, "A single confirmed protocol selection is required", status=422)
        endpoints = validate_endpoints(projection.get("endpoints"), provider_protocols)
        credential_ref = row["credential_id"]
        if credential_ref is not None:
            descriptor = catalog.harnesses.get(harness_id)
            kind = descriptor.credential_kind
            if not isinstance(credential_ref, str) or not credential_ref or kind is None:
                raise ServerError(CREDENTIAL_UNRESOLVED, "Harness cannot accept this credential reference", status=422)
            try:
                catalog.credentials.get(credential_ref, kind=kind)
            except ServerError as error:
                raise ServerError(CREDENTIAL_UNRESOLVED, "Credential reference cannot be validated", status=422) from error
        provider = projection.get("provider")
        if not isinstance(provider, str) or not provider.strip() or "\x00" in provider:
            raise ServerError("PROFILE_CONFIGURATION_INVALID", "Provider identity is invalid", status=422)
        payload = {"provider": provider, "model": choice["modelId"],
                   "protocol": selected, "endpoint": endpoints.get(selected),
                   "credentialRef": f"ref://{credential_ref}" if credential_ref is not None else None,
                   "brandFields": fields}
        try:
            payload = self._schema.validate(payload)
        except ContractError as error:
            raise ServerError("PROFILE_CONFIGURATION_INVALID", "C2 payload schema rejected model choice", status=422) from error
        # Detect revisions changing during multi-object reads. The caller must
        # revalidate this separate snapshot at the actual admission boundary.
        revisions = {"harnessId": harness_id, "providerConfigId": row["id"],
                     "configVersion": int(row["version"]),
                     "configObjectDigest": row["config_object_digest"],
                     "modelsObjectDigest": row["models_object_digest"],
                     "harnessProtocols": harness_protocols}
        current = catalog.records.get(row["id"])
        if (any(current[key] != row[key] for key in (
            "version", "config_object_digest", "models_object_digest", "archived_at",
            "harness_type", "provider_type", "credential_id"))
                or harness_id not in catalog.harnesses
                or normalize_protocols(list(catalog.harnesses.wire_protocols(harness_id))) != harness_protocols):
            raise ServerError(CONFIG_REVISION_CONFLICT, "Catalogue changed during resolution", status=409)
        return ResolvedProfileModelChoice(
            json.dumps(payload, allow_nan=False), json.dumps(revisions, allow_nan=False))
