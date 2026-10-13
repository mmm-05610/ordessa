"""qwen production deployment template for the managed sidecar chain (non-secret).

Work Order 43's faithful clone of the dsh production template, for the Qwen
Code CLI started in its official ACP mode (`qwen --acp`). This module owns the
qwen-specific parts of a production deployment: the artifact directory carrying
the bundled CLI, the OpenAI-compatible endpoint and model the product selected,
the credential environment reference, and the confined guest paths for native
configuration and session state.

Verified first-hand over a live ACP probe: the OpenAI env trio
(`OPENAI_BASE_URL` / `OPENAI_API_KEY` / `OPENAI_MODEL`) drives the endpoint and
the wire model id end to end, and the adapter's `model` config option advertises
the runtime value `$runtime|openai|deepseek-flash(openai)` for that model. The
alias table translates the product id to exactly that advertised value.

There is no native configuration projection: qwen normalizes its settings
document at first boot (a read-only projection fails with EBUSY), and every
connection fact this deployment needs travels through the environment
(probe-verified). Nothing here reads, stores, or emits credential content: the
API key is an environment *reference* resolved inside the sandbox.

The guest layout is the common one: `/runtime/home` is the one isolated home
root; `QWEN_HOME=/runtime/home/.qwen` names the same directory dsh-style
double convergence (`$HOME/.qwen` resolves identically), the read-only
settings projection and the writable session store both live inside it.
"""
from __future__ import annotations

import argparse
import re
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

# P-QWEN-001 (approvals/P-QWEN-001-release.md): the family package imports the
# brand-neutral core directly (direction: family -> core, the target shape).
from ordessa_execution_agents.harness.definitions.harness_capabilities import CANONICAL_CAPABILITY_IDS

QWEN_PROVIDER = "openai"
#: The product/ProviderModel model id the user confirmed. It must never change
#: silently: the native catalogue value below is derived from it.
PRODUCT_MODEL_ID = "deepseek-flash"
#: The value dsh's ACP model config option advertises for that product model.
#: The option's values are opaque strings, and dsh's shipped picker spells this
#: entry as a JSON-array string over the `deepseek-official` route (observed
#: first-hand over `session/new`; displayed to users as "DeepSeek-V41-Flash").
#: The value qwen's ACP `model` config option advertises for the product
#: model when `OPENAI_MODEL=deepseek-flash` is set: the runtime composes
#: the selectable value from auth type + model id (observed first-hand).
NATIVE_MODEL_VALUE = "$runtime|openai|deepseek-flash(openai)"
OFFICIAL_BASE_URL = "https://api.deepseek.com"
CREDENTIAL_KIND = "api-key"
CREDENTIAL_ENVIRONMENT = "OPENAI_API_KEY"
#: Stable artifact name and the confined guest path it is projected to. The
#: adapter entry is derived from it, so the two can never disagree.
ARTIFACT_NAME = "qwen-runtime"
ARTIFACT_TARGET = f"/runtime/artifacts/{ARTIFACT_NAME}"
ADAPTER_ARTIFACT_RELATIVE_ENTRY = "node_modules/@qwen-code/qwen-code/cli-entry.js"
ADAPTER_ARTIFACT_ENTRY = f"{ARTIFACT_TARGET}/{ADAPTER_ARTIFACT_RELATIVE_ENTRY}"
#: Declared by the pinned builder output; the deployment only records it.
ADAPTER_PACKAGE = "@qwen-code/qwen-code"
ADAPTER_VERSION = "0.23.4"

#: Confined harness home and the native session store subtree inside it. The
#: home is a projection inside the one isolated guest home root
#: (`/runtime/home`), never the host home: `DSH_HOME` below names the same
#: directory, and dsh's own default (`$HOME/.dsh`) resolves to it too, so an
#: explicit variable and the default path can never disagree.
HARNESS_HOME = "/runtime/home/.qwen"
#: qwen stores session chats under `projects/<project>/chats/`, so the
#: writable projection is the projects subtree.
STATE_TARGET = f"{HARNESS_HOME}/projects"

