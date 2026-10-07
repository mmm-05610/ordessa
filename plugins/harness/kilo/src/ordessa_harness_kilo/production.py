"""Kilo production deployment template for the managed sidecar chain (non-secret).

Work Order 43 follow-up. Kilo CLI (`@kilocode/cli`) is an OpenCode fork with a
first-party ACP stdio server (`kilo acp`), so this template composes the pinned
artifact's native binary directly - no node launcher in between. This module
owns the kilo-specific deployment facts: the artifact directory carrying the
launcher and platform binary, the native configuration document (delivered as
the `KILO_CONFIG_CONTENT` environment value, the probe-verified path), the
credential environment reference, and the confined guest paths.

Deliberately *data*: the Server, Core, Worker and bwrap layers only ever see
the generic `runtimeArtifactMounts` / `stateProjection` / `adapter` fields this
template produces, and never a Kilo branch.

The native configuration (`kilo.json`) is checked in next to this module under
`deploy/kilo/`: one OpenAI-compatible provider aimed at the official DeepSeek
root, the user-confirmed product model, the credential as an environment
*reference* (`{env:OPENAI_API_KEY}` - resolved by kilo inside the sandbox,
never a literal), and auto-update off. The loopback endpoint a no-model gate
uses is produced by replacing `provider.*.options.baseURL` alone.

No configuration file is projected: the probe-verified delivery channel for
the configuration document is `KILO_CONFIG_CONTENT` (environment), which also
keeps kilo's own first-boot normalization from fighting a read-only mount.
The guest `HOME` is the one isolated root, so kilo's XDG defaults
(`~/.config/kilo`, `~/.local/share/kilo`) resolve inside it without any extra
variable; the writable state projection covers the data subtree only.
"""
from __future__ import annotations

import argparse
import re
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

# H-KILO-001 (approvals/H-KILO-001-release.md): the family package imports the
# brand-neutral core directly (direction: family -> core, the target shape).
from ordessa_server_product.harness_adapters.registry.capability_claims import capability_claims as _derive_capability_claims

KILO_PROVIDER = "deepseek"
#: The product/ProviderModel model id the user confirmed. It is also an entry
#: in kilo's own model catalog (models.dev deepseek entry, verified in research).
PRODUCT_MODEL_ID = "deepseek-flash"
#: The native config option value: kilo addresses models as `provider/model`.
NATIVE_MODEL_VALUE = f"{KILO_PROVIDER}/{PRODUCT_MODEL_ID}"
OFFICIAL_BASE_URL = "https://api.deepseek.com"
CREDENTIAL_KIND = "api-key"
CREDENTIAL_ENVIRONMENT = "OPENAI_API_KEY"

#: Stable artifact name and the confined guest path it is projected to. The
#: adapter entry is derived from it, so the two can never disagree.
ARTIFACT_NAME = "kilo-runtime"
ARTIFACT_TARGET = f"/runtime/artifacts/{ARTIFACT_NAME}"
#: The pinned platform binary is the adapter process itself (verified: the
#: binary alone answers ACP stdio; the node launcher only adds resolution).
ADAPTER_ARTIFACT_RELATIVE_ENTRY = "node_modules/@kilocode/cli-linux-x64-baseline/bin/kilo"
ADAPTER_ARTIFACT_ENTRY = f"{ARTIFACT_TARGET}/{ADAPTER_ARTIFACT_RELATIVE_ENTRY}"
#: Declared by the pinned builder output; the deployment only records it.
ADAPTER_PACKAGE = "@kilocode/cli"
ADAPTER_VERSION = "7.7.2"

#: The configuration document path inside it, for auditing the override.
CONFIG_BASE_URL_PATH = ("provider", "deepseek", "options", "baseURL")

#: Writable native state: kilo's XDG data subtree under the isolated guest HOME
#: (sessions database, auth cache, logs). Config and cache stay outside it.
STATE_TARGET = "/runtime/home/.local/share/kilo"

#: The product control that selects the model.
MODEL_CONTROL_ID = "model"

# H-KILO-001: one directory level less than the legacy in-tree path
# (`.../pacthold.plugins/harness/kilo/src/ordessa_harness_kiloproduction.py` -> parents[3]; here -> parents[2]),
# so DEPLOY_DIRECTORY keeps pointing at this package's checked-in `deploy/kilo/`
# with byte-identical assets (hash verified in the checkpoint).
PLUGIN_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_DIRECTORY = PLUGIN_ROOT / "deploy" / "kilo"
CONFIG_TEMPLATE = DEPLOY_DIRECTORY / "kilo.json"
#: Reviewed offline asset for gates that must not reach a real endpoint. It is
#: compiled by the gate and preloaded via LD_PRELOAD so the enforcement covers
#: the native binary (a NODE_OPTIONS hook would only cover node processes).
LOOPBACK_GUARD_SOURCE = "deploy/kilo/egress-guard.c"
EGRESS_GUARD_TARGET = "/runtime/home/.kilo-gate/egress-guard.so"




class KiloProductionTemplateError(ValueError):
    """A deployment declaration this template refuses to emit."""


def capability_claims() -> dict[str, bool]:
    """本模板部署时声明的 canonical 能力（派生自注册表，不手写）。"""
    return _derive_capability_claims("kilo")


