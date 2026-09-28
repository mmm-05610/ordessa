"""Provider-neutral validation and object projections for model configurations."""
from __future__ import annotations

import json
from typing import Any, Mapping

from server_plugin_api import ServerError, unavailable
from ordessa_server_compat.model_configs.provider_protocols import (
    normalize_model_facts, normalize_protocols, validate_endpoints,
)
from ordessa_server_compat.model_configs.repository import KEEP
from server_plugin_api import canonical, digest, reject_sensitive_keys


class ProviderModelService:
    def __init__(self, records, objects, *, harnesses, credentials, profiles,
                 secret_store=None) -> None:
        self.records = records
        self.objects = objects
        self.harnesses = harnesses
        self.credentials = credentials
        self.profiles = profiles
        #: Order 55: the probes pull the credential through the store at call
        #: time; the value lives only inside the probe call (memory/header).
        self.secret_store = secret_store

    def _probe_credential(self, credential_id: str | None) -> str | None:
        if credential_id is None or self.secret_store is None:
            return None
        row = self.credentials.get(credential_id)
        return self.secret_store.read(row["secret_locator"]).decode("utf-8").strip()

    def probe_models(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Order 55: one bounded outbound GET of the declared /models."""
        from ordessa_server_compat.model_configs.probe import ProbeError, pull_models

        try:
            api_key = self._probe_credential(params.get("credentialId"))
            result = pull_models(str(params["baseUrl"]), api_key)
        except ProbeError as error:
            return {"status": "failed", "code": error.code, "models": []}
        return {"status": "ok", "models": list(result.models)}

    def probe_connection(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Order 55: one bounded reachability check of the declared endpoint."""
        from ordessa_server_compat.model_configs.probe import probe_connection

        try:
            api_key = self._probe_credential(params.get("credentialId"))
            result = probe_connection(str(params["baseUrl"]), api_key)
        except ProbeError as error:
            return {"status": "failed", "code": error.code}
        return {"status": result.status, "detail": result.detail}

    def list(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        return [self.project(row) for row in self.records.list(include_archived=include_archived)]

    def create(self, key: str, body: dict[str, Any]) -> dict[str, Any]:
        norm = self._validate(body, creating=True)
        config = self.objects.publish(canonical(_config_payload(body, norm)))
        models = self.objects.publish(
            canonical({"schema_version": 1, "models": norm["models"]}))
        _status, result = self.records.create(
            key=key, request_digest=digest(body), display_name=body["displayName"],
            harness_type=body["harness"], provider_type=body["provider"],
            credential_id=body.get("credentialId"), config_digest=config.digest,
            models_digest=models.digest,
            base_url=body.get("baseUrl"), auth_style=body.get("authStyle"),
            wire_api=body.get("wireApi"), fields_source=body.get("fieldsSource"),
        )
        return self.project(self.records.get(result["providerModelId"]))

    def update(self, record_id: str, expected_version: int, key: str, body: dict[str, Any]):
        current = self.records.get(record_id)
        # Work Order 126 union of 092 x Order 112 (both guards kept):
        #   * 112 - the stored record is the base, so any field the caller does
        #     not name keeps its value; the four provenance columns name KEEP to
        #     mean "not named" and pass an explicit null to mean "clear".
        #   * 092 - the merged body then runs through _validate, which normalizes
        #     and strictly validates the recognized protocol facts (protocols /
        #     endpoints / model capabilities); because 112 seeded the merge from
        #     project(current), a protocol set is carried forward when omitted,
        #     so the old hand-written "preserve prior" is no longer needed.
        merged = {
            **self.project(current), **body,
            "harness": current["harness_type"], "provider": current["provider_type"],
        }
        norm = self._validate(merged, creating=False)
        config = self.objects.publish(canonical(_config_payload(merged, norm)))
        models = self.objects.publish(
            canonical({"schema_version": 1, "models": norm["models"]}))
        _status, result = self.records.update(
            record_id=record_id, expected_version=expected_version, key=key,
            request_digest=digest(body), display_name=merged["displayName"],
            credential_id=merged.get("credentialId"), config_digest=config.digest,
            models_digest=models.digest,
            base_url=body["baseUrl"] if "baseUrl" in body else KEEP,
            auth_style=body["authStyle"] if "authStyle" in body else KEEP,
            wire_api=body["wireApi"] if "wireApi" in body else KEEP,
            fields_source=body["fieldsSource"] if "fieldsSource" in body else KEEP,
        )
        return self.project(self.records.get(result["providerModelId"]))

    def archive(self, record_id: str, expected_version: int, key: str):
        references = self.profile_references(record_id)
        if references:
            error = ServerError(
                "REFERENCE_CONFLICT", "Provider/Model config is referenced by active Profiles", status=409,
            )
            error.references = references  # type: ignore[attr-defined]
            raise error
        _status, result = self.records.archive(
            record_id=record_id, expected_version=expected_version, key=key,
            request_digest=digest({"providerModelId": record_id, "expectedVersion": expected_version}),
        )
        return self.project(self.records.get(result["providerModelId"]))

    def validate_references(self, harness: str, values: list[dict[str, Any]]) -> None:
        for assignment in values:
            for reference in _model_references(assignment.get("value")):
                row = self.records.get(reference["providerId"])
                # A shared record (harness_type NULL) may be referenced by any
                # harness (092); a bound record still refuses the wrong harness.
                if row["archived_at"] is not None or (
                        row["harness_type"] is not None and row["harness_type"] != harness):
                    raise ServerError(
                        "PROFILE_CONFIGURATION_INVALID",
                        "Provider/Model reference is archived or for a different Harness", status=422,
                    )
                model_ids = {item["modelId"] for item in self._models(row)}
                if reference["modelId"] not in model_ids:
                    raise ServerError(
                        "PROFILE_CONFIGURATION_INVALID", "Referenced model was not found", status=422,
                    )

    def freeze_execution_configuration(
        self, harness: str, configuration: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Resolve one declared model control into a non-secret immutable projection."""
        descriptor = self.harnesses.get(harness)
        control_id = descriptor.model_control_id
        if control_id is None:
            return None
        reference = configuration.get(control_id)
        if not isinstance(reference, Mapping):
            raise ServerError(
                "PROFILE_CONFIGURATION_INVALID",
                f"Control {control_id} must select a Provider/Model configuration", status=422,
            )
        provider_id = reference.get("providerId")
        model_id = reference.get("modelId")
        if not isinstance(provider_id, str) or not provider_id or not isinstance(model_id, str) or not model_id:
            raise ServerError(
                "PROFILE_CONFIGURATION_INVALID", "Provider/Model reference is invalid", status=422,
            )
        row = self.records.get(provider_id)
        if row["archived_at"] is not None or (
                row["harness_type"] is not None and row["harness_type"] != harness):
            raise ServerError(
                "PROFILE_CONFIGURATION_INVALID",
                "Provider/Model reference is archived or for a different Harness", status=422,
            )
        model = next((item for item in self._models(row) if item["modelId"] == model_id), None)
        if model is None:
            raise ServerError(
                "PROFILE_CONFIGURATION_INVALID", "Referenced model was not found", status=422,
            )
        if model.get("availability") == "unavailable":
            raise ServerError(
                "PROFILE_CONFIGURATION_INVALID", "Referenced model is unavailable", status=422,
            )
        credential_id = row["credential_id"]
        if descriptor.credential_kind is not None and credential_id is not None:
            self.credentials.get(credential_id, kind=descriptor.credential_kind)
        stored = json.loads(self.objects.read(row["config_object_digest"]))
        # Order 092 stage 4: only a *declared* mismatch blocks. Both the record
        # and this Harness must state protocols; if they do and share none, the
        # combination is genuinely impossible and is a typed refusal. Either side
        # undeclared -> do not block (unknown is never treated as unavailable).
        provider_protocols = set(stored.get("protocols") or [])
        harness_protocols = self._registry_wire_protocols(harness)
        if provider_protocols and harness_protocols and not (provider_protocols & harness_protocols):
            raise ServerError(
                "PROTOCOL_INCOMPATIBLE",
                f"Provider declares {sorted(provider_protocols)} but Harness "
                f"{harness!r} declares {sorted(harness_protocols)}; no protocol in common",
                status=422,
            )
        return {
            "providerModelId": row["id"],
            "providerModelVersion": int(row["version"]),
            "provider": row["provider_type"],
            "model": model_id,
            "credentialId": credential_id,
            "configuration": dict(stored.get("configuration") or {}),
            # Order 093 wiring input (092's flagged residual): pass the record's
            # declared protocol facts to the native materializer so a real turn
            # can write the record's base URL + dialect instead of the template
            # constant. Emitted ONLY when declared - an unchanged record freezes
            # byte-for-byte as before (093 G6 "no facts => zero regression").
            **({"protocols": list(stored["protocols"])} if stored.get("protocols") else {}),
            **({"endpoints": dict(stored["endpoints"])} if stored.get("endpoints") else {}),
        }

    def reference(self, provider_id: str, model_id: str) -> dict[str, Any]:
        row = self.records.get(provider_id)
        match = next((item for item in self._models(row) if item["modelId"] == model_id), None)
        if match is None:
            raise ServerError("PROVIDER_MODEL_NOT_FOUND", "Referenced model was not found", status=404)
        return {
            "providerId": provider_id, "modelId": model_id,
            "availability": match["availability"],
            "unavailableReason": match.get("unavailableReason"),
        }
    def profile_references(self, record_id: str) -> list[str]:
        references = []
        for profile in self.profiles.list(include_archived=False):
            stored = json.loads(self.objects.read(profile["config_object_digest"]))
            if any(ref["providerId"] == record_id for ref in _model_references(stored)):
                references.append(profile["id"])
        return references

    def project(self, row: Mapping[str, Any]) -> dict[str, Any]:
        config = json.loads(self.objects.read(row["config_object_digest"]))
        declared = config.get("protocols")
        endpoints = config.get("endpoints") or {}
        return {
            "id": row["id"], "version": int(row["version"]),
            "displayName": row["display_name"], "harness": row["harness_type"],
            "provider": row["provider_type"], "credentialId": row["credential_id"],
            "configuration": [
                {"controlId": key, "value": value}
                for key, value in sorted(dict(config.get("configuration") or {}).items())
            ],
            "models": self._models(row), "archivedAt": row["archived_at"],
            # Order 092 stage 3: the record's canonical protocol set and its
            # per-protocol endpoints. ``protocolsDeclared`` is the honest flag the
            # front end reads to know whether the (empty) set means "none" or "not
            # stated" - an undeclared record is unknown, never incompatible.
            "protocols": list(declared) if declared is not None else None,
            "endpoints": dict(endpoints) if endpoints else None,
            "protocolsDeclared": declared is not None,
            # Order 092 stage 4: which Harness could use this record and via which
            # protocol - derived on read from both sides' declarations, never
            # stored, so it can never go stale against a changed deployment.
            "compatibility": self._derive_compatibility(declared),
            # Order 55: the endpoint facts and where they came from; absent
            # means unknown, never a guessed default.
            "provenance": ({"baseUrl": row["base_url"],
                            "authStyle": row["auth_style"], "wireApi": row["wire_api"],
                            "fieldsSource": row["fields_source"]}
                           if row["base_url"] or row["auth_style"] or row["wire_api"]
                           or row["fields_source"] else None),
            "createdAt": row["created_at"], "updatedAt": row["updated_at"],
        }

    def _models(self, row: Mapping[str, Any]) -> list[dict[str, Any]]:
        return list(json.loads(self.objects.read(row["models_object_digest"])).get("models") or [])

    def _registry_wire_protocols(self, harness: str) -> set[str]:
        """The canonical protocols one registered Harness seat declares it speaks.

        Tolerates a plain-mapping harness table (as unit tests supply) so the
        derivation degrades to "unknown" instead of crashing on a test double.
        """
        getter = getattr(self.harnesses, "wire_protocols", None)
        if getter is None:
            return set()
        return set(getter(harness) or {})

    def _derive_compatibility(self, declared: Any) -> list[dict[str, str]]:
        """Which Harnesses could use this record, and via which protocol.

        Both sides must declare for a pair to appear: an undeclared record
        (``declared is None``) yields no rows and reads as ``protocolsDeclared:
        false``, and a family that declares no protocols contributes nothing -
        that is *unknown*, not "incompatible" (the two are different states).
        """
        if not declared:
            return []
        registered = getattr(self.harnesses, "registered", None)
        if registered is None:
            return []
        declared_set = set(declared)
        pairs: list[dict[str, str]] = []
        for harness in sorted(registered()):
            supported = self._registry_wire_protocols(harness) & declared_set
            for protocol in sorted(supported):
                pairs.append({"harness": harness, "protocol": protocol})
        return pairs

    def _validate(self, body: Mapping[str, Any], *, creating: bool) -> dict[str, Any]:
        harness = body["harness"]
        # Order 092 stage 2: a shared (harness-neutral) upstream record carries no
        # harness. It may be referenced by any declaration-compatible harness; its
        # credential kind is validated against the *consuming* harness at freeze,
        # not here (there is no single descriptor to check against). A bound record
        # (harness set) still must name a configured harness, exactly as before.
        descriptor = None
        if harness is not None:
            if harness not in self.harnesses:
                raise unavailable("HARNESS_UNAVAILABLE", "Requested Harness is not configured")
            descriptor = self.harnesses.get(harness)
        reject_sensitive_keys(body["configuration"])
        credential_id = body.get("credentialId")
        if credential_id is not None and descriptor is not None:
            if descriptor.credential_kind is None:
                raise ServerError(
                    "PROFILE_CONFIGURATION_INVALID", "Harness does not accept credentials", status=422,
                )
            self.credentials.get(credential_id, kind=descriptor.credential_kind)
        models = body["models"]
        ids = [item["modelId"] for item in models]
        if not models or len(ids) != len(set(ids)):
            raise ServerError(
                "PROFILE_CONFIGURATION_INVALID", "Models must be non-empty and unique", status=422,
            )
        for item in models:
            if item["availability"] == "unavailable" and not item.get("unavailableReason"):
                raise ServerError(
                    "PROFILE_CONFIGURATION_INVALID", "Unavailable models require a reason", status=422,
                )
        # Order 092 stage 3: canonical protocol vocabulary + model facts. Dialects
        # collapse to the four canonical values and an unknown one is a typed
        # refusal; endpoints must be keyed by a declared protocol and follow the
        # probe's URL discipline; capabilities are strict (documented keys only).
        declared = None
        if body.get("protocols") is not None:
            declared = normalize_protocols(body["protocols"])
        endpoints = validate_endpoints(body.get("endpoints"), declared or [])
        normalized_models = [normalize_model_facts(item) for item in models]
        return {"protocols": declared, "endpoints": endpoints, "models": normalized_models}


def _config_payload(body: Mapping[str, Any], norm: Mapping[str, Any]) -> dict[str, Any]:
    """The canonical configuration object for a record: control values plus the
    optional protocol facts (092). Absent protocol set / empty endpoints are not
    written, so an undeclared record reads back with those keys absent, not empty.
    """
    payload: dict[str, Any] = {
        "schema_version": 1, "configuration": {
            item["controlId"]: item["value"] for item in body["configuration"]
        },
    }
    if norm["protocols"] is not None:
        payload["protocols"] = norm["protocols"]
    if norm["endpoints"]:
        payload["endpoints"] = norm["endpoints"]
    return payload


def _model_references(value: Any):
    if isinstance(value, Mapping):
        if set(value) >= {"providerId", "modelId"}:
            yield {"providerId": str(value["providerId"]), "modelId": str(value["modelId"])}
        for nested in value.values():
            yield from _model_references(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _model_references(nested)
