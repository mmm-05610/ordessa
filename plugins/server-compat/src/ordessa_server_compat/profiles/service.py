"""Profile use cases: validated creation and registry-backed capability views."""
from __future__ import annotations

import json
from typing import Any

from server_plugin_api import ServerError, unavailable
from ordessa_server_compat.execution import HarnessRegistry
from ordessa_server_compat.profiles.repository import ProfileRecords
from server_plugin_api import canonical, digest, reject_sensitive_keys


class ProfileService:
    def __init__(self, records: ProfileRecords, idempotency, objects, *,
                 harnesses: HarnessRegistry,
                 credentials) -> None:
        self.records = records
        self.idempotency = idempotency
        self.objects = objects
        self.harnesses = harnesses
        self.credentials = credentials
        self.model_configs = None

    def bind_model_configs(self, model_configs) -> None:
        self.model_configs = model_configs

    def create(self, key: str, body: dict[str, Any]):
        harness_type = body["harness_type"]
        if harness_type not in self.harnesses:
            raise unavailable("HARNESS_UNAVAILABLE", "Requested Harness is not configured")
        descriptor = self.harnesses.get(harness_type)
        reject_sensitive_keys(body["configuration"])
        if body.get("credential_id") is not None:
            if descriptor.credential_kind is None:
                raise unavailable("HARNESS_UNAVAILABLE", "Requested Harness is not configured")
            self.credentials.get(body["credential_id"], kind=descriptor.credential_kind)
        if descriptor.configuration_validator is not None:
            try:
                descriptor.configuration_validator(body["configuration"])
            except ServerError:
                raise
            except (TypeError, ValueError) as exc:
                raise ServerError("PROFILE_CONFIGURATION_INVALID", str(exc), status=422) from exc
        record = self.objects.publish(canonical({
            "schema_version": 1, "harness_type": harness_type,
            "configuration": body["configuration"],
        }))
        status, result = self.records.create(
            key=key, request_digest=digest(body), name=body["name"],
            harness_type=harness_type, config_digest=record.digest,
            credential_id=body.get("credential_id"),
        )
        # capabilities 永远来自 registry 的 canonical 静态声明（已校验的已注册扩展），
        # 不来自数据库行里的任何旧快照。
        result["capabilities"] = self.harnesses.canonical_claims(harness_type)
        return status, result

    def list(self, *, include_archived: bool = True) -> list[dict[str, Any]]:
        items = []
        for row in self.records.list(include_archived=include_archived):
            items.append({
                "profile_id": row["id"], "name": row["name"],
                "harness_type": row["harness_type"],
                "config_revision": row["config_revision"],
                "native_generation": row["native_generation"],
                "credential_id": row["credential_id"], "run_state": row["run_state"],
                "account_id": row["account_id"] if "account_id" in row.keys() else None,
                "recovery_pending": bool(row["recovery_pending"]),
                "capabilities": self.harnesses.canonical_claims(row["harness_type"]),
            })
        return items

    def create_wire(self, key: str, *, display_name: str, harness: str,
                    credential_id: str | None = None) -> dict[str, Any]:
        _status, body = self.create(key, {
            "name": display_name, "harness_type": harness,
            "configuration": {}, "credential_id": credential_id,
        })
        return self.records.get(body["profile_id"])

    def update_display_name(
        self, key: str, *, profile_id: str, expected_version: int, display_name: str,
    ) -> dict[str, Any]:
        _status, body = self.records.update_display_name(
            profile_id=profile_id, expected_version=expected_version,
            display_name=display_name, key=key,
            request_digest=digest({
                "profileId": profile_id, "expectedVersion": expected_version,
                "displayName": display_name,
            }),
        )
        return body["profile"]

    def update_configuration(
        self, key: str, *, profile_id: str, expected_version: int,
        values: list[dict[str, Any]],
    ) -> dict[str, Any]:
        profile = self.records.get(profile_id)
        if profile["archived_at"] is not None:
            raise ServerError("PROFILE_ARCHIVED", "Profile is archived", status=409)
        reject_sensitive_keys(values)
        if self.model_configs is not None:
            self.model_configs.validate_references(profile["harness_type"], values)
        configuration = {item["controlId"]: item["value"] for item in values}
        descriptor = self.harnesses.get(profile["harness_type"])
        if descriptor.configuration_validator is not None:
            try:
                descriptor.configuration_validator(configuration)
            except ServerError:
                raise
            except (TypeError, ValueError) as exc:
                raise ServerError("PROFILE_CONFIGURATION_INVALID", str(exc), status=422) from exc
        record = self.objects.publish(canonical({
            "schema_version": 1, "harness_type": profile["harness_type"],
            "configuration": configuration,
        }))
        _status, body = self.records.update_configuration(
            profile_id=profile_id, expected_version=expected_version,
            config_digest=record.digest, key=key,
            request_digest=digest({
                "profileId": profile_id, "expectedVersion": expected_version, "values": values,
            }),
        )
        return body["profile"]

    def archive(self, key: str, *, profile_id: str, expected_version: int) -> dict[str, Any]:
        _status, body = self.records.archive(
            profile_id=profile_id, expected_version=expected_version, key=key,
            request_digest=digest({
                "profileId": profile_id, "expectedVersion": expected_version,
            }),
        )
        return body["profile"]