def config_document() -> dict[str, Any]:
    """The checked-in native configuration document (official root)."""
    return json.loads(CONFIG_TEMPLATE.read_text(encoding="utf-8"))


def _base_url_of(document: Mapping[str, Any]) -> Any:
    section: Any = document
    for key in CONFIG_BASE_URL_PATH:
        section = section[key]
    return section


def loopback_config_document(base_url: str) -> dict[str, Any]:
    """A copy of the configuration with only `options.baseURL` replaced."""
    if not isinstance(base_url, str) or not base_url.startswith("http://127.0.0.1:"):
        raise KiloProductionTemplateError("KILO_LOOPBACK_BASE_URL_INVALID")
    document = config_document()
    section = document
    for key in CONFIG_BASE_URL_PATH[:-1]:
        section = section[key]
    section[CONFIG_BASE_URL_PATH[-1]] = base_url
    return document


def render_config_document(document: Mapping[str, Any]) -> str:
    """Deterministic compact JSON string for the `KILO_CONFIG_CONTENT` value."""
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


def documented_differences(base_url: str) -> dict[str, tuple[Any, Any]]:
    """Exactly which config fields a loopback override changes, for auditing."""
    key = ".".join(CONFIG_BASE_URL_PATH)
    return {key: (_base_url_of(config_document()), base_url)}


def adapter_environment(base_url: str | None = None) -> dict[str, str]:
    """The production adapter environment; `base_url` swaps the loopback in.

    Without `base_url` this is the production template: the checked-in
    configuration document, delivered through `KILO_CONFIG_CONTENT`.
    """
    document = config_document() if base_url is None else loopback_config_document(base_url)
    return {"KILO_CONFIG_CONTENT": render_config_document(document)}


def model_aliases() -> dict[str, str]:
    """Product model id -> native config option value, owned by this layer."""
    return {PRODUCT_MODEL_ID: NATIVE_MODEL_VALUE}


def native_model(model: object) -> object:
    """Translate one product model id; anything else is passed through untouched."""
    if not isinstance(model, str):
        return model
    return model_aliases().get(model, model)


def projection_files() -> tuple[dict[str, str], ...]:
    """No configuration file is projected: the config rides in the environment."""
    return ()


#: Captured before `harness_deployment` shadows the name with its keyword
#: argument of the same shape.
_build_adapter_environment = adapter_environment


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
        raise KiloProductionTemplateError("KILO_ARTIFACT_TOKEN_INVALID")
    if not isinstance(tree_digest, str) or not tree_digest.startswith("sha256:") or len(tree_digest) != 71:
        raise KiloProductionTemplateError("KILO_ARTIFACT_DIGEST_INVALID")
    if adapter_environment is not None and any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in adapter_environment.items()
    ):
        raise KiloProductionTemplateError("KILO_ADAPTER_ENVIRONMENT_INVALID")
    mounts = runtime_artifact_mounts_override or ({
        "token": artifact_token, "target": ARTIFACT_TARGET, "treeDigest": tree_digest,
    },)
    return {
        "id": "kilo",
        "timeoutMs": timeout_ms,
        # 能力声明**派生**自注册表（`harnesses.toml`），不由本模板手写。
        "capabilityClaims": capability_claims(),
        "credentialKind": CREDENTIAL_KIND,
        "credentialEnvironment": CREDENTIAL_ENVIRONMENT,
        "modelControlId": MODEL_CONTROL_ID,
        "controlOptions": {MODEL_CONTROL_ID: []},
        # Order 092: canonical protocols this family can speak -> native dialect value.
        "wireProtocols": {"openai-chat": "@ai-sdk/openai-compatible"},
        "runtimeArtifactMounts": [dict(item) for item in mounts],
        "projectionFiles": [dict(item) for item in (
            projection_files_override
            if projection_files_override is not None else projection_files()
        )],
        "stateProjection": {"target": STATE_TARGET},
        # Order 66: the family library owns the live session database and the
        # revert/diff lands; log/, repos/ and telemetry-id stay in the profile
        # home. The db needs its WAL sidecars shared with it or a second
        # writer would not see committed rows.
        "sessionStore": {
            "kind": "whole-db",
            "shared": [
                       {"name": "kilo.db", "kind": "file"},
                       {"name": "kilo.db-wal", "kind": "file"},
                       {"name": "kilo.db-shm", "kind": "file"},
                       {"name": "storage/session_diff", "kind": "directory"},
                       {"name": "kilo", "kind": "directory"},
                   ],
        },
        "adapter": {
            # The platform binary is the ACP server: no node launcher needed.
            "command": ADAPTER_ARTIFACT_ENTRY,
            "args": ["acp"],
            # The environment reaches the adapter process only, and the
            # credential is injected there as the declared environment
            # variable; no secret is written into any file or argument.
            "environment": dict(
                _build_adapter_environment()
                if adapter_environment is None else adapter_environment),
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
    parser = argparse.ArgumentParser(description="Emit the kilo production deployment file.")
    parser.add_argument("--artifact-token", required=True,
                        help="mount token the deployment binds to the built kilo runtime artifact")
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
        "result": "KILO_PRODUCTION_DEPLOYMENT_EMITTED",
        "out": str(output), "artifactTarget": ARTIFACT_TARGET,
        "productModelId": PRODUCT_MODEL_ID, "nativeModelValue": NATIVE_MODEL_VALUE,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI parity with the module
    raise SystemExit(main())