#: Production adapter environment. `QWEN_HOME` pins the harness home to the
#: isolated projection; the OpenAI trio is the probe-verified path to the
#: endpoint and the wire model id (process env outranks the settings document).
#: No offline or telemetry switches are invented: startup network behavior is
#: a gate observation (the loopback guard), not a template claim.
ADAPTER_ENVIRONMENT = {
    "QWEN_HOME": HARNESS_HOME,
    "OPENAI_BASE_URL": OFFICIAL_BASE_URL,
    "OPENAI_MODEL": PRODUCT_MODEL_ID,
}

#: The product control that selects the model. The Server only knows this id
#: from the declaration; nothing about dsh is hardcoded in it. No default value
#: is advertised, because a model selection is a Provider/Model reference the
#: product resolves, not one of a fixed set of native strings - and a silently
#: discovered default would run a model the user never chose.
MODEL_CONTROL_ID = "model"

# This offline guard is an owner resource adjacent to this module and included
# by the leaf's explicit package-data declaration.
DEPLOY_DIRECTORY = Path(__file__).resolve().parent / "deployment"
#: Reviewed offline asset for gates that must not reach a real endpoint. It is
#: never referenced by a production deployment.
LOOPBACK_GUARD = DEPLOY_DIRECTORY / "loopback-guard.cjs"
LOOPBACK_GUARD_TARGET = f"{HARNESS_HOME}/qwen-loopback-guard.cjs"


class QwenProductionTemplateError(ValueError):
    """A deployment declaration this template refuses to emit."""


def capability_claims(*, capabilities_for) -> dict[str, bool]:
    """本模板部署时声明的 canonical 能力（派生自注册表，不手写）。

    全部语义级能力（attach/permissions/native_continuation 的观测结论）由链门的
    证据表决定，本模板无权改写；此处返回的只是注册表里的静态声明上限。
    """
    if not callable(capabilities_for):
        raise QwenProductionTemplateError("QWEN_CAPABILITY_SOURCE_REQUIRED")
    claims = capabilities_for("dsh")
    if (not isinstance(claims, Mapping) or set(claims) != set(CANONICAL_CAPABILITY_IDS)
            or any(type(claims[key]) is not bool for key in CANONICAL_CAPABILITY_IDS)):
        raise QwenProductionTemplateError("QWEN_CAPABILITY_CLAIMS_INVALID")
    return {key: claims[key] for key in CANONICAL_CAPABILITY_IDS}


def loopback_environment(base_url: str) -> dict[str, str]:
    """The adapter environment with only `OPENAI_BASE_URL` replaced.

    A no-model gate needs qwen to talk to a local fake endpoint. Everything
    else - the model id, the harness home - stays the template's, and the
    production template itself is never rewritten. The endpoint travels in the
    environment because that is the documented, probe-verified path (process
    env outranks the settings document), so the override lives here too.
    """
    if not isinstance(base_url, str) or not base_url.startswith("http://127.0.0.1:"):
        raise QwenProductionTemplateError("QWEN_LOOPBACK_BASE_URL_INVALID")
    environment = dict(ADAPTER_ENVIRONMENT)
    environment["OPENAI_BASE_URL"] = base_url
    return environment


def documented_differences(base_url: str) -> dict[str, tuple[Any, Any]]:
    """Exactly which adapter-environment fields a loopback override changes."""
    return {
        "OPENAI_BASE_URL": (ADAPTER_ENVIRONMENT["OPENAI_BASE_URL"], base_url),
    }


def model_aliases() -> dict[str, str]:
    """Product model id -> native catalogue value, owned by the Harness layer."""
    return {PRODUCT_MODEL_ID: NATIVE_MODEL_VALUE}


def native_model(model: object) -> object:
    """Translate one product model id; anything else is passed through untouched."""
    if not isinstance(model, str):
        return model
    return model_aliases().get(model, model)


def projection_files() -> tuple[dict[str, str], ...]:
    """No native configuration is projected, deliberately.

    First-hand gate finding: qwen normalizes its settings document at first
    boot (backup + rename), so a read-only projection of it fails the harness
    with EBUSY. Every connection fact this deployment needs travels in the
    environment (probe-verified), and the settings document qwen owns inside
    the isolated home is native state - which the state projection deliberately
    does not cover (it is outside `projects/`).
    """
    return ()


ARTIFACT_TOKEN = re.compile(r"[a-z][a-z0-9-]{0,31}")


