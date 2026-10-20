"""Captured Claude ACP artifact/configuration facts; no deployment assembler.

These preserved source pins and pure settings helpers do not register an ACP
provider, claim current runtime readiness or emit the retired sidecar deployment.
The current SDK provider preserves Claude's native claude-stream-json/1 protocol
and refuses its unavailable original bootstrap explicitly.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


CLAUDE_PROVIDER = "deepseek"
#: The product/ProviderModel model id the user confirmed. Claude Code accepts
#: arbitrary model ids for custom gateways ("Custom model" row observed in the
#: adapter's own `model` config option), and DeepSeek's anthropic-compatible
#: endpoint resolves this id natively.
PRODUCT_MODEL_ID = "deepseek-flash"
#: The native value equals the product id: the model passes through untouched
#: (identity mapping, verified in the probe - the wire request carried
#: `deepseek-flash` exactly).
NATIVE_MODEL_VALUE = PRODUCT_MODEL_ID
OFFICIAL_BASE_URL = "https://api.deepseek.com/anthropic"
CREDENTIAL_KIND = "api-key"
CREDENTIAL_ENVIRONMENT = "ANTHROPIC_AUTH_TOKEN"

#: Stable artifact name and the confined guest path it is projected to. The
#: adapter entry is derived from it, so the two can never disagree.
ARTIFACT_NAME = "claude-runtime"
ARTIFACT_TARGET = f"/runtime/artifacts/{ARTIFACT_NAME}"
ADAPTER_ARTIFACT_RELATIVE_ENTRY = "node_modules/@agentclientprotocol/claude-agent-acp/dist/index.js"
ADAPTER_ARTIFACT_ENTRY = f"{ARTIFACT_TARGET}/{ADAPTER_ARTIFACT_RELATIVE_ENTRY}"
#: Declared by the pinned builder output; the deployment only records it.
ADAPTER_PACKAGE = "@agentclientprotocol/claude-agent-acp"
ADAPTER_VERSION = "0.81.2"

#: Confined config home and the native transcript subtree inside it. Claude
#: Code's own default is `$HOME/.claude`; the guest `HOME` is the one isolated
#: root (`/runtime/home`), and `CLAUDE_CONFIG_DIR` names the same directory,
#: so an explicit variable and the default path can never disagree.
CONFIG_HOME = "/runtime/home/.claude"
STATE_TARGET = f"{CONFIG_HOME}/projects"

#: Production adapter environment. `CLAUDE_CONFIG_DIR` pins the config home to
#: the isolated projection for configuration and session state. No offline or
#: telemetry switches are invented: startup network behavior is a gate
#: observation (the LD_PRELOAD loopback guard reaches the native binary, which
#: a NODE_OPTIONS hook could not), not a template claim.
ADAPTER_ENVIRONMENT = {
    "CLAUDE_CONFIG_DIR": CONFIG_HOME,
}

#: The product control that selects the model.
MODEL_CONTROL_ID = "model"

DEPLOY_DIRECTORY = Path(__file__).resolve().parent / "deployment"
SETTINGS_TEMPLATE = DEPLOY_DIRECTORY / "settings.json"
#: The settings path whose value the deployment writes; the settings document
#: is Claude Code's own `env`-map + model schema.
SETTINGS_BASE_URL_PATH = ("env", "ANTHROPIC_BASE_URL")

SETTINGS_SOURCE = "deploy/claude/settings.json"
#: Reviewed offline asset for gates that must not reach a real endpoint. It is
#: compiled by the gate and preloaded via LD_PRELOAD so the enforcement covers
#: the native CLI binary (a NODE_OPTIONS hook would only cover the adapter).
EGRESS_GUARD = DEPLOY_DIRECTORY / "egress-guard.c"
#: Guest path the gate-compiled guard shared library is projected to (inside
#: the confined config home, outside the writable state subtree).
EGRESS_GUARD_TARGET = "/runtime/home/.claude/claude-egress-guard.so"


class ClaudeProductionTemplateError(ValueError):
    """A deployment declaration this template refuses to emit."""


def settings_document() -> dict[str, Any]:
    """The checked-in native settings document (official root)."""
    return json.loads(SETTINGS_TEMPLATE.read_text(encoding="utf-8"))


def loopback_settings_document(base_url: str) -> dict[str, Any]:
    """A copy of the settings document with only `env.ANTHROPIC_BASE_URL`
    replaced.

    A no-model gate needs Claude Code to talk to a local fake endpoint.
    Everything else - the model - stays the template's, and the production
    template itself is never rewritten.
    """
    if not isinstance(base_url, str) or not base_url.startswith("http://127.0.0.1:"):
        raise ClaudeProductionTemplateError("CLAUDE_LOOPBACK_BASE_URL_INVALID")
    document = settings_document()
    section = document
    for key in SETTINGS_BASE_URL_PATH[:-1]:
        section = section[key]
    section[SETTINGS_BASE_URL_PATH[-1]] = base_url
    return document


def _base_url_of(document: Mapping[str, Any]) -> Any:
    section = document
    for key in SETTINGS_BASE_URL_PATH[:-1]:
        section = section[key]
    return section[SETTINGS_BASE_URL_PATH[-1]]


def documented_differences(base_url: str) -> dict[str, tuple[Any, Any]]:
    """Exactly which fields a loopback override changes, for auditing it."""
    production = settings_document()
    override = loopback_settings_document(base_url)
    key = ".".join(SETTINGS_BASE_URL_PATH)
    return {key: (_base_url_of(production), _base_url_of(override))}


def model_aliases() -> dict[str, str]:
    """Product model id -> native catalogue value (identity for claude-code)."""
    return {PRODUCT_MODEL_ID: NATIVE_MODEL_VALUE}


def native_model(model: object) -> object:
    """Translate one product model id; anything else is passed through untouched."""
    if not isinstance(model, str):
        return model
    return model_aliases().get(model, model)


def projection_files() -> tuple[dict[str, str], ...]:
    """The native configuration, read-only, inside the confined config home."""
    return (
        {"source": SETTINGS_SOURCE, "target": f"{CONFIG_HOME}/settings.json"},
    )
