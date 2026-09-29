"""AR-1/W-1：wire 写面退役后的测试摆桌子直调助手。

被退役的 ``providerModels.*`` 六方法与 ``profiles.*`` 写方法的测试调用，改为对
**同一条服务链**（``compat.handlers`` 端口上 handler 绑定的 model_configs /
profiles 服务对象）的 Python 直调；返回形状与 wire 应答逐键一致，调用方断言
零改动。这不是绕过产品写新链——写入路径与 wire 时代完全同一条，只是不再
经 wire 编解码。
"""
from __future__ import annotations

from typing import Any


def _handlers(runtime):
    return runtime.plugin_host.provided_port("compat.handlers")


def provider_models_create(runtime, request_id: str, body: dict) -> dict:
    record = _handlers(runtime).model_configs.create(request_id, body)
    return {"providerModel": record}


def provider_models_update(runtime, request_id: str, provider_model_id: str,
                           expected_version: int, body: dict) -> dict:
    record = _handlers(runtime).model_configs.update(
        provider_model_id, expected_version, request_id, body)
    return {"providerModel": record}


def provider_models_list(runtime, include_archived: bool = False) -> dict:
    items = _handlers(runtime).model_configs.list(include_archived=include_archived)
    return {"items": items, "nextCursor": None}


def profiles_create(runtime, request_id: str, *, display_name: str, harness: str,
                    credential_id=None) -> dict:
    row = _handlers(runtime).profiles.create_wire(
        request_id, display_name=display_name, harness=harness,
        credential_id=credential_id)
    return {"profile": _handlers(runtime)._profile(row)}


def profiles_update_config(runtime, request_id: str, *, profile_id: str,
                           expected_version: int, values: Any) -> dict:
    row = _handlers(runtime).profiles.update_configuration(
        request_id, profile_id=profile_id, expected_version=expected_version,
        values=values)
    return {
        "profile": _handlers(runtime)._profile(row),
        "configVersion": int(row["config_revision"]),
        "effectiveFor": "next_send",
    }


def profiles_update(runtime, request_id: str, *, profile_id: str,
                    expected_version: int, display_name: str) -> dict:
    row = _handlers(runtime).profiles.update_display_name(
        request_id, profile_id=profile_id, expected_version=expected_version,
        display_name=display_name)
    return {"profile": _handlers(runtime)._profile(row)}


def profiles_archive(runtime, request_id: str, *, profile_id: str,
                     expected_version: int) -> dict:
    row = _handlers(runtime).profiles.archive(
        request_id, profile_id=profile_id, expected_version=expected_version)
    return {"profile": _handlers(runtime)._profile(row)}


def profiles_clone(runtime, request_id: str, *, profile_id: str, display_name: str,
                   harness: str | None = None) -> dict:
    """按退役 wire handler 的编排逐句对译（plan_migration + clone_from + 资产重绑）。

    request_id 仅保留形参对称——clone 幂等键在 records.clone_from 内部生成。
    """
    h = _handlers(runtime)
    records = h.profiles.records
    source = records.get(profile_id)
    target_harness = harness or source["harness_type"]
    from ordessa_server_compat.composition import _registry_profile_spec
    from ordessa_server_compat.profiles.clone import plan_migration

    profile_spec = _registry_profile_spec(target_harness)
    if profile_spec is None:
        raise RuntimeError(f"the {target_harness!r} family is not registered")
    report = plan_migration(
        source=source, target_harness=target_harness,
        asset_bindings=h._asset_bindings_for(profile_id),
        hooks=h.hooks.list() if h.hooks is not None else [],
        registry_profile=profile_spec,
    )
    clone = records.clone_from(
        source_id=profile_id, name=display_name,
        harness_type=target_harness, report=report)
    rebound: list = []
    if h.asset_records is not None:
        migrated = [entry["item"] for entry in report["items"]
                    if entry["migrated"] and ":" in entry["item"]]
        rebound = h.asset_records.copy_bindings(
            source_profile_id=profile_id, target_profile_id=clone["id"],
            items=migrated)
    report["reboundAssets"] = rebound
    return {"profile": h._profile(clone), "migration": report}


def profiles_set_permissions(runtime, request_id: str, *, profile_id: str,
                             expected_version: int, preset: str, rules: list) -> dict:
    h = _handlers(runtime)
    updated = h.profiles.records.set_permissions(
        profile_id=profile_id, preset=preset, rules=rules,
        expected_version=expected_version, key=request_id,
        request_digest=request_id)
    return {"profile": h._profile(updated[1]["profile"])}


def profiles_grant_subagent(runtime, *, profile_id: str, child_profile_id: str) -> dict:
    grant = _handlers(runtime).profiles.records.grant_subagent(
        parent_id=profile_id, child_id=child_profile_id)
    return {"grant": grant}


def profiles_revoke_subagent(runtime, *, profile_id: str, child_profile_id: str) -> dict:
    _handlers(runtime).profiles.records.revoke_subagent(
        parent_id=profile_id, child_id=child_profile_id)
    return {"revoked": True}


def provider_models_probe_models(runtime, *, base_url: str, credential_id=None) -> dict:
    return _handlers(runtime).model_configs.probe_models(
        {"baseUrl": base_url, "credentialId": credential_id})