def harness_deployment(
    *, capabilities_for,
    artifact_token: str,
    tree_digest: str,
    timeout_ms: int = 120_000,
    adapter_environment: Mapping[str, str] | None = None,
    projection_files_override: Sequence[Mapping[str, str]] | None = None,
    runtime_artifact_mounts_override: Sequence[Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """One production Harness entry, ready for a non-secret deployment file."""
    if not isinstance(artifact_token, str) or not ARTIFACT_TOKEN.fullmatch(artifact_token):
        raise QwenProductionTemplateError("QWEN_ARTIFACT_TOKEN_INVALID")
    if not isinstance(tree_digest, str) or not tree_digest.startswith("sha256:") or len(tree_digest) != 71:
        raise QwenProductionTemplateError("QWEN_ARTIFACT_DIGEST_INVALID")
    if adapter_environment is not None and any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in adapter_environment.items()
    ):
        raise QwenProductionTemplateError("QWEN_ADAPTER_ENVIRONMENT_INVALID")
    mounts = runtime_artifact_mounts_override or ({
        "token": artifact_token, "target": ARTIFACT_TARGET, "treeDigest": tree_digest,
    },)
    return {
        "id": "qwen",
        "timeoutMs": timeout_ms,
        # 能力声明**派生**自注册表（`harnesses.toml`），不由本模板手写：see
        # `registry.capability_claims`。它是静态声明上限，测试逐项断言 true 项 == TOML，
        # 因此"生产部署声明的能力"与"注册表声明的能力"不可能漂移。
        "capabilityClaims": capability_claims(capabilities_for=capabilities_for),
        "credentialKind": CREDENTIAL_KIND,
        "credentialEnvironment": CREDENTIAL_ENVIRONMENT,
        "modelControlId": MODEL_CONTROL_ID,
        "controlOptions": {MODEL_CONTROL_ID: []},
        "runtimeArtifactMounts": [dict(item) for item in mounts],
        "projectionFiles": [dict(item) for item in (
            projection_files_override
            if projection_files_override is not None else projection_files()
        )],
        "stateProjection": {"target": STATE_TARGET},
        # Order 67's narrowed lock: no local run has observed this family's
        # per-turn home writes beyond the declared session subtree, so
        # admission holds one active execution per Profile until a gate does.
        "homeConcurrency": "exclusive",
        "adapter": {
            "command": "/usr/bin/node",
            "args": [ADAPTER_ARTIFACT_ENTRY, "--acp"],
            # The environment reaches the adapter process only, and the
            # credential is injected there as the declared environment
            # variable; no secret is written into any file or argument.
            "environment": dict(ADAPTER_ENVIRONMENT if adapter_environment is None else adapter_environment),
        },
    }


def deployment_document(
    *, capabilities_for, artifact_token: str, tree_digest: str, **harness: Any,
) -> dict[str, Any]:
    """The whole non-secret deployment file the Server loads."""
    return {
        "schemaVersion": 1,
        "harnesses": [harness_deployment(
            artifact_token=artifact_token, tree_digest=tree_digest, capabilities_for=capabilities_for, **harness,
        )],
    }


def main(arguments: Sequence[str] | None = None, *, capabilities_for) -> int:
    """Emit the production deployment file for one built artifact."""
    parser = argparse.ArgumentParser(description="Emit the qwen production deployment file.")
    parser.add_argument("--artifact-token", required=True,
                        help="mount token the deployment binds to the built qwen runtime artifact")
    parser.add_argument("--tree-digest", required=True,
                        help="the artifact manifest's sha256: tree digest")
    parser.add_argument("--out", required=True, help="path of the deployment file to write")
    parser.add_argument("--timeout-ms", type=int, default=120_000)
    options = parser.parse_args(arguments)
    document = deployment_document(
        artifact_token=options.artifact_token, tree_digest=options.tree_digest,
        timeout_ms=options.timeout_ms, capabilities_for=capabilities_for,
    )
    output = Path(options.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "QWEN_PRODUCTION_DEPLOYMENT_EMITTED",
        "out": str(output), "artifactTarget": ARTIFACT_TARGET,
        "productModelId": PRODUCT_MODEL_ID, "nativeModelValue": NATIVE_MODEL_VALUE,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":  # direct execution has no composing owner
    raise SystemExit("QWEN_CAPABILITY_SOURCE_REQUIRED: use an explicitly composed capability source")
