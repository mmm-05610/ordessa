"""The optional ``harness.providers`` section of the service configuration.

The rules are the CLI's own harness-configuration rules, so the same provider
configuration means the same thing on both entry points, and the Server never
admits a literal credential.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ordessa_server_product.service_configuration import (
    ServiceConfigurationError,
    configuration_from_document,
    default_service_configuration,
)

_DOCUMENT = {
    "version": 1,
    "server": {"serverId": "ordessa-test"},
    "access": {
        "tokenFile": "/tmp/ordessa-test/secrets/http-token",
        "principalId": "instance",
        "realm": "ordessa",
        "project": "local",
        "grants": ["agents.start", "agents.prompt"],
    },
    "profiles": {"namespace": "server"},
    "harness": {"allowlist": ["kilo", "codex"]},
    "capabilities": ["agents", "environments", "decisions"],
}


def _document(**harness):
    document = copy.deepcopy(_DOCUMENT)
    document["harness"].update(harness)
    return document


def _load(document):
    return configuration_from_document(document, harness_default=())


def _refused(document):
    with pytest.raises(ServiceConfigurationError) as failure:
        _load(document)
    return failure.value.reason


def test_zero_configuration_admits_no_provider_configuration():
    configuration = default_service_configuration(
        Path("/tmp/ordessa-zero"), harness_allowlist=("kilo",))
    assert dict(configuration.harness_providers) == {}


def test_the_providers_section_is_optional():
    configuration = _load(_document())
    assert dict(configuration.harness_providers) == {}


def test_a_provider_keeps_its_command_environment_and_references():
    configuration = _load(_document(providers={
        "kilo": {
            "command": ["/opt/kilo/bin/kilo"],
            "env": {"KILO_CONFIG_CONTENT": '{"autoupdate":false}'},
            "envFrom": {"KILO_PROVIDER_KEY": "OPEN_CODE_GO_API_KEY"},
        },
    }))
    entry = configuration.harness_providers["kilo"]
    assert entry["command"] == ["/opt/kilo/bin/kilo"]
    assert entry["env"] == {"KILO_CONFIG_CONTENT": '{"autoupdate":false}'}
    assert entry["envFrom"] == {"KILO_PROVIDER_KEY": "OPEN_CODE_GO_API_KEY"}


@pytest.mark.parametrize("command", [
    "codex",
    [],
    ["codex", ""],
    ["codex", 7],
    ["/opt/" + "x" * 5000],
])
def test_a_command_must_be_a_bounded_string_list(command):
    assert "argv list" in _refused(_document(providers={"codex": {"command": command}}))


def test_an_environment_value_must_be_a_string():
    reason = _refused(_document(providers={"codex": {"env": {"A": 1}}}))
    assert "string values" in reason


@pytest.mark.parametrize("name", [
    "DEEPSEEK_API_KEY",
    "MY_TOKEN",
    "MY_SECRET",
    "MY_PASSWORD",
    "MY_APIKEY",
    "MY_CREDENTIAL",
])
def test_a_credential_shaped_environment_name_is_refused(name):
    reason = _refused(_document(providers={"codex": {"env": {name: "value"}}}))
    assert "credential" in reason


@pytest.mark.parametrize("value", [
    "sk-abcdefghijklmnopqrstuvwxyz012345",
    "ghp_abcdefghijklmnopqrstuvwxyz012345",
    "xoxb-abcdefghijklmnopqrstuvwxyz012345",
    "AKIAIOSFODNN7EXAMPLE",
    "a" * 40,
])
def test_a_literal_credential_is_refused_in_an_environment_value(value):
    reason = _refused(_document(providers={"codex": {"env": {"MODEL_HOST": value}}}))
    assert "credential" in reason


def test_the_same_variable_may_not_be_bound_twice():
    reason = _refused(_document(providers={"codex": {
        "env": {"MODEL_HOST": "value"}, "envFrom": {"MODEL_HOST": "OTHER_NAME"}}}))
    assert "same variable" in reason


@pytest.mark.parametrize("reference", [
    "not-a-name",
    "has space",
    "",
    "a" * 100,
])
def test_an_environment_reference_must_name_an_environment_variable(reference):
    reason = _refused(_document(providers={"codex": {
        "envFrom": {"MODEL_HOST": reference}}}))
    assert "environment variables" in reason


def test_an_environment_reference_may_not_carry_a_literal():
    reason = _refused(_document(providers={"codex": {
        "envFrom": {"MODEL_HOST": "sk-abcdefghijklmnopqrstuvwxyz012345"}}}))
    assert reason


def test_an_unknown_provider_key_is_refused():
    reason = _refused(_document(providers={"codex": {"model": "gpt"}}))
    assert "command/env/envFrom" in reason


def test_the_providers_section_must_be_an_object():
    assert "JSON object" in _refused(_document(providers=[]))


def test_the_harness_section_admits_only_the_allowlist_and_the_providers():
    assert "optional providers" in _refused(_document(model="gpt"))


class _Endpoints:
    """The endpoint service is not exercised: only the wiring is."""


class _Services:
    endpoints = _Endpoints()


class _EnvironmentOwner:
    services = _Services()


def test_the_configured_providers_reach_the_preparation_port():
    from ordessa_server_product.service_composition import build_agent_ports

    providers = {
        "kilo": {
            "command": None,
            "env": {"KILO_CONFIG_CONTENT": '{"autoupdate":false}'},
            "envFrom": {"KILO_PROVIDER_KEY": "OPEN_CODE_GO_API_KEY"},
        },
    }
    _resolver, preparation = build_agent_ports(
        _EnvironmentOwner(), catalog=object(), profile_service=object(),
        lifecycle_authority=object(), roots={}, providers=providers)
    inner = preparation._inner
    assert inner._harness_config["kilo"]["env"] == {"KILO_CONFIG_CONTENT": '{"autoupdate":false}'}
    assert inner._harness_config["kilo"]["envFrom"] == {"KILO_PROVIDER_KEY": "OPEN_CODE_GO_API_KEY"}


def test_no_configured_providers_leave_the_preparation_port_empty():
    from ordessa_server_product.service_composition import build_agent_ports

    _resolver, preparation = build_agent_ports(
        _EnvironmentOwner(), catalog=object(), profile_service=object(),
        lifecycle_authority=object(), roots={})
    assert preparation._inner._harness_config == {}
