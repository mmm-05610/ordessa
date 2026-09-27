"""Claude Code production deployment template for the managed sidecar chain.

Work Order 43. Joins the existing `claude` family package (whose composition
and provider modules belong to the pre-existing local CLI driver); this module
owns only the production deployment: which artifact directory carries the ACP
adapter and its dependency closure (including the Anthropic platform CLI
binary), how the product model id is spelled natively, which environment
variable carries the credential reference, and which confined guest paths hold
the native configuration and the native session transcripts.

Deliberately *data*, like every production template: the Server, Core, Worker
and bwrap layers only ever see the generic `runtimeArtifactMounts` /
`projectionFiles` / `stateProjection` / `adapter` fields this template
produces, and never a Claude branch.

The native configuration (`settings.json`) is checked in next to this module
under `deploy/claude/`: the official DeepSeek anthropic-compatible root (the
endpoint Claude Code speaks natively) and the user-confirmed product model.
Verified first-hand over a live ACP probe: `settings.json` `env` values reach
the session, and the model is used as-is for the wire request. The loopback
endpoint a no-model gate uses is produced by replacing
`env.ANTHROPIC_BASE_URL` alone.

Nothing here reads, stores, or emits credential content: the API key is an
environment *reference* (`ANTHROPIC_AUTH_TOKEN`) resolved inside the sandbox,
where the Worker materialized it - never a settings file entry.

License boundary: the ACP adapter
(`@agentclientprotocol/claude-agent-acp`) is Apache-2.0; the embedded
`@anthropic-ai/claude-agent-sdk` and its platform CLI binary are Anthropic
proprietary ("All rights reserved", use under Anthropic's Commercial Terms).
This deployment installs and runs them unmodified; it does not modify the
binary and does not redistribute either.
"""
from __future__ import annotations

import argparse
import re
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..registry.capability_claims import capability_claims as _derive_capability_claims

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

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_DIRECTORY = PLUGIN_ROOT / "deploy" / "claude"
SETTINGS_TEMPLATE = DEPLOY_DIRECTORY / "settings.json"
#: The settings path whose value the deployment writes; the settings document
#: is Claude Code's own `env`-map + model schema.
SETTINGS_BASE_URL_PATH = ("env", "ANTHROPIC_BASE_URL")

SETTINGS_SOURCE = "deploy/claude/settings.json"
#: Reviewed offline asset for gates that must not reach a real endpoint. It is
#: compiled by the gate and preloaded via LD_PRELOAD so the enforcement covers
#: the native CLI binary (a NODE_OPTIONS hook would only cover the adapter).
LOOPBACK_GUARD_SOURCE = "deploy/claude/egress-guard.c"
#: Guest path the gate-compiled guard shared library is projected to (inside
#: the confined config home, outside the writable state subtree).
EGRESS_GUARD_TARGET = "/runtime/home/.claude/claude-egress-guard.so"


class ClaudeProductionTemplateError(ValueError):
    """A deployment declaration this template refuses to emit."""


def capability_claims() -> dict[str, bool]:
    """本模板部署时声明的 canonical 能力（派生自注册表，不手写）。"""
    return _derive_capability_claims("claude-code")


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


ARTIFACT_TOKEN = re.compile(r"[a-z][a-z0-9-]{0,31}")


def harness_deployment(
    *,
    artifact_token: str,
    tree_digest: str,
    timeout_ms: int = 120_000,
    adapter_environment: Mapping[str, str] | None = None,
    projection_files_override: Sequence[Mapping[str, str]] | None = None,
    runtime_artifact_mounts_override: Sequence[Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """One production Harness entry, ready for a non-secret deployment file."""
    if not isinstance(artifact_token, str) or not ARTIFACT_TOKEN.fullmatch(artifact_token):
        raise ClaudeProductionTemplateError("CLAUDE_ARTIFACT_TOKEN_INVALID")
    if not isinstance(tree_digest, str) or not tree_digest.startswith("sha256:") or len(tree_digest) != 71:
        raise ClaudeProductionTemplateError("CLAUDE_ARTIFACT_DIGEST_INVALID")
    if adapter_environment is not None and any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in adapter_environment.items()
    ):
        raise ClaudeProductionTemplateError("CLAUDE_ADAPTER_ENVIRONMENT_INVALID")
    mounts = runtime_artifact_mounts_override or ({
        "token": artifact_token, "target": ARTIFACT_TARGET, "treeDigest": tree_digest,
    },)
    return {
        "id": "claude-code",
        "timeoutMs": timeout_ms,
        # 能力声明**派生**自注册表（`harnesses.toml`），不由本模板手写。
        "capabilityClaims": capability_claims(),
        "credentialKind": CREDENTIAL_KIND,
        "credentialEnvironment": CREDENTIAL_ENVIRONMENT,
        "modelControlId": MODEL_CONTROL_ID,
        "controlOptions": {MODEL_CONTROL_ID: []},
        # Order 092: canonical protocols this family can speak -> native dialect value.
        "wireProtocols": {"anthropic-messages": "anthropic"},
        "runtimeArtifactMounts": [dict(item) for item in mounts],
        "projectionFiles": [dict(item) for item in (
            projection_files_override
            if projection_files_override is not None else projection_files()
        )],
        "stateProjection": {"target": STATE_TARGET},
        # Order 67's narrowed lock: this family writes shared files outside the
        # session store (`.claude.json`, todos/, shell-snapshots/) whose
        # concurrent-writer safety is not established first-hand, so admission
        # holds one active execution per Profile for it.
        "homeConcurrency": "exclusive",
        "usageProbe": {"journalSuffix": ".jsonl", "format": "claude-projects-line"},
        "adapter": {
            "command": "/usr/bin/node",
            "args": [ADAPTER_ARTIFACT_ENTRY],
            # The environment reaches the adapter process only, and the
            # credential is injected there as the declared environment
            # variable; no secret is written into any file or argument.
            "environment": dict(ADAPTER_ENVIRONMENT if adapter_environment is None else adapter_environment),
        },
    }


def deployment_document(
    *, artifact_token: str, tree_digest: str, **harness: Any,
) -> dict[str, Any]:
    """The whole non-secret deployment file the Server loads."""
    return {
        "schemaVersion": 1,
        "harnesses": [harness_deployment(
            artifact_token=artifact_token, tree_digest=tree_digest, **harness,
        )],
    }


def main(arguments: Sequence[str] | None = None) -> int:
    """Emit the production deployment file for one built artifact."""
    parser = argparse.ArgumentParser(description="Emit the claude-code production deployment file.")
    parser.add_argument("--artifact-token", required=True,
                        help="mount token the deployment binds to the built claude runtime artifact")
    parser.add_argument("--tree-digest", required=True,
                        help="the artifact manifest's sha256: tree digest")
    parser.add_argument("--out", required=True, help="path of the deployment file to write")
    parser.add_argument("--timeout-ms", type=int, default=120_000)
    options = parser.parse_args(arguments)
    document = deployment_document(
        artifact_token=options.artifact_token, tree_digest=options.tree_digest,
        timeout_ms=options.timeout_ms,
    )
    output = Path(options.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "CLAUDE_PRODUCTION_DEPLOYMENT_EMITTED",
        "out": str(output), "artifactTarget": ARTIFACT_TARGET,
        "productModelId": PRODUCT_MODEL_ID, "nativeModelValue": NATIVE_MODEL_VALUE,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI parity with the module
    raise SystemExit(main())
