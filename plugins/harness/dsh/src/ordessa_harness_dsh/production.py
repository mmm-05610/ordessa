"""dsh production deployment template for the managed sidecar chain (non-secret).

Work Order 43's faithful clone of the Pi production template (see
`ordessa_harness_dsh/production.py`), for DeepSeek's official Harness
launcher `@deepseek-ai/dsh`. This module owns the dsh-specific parts of a
production deployment: which artifact directory carries the launcher and its
native dependency closure, how the product model id is spelled in the native
model catalogue, which environment variable carries the credential reference,
and which confined guest paths hold the native configuration and the native
session store.

It is deliberately *data*: the Server, Core, Worker and bwrap layers only ever
see the generic `runtimeArtifactMounts` / `projectionFiles` / `stateProjection`
/ `adapter` fields this template produces, and never a dsh branch.

The native configuration itself (`settings.yaml`) is checked in next to this
module under `deploy/dsh/`: one provider, the user-confirmed product model
`deepseek-flash`, the official DeepSeek root, a permissive default output ceiling
(order 108; a no-model gate pins its own bounded ceiling), and
thinking disabled. A test asserts the checked-in bytes against this module's
constants, so the template cannot drift into a second implementation. The
loopback endpoint a no-model gate uses is produced by replacing
`llm-deepseek.baseURL` alone.

Nothing here reads, stores, or emits credential content: the API key is an
environment *reference* (`$DEEPSEEK_API_KEY`) resolved by dsh inside the
sandbox, where the Worker materialized it.

The guest layout is the common one every Harness uses: exactly one isolated
home root (`/runtime/home`) holds a read-only projection of the reviewed native
configuration and exactly one writable state directory

* read-only ``settings.yaml`` at ``/runtime/home/.dsh/settings.yaml``,
* writable ``/runtime/home/.dsh/sessions`` for dsh's own session store,
* ``DSH_HOME=/runtime/home/.dsh`` for both halves.

The dedicated variable and dsh's ``$HOME``-derived default (``/runtime/home``
is the guest ``HOME``, so ``~/.dsh`` resolves to the same directory) therefore
converge: nothing is copied into a writable home at run time, and the reviewed
file is the only configuration the process can read.
"""
from __future__ import annotations

import argparse
import re
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

# P-B pilot (approvals/PB-dsh-pilot-release.md §三处改码①②):
# ① brand-family code imports the brand-neutral core directly (direction:
#    package -> core, which is the target shape itself);
# ② PyYAML is imported lazily inside the two render functions below - not at
#    module top - so importing this package needs no YAML anywhere and the
#    redistribution closure stays exactly as wide as before (with-PyYAML
#    environments behave byte-identically; reproduced pre-change as
#    `ModuleNotFoundError: No module named 'yaml'` at top-level import).
from ordessa_server_product.harness_adapters.registry.capability_claims import capability_claims as _derive_capability_claims

DSH_PROVIDER = "deepseek-official"
#: The product/ProviderModel model id the user confirmed. It must never change
#: silently: the native catalogue value below is derived from it.
PRODUCT_MODEL_ID = "deepseek-flash"
#: The value dsh's ACP model config option advertises for that product model.
#: The option's values are opaque strings, and dsh's shipped picker spells this
#: entry as a JSON-array string over the `deepseek-official` route (observed
#: first-hand over `session/new`; displayed to users as "DeepSeek-V41-Flash").
NATIVE_MODEL_VALUE = '["deepseek-official","deepseek-flash"]'
OFFICIAL_BASE_URL = "https://api.deepseek.com"
CREDENTIAL_KIND = "api-key"
CREDENTIAL_ENVIRONMENT = "DEEPSEEK_API_KEY"
#: Order 108 (AQ-0004): the ceiling a *real* deployment sends. The 64 was a
#: gate-era cost control that truncated ordinary answers; a managed run now gets
#: a permissive default (a deployment-declared override would win over it).
DEFAULT_OUTPUT_TOKEN_LIMIT = 8192
#: Order 108: the *gate's* explicit ceiling, not the template's, so a no-model
#: gate's request budget stays bounded regardless of the production default.
OUTPUT_TOKEN_LIMIT = 64

#: Stable artifact name and the confined guest path it is projected to. The
#: adapter entry is derived from it, so the two can never disagree.
ARTIFACT_NAME = "dsh-runtime"
ARTIFACT_TARGET = f"/runtime/artifacts/{ARTIFACT_NAME}"
ADAPTER_ARTIFACT_RELATIVE_ENTRY = "node_modules/@deepseek-ai/dsh/lib/bin.js"
ADAPTER_ARTIFACT_ENTRY = f"{ARTIFACT_TARGET}/{ADAPTER_ARTIFACT_RELATIVE_ENTRY}"
#: Declared by the pinned builder output; the deployment only records it.
ADAPTER_PACKAGE = "@deepseek-ai/dsh"
ADAPTER_VERSION = "0.1.5-rc.1"

#: Confined harness home and the native session store subtree inside it. The
#: home is a projection inside the one isolated guest home root
#: (`/runtime/home`), never the host home: `DSH_HOME` below names the same
#: directory, and dsh's own default (`$HOME/.dsh`) resolves to it too, so an
#: explicit variable and the default path can never disagree.
HARNESS_HOME = "/runtime/home/.dsh"
STATE_TARGET = f"{HARNESS_HOME}/sessions"

#: Production adapter environment. `DSH_HOME` pins the harness home to the
#: isolated projection for both configuration and session state. No offline or
#: telemetry switches are invented: startup network behavior is a gate
#: observation (the loopback guard), not a template claim.
ADAPTER_ENVIRONMENT = {
    "DSH_HOME": HARNESS_HOME,
}

#: The product control that selects the model. The Server only knows this id
#: from the declaration; nothing about dsh is hardcoded in it. No default value
#: is advertised, because a model selection is a Provider/Model reference the
#: product resolves, not one of a fixed set of native strings - and a silently
#: discovered default would run a model the user never chose.
MODEL_CONTROL_ID = "model"

# P-B (§三处改码③): one directory level less than the legacy in-tree path
# (`.../pacthold.plugins/harness/dsh/src/ordessa_harness_dshproduction.py` -> parents[3]; here -> parents[2]),
# so DEPLOY_DIRECTORY keeps pointing at this package's checked-in `deploy/dsh/`
# with byte-identical template content (hashes verified in the checkpoint).
PLUGIN_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_DIRECTORY = PLUGIN_ROOT / "deploy" / "dsh"
SETTINGS_TEMPLATE = DEPLOY_DIRECTORY / "settings.yaml"
#: The settings namespace whose section this deployment writes; the settings
#: document maps namespace -> user section.
SETTINGS_NAMESPACE = "llm-deepseek"
#: Reviewed offline asset for gates that must not reach a real endpoint. It is
#: never referenced by a production deployment.
LOOPBACK_GUARD = DEPLOY_DIRECTORY / "loopback-guard.cjs"
LOOPBACK_GUARD_TARGET = f"{HARNESS_HOME}/dsh-loopback-guard.cjs"

SETTINGS_SOURCE = "deploy/dsh/settings.yaml"


class DshProductionTemplateError(ValueError):
    """A deployment declaration this template refuses to emit."""


def capability_claims() -> dict[str, bool]:
    """本模板部署时声明的 canonical 能力（派生自注册表，不手写）。

    全部语义级能力（attach/permissions/native_continuation 的观测结论）由链门的
    证据表决定，本模板无权改写；此处返回的只是注册表里的静态声明上限。
    """
    return _derive_capability_claims("dsh")


def settings_document() -> dict[str, Any]:
    """The checked-in native settings document (official root)."""
    import yaml  # lazy (P-B §②): rendering needs YAML, importing this module does not
    return yaml.safe_load(SETTINGS_TEMPLATE.read_text(encoding="utf-8"))


def loopback_settings_document(base_url: str) -> dict[str, Any]:
    """A copy of the settings document with only `baseURL` replaced.

    A no-model gate needs dsh to talk to a local fake endpoint. Everything
    else - provider route, output ceiling, thinking mode - stays the template's,
    and the production template itself is never rewritten.
    """
    if not isinstance(base_url, str) or not base_url.startswith("http://127.0.0.1:"):
        raise DshProductionTemplateError("DSH_LOOPBACK_BASE_URL_INVALID")
    document = settings_document()
    document[SETTINGS_NAMESPACE]["baseURL"] = base_url
    return document


def gate_settings_document(base_url: str) -> dict[str, Any]:
    """The loopback settings a chain gate projects, pinned to the gate ceiling.

    Order 108: the endpoint swap stays :func:`loopback_settings_document` (only
    `baseURL`); the gate's budget is an explicit, separate pin to
    :data:`OUTPUT_TOKEN_LIMIT`, so a no-model gate does not inherit the permissive
    production default (removing the pin is the G2 counter-example).
    """
    document = loopback_settings_document(base_url)
    document[SETTINGS_NAMESPACE]["maxTokens"] = OUTPUT_TOKEN_LIMIT
    return document


def render_settings_document(document: Mapping[str, Any]) -> bytes:
    """Deterministic YAML bytes for one settings document.

    The gate projects these bytes; sort_keys keeps two runs byte-identical so a
    digest comparison never depends on dict ordering.
    """
    import yaml  # lazy (P-B §②): same contract as settings_document
    return yaml.safe_dump(dict(document), sort_keys=True, default_flow_style=False).encode("utf-8")


def documented_differences(base_url: str) -> dict[str, tuple[Any, Any]]:
    """Exactly which fields a loopback override changes, for auditing it."""
    production = settings_document()
    override = loopback_settings_document(base_url)
    return {
        f"{SETTINGS_NAMESPACE}.{key}": (production[SETTINGS_NAMESPACE].get(key),
                                        override[SETTINGS_NAMESPACE].get(key))
        for key in sorted(set(production[SETTINGS_NAMESPACE]) | set(override[SETTINGS_NAMESPACE]))
        if production[SETTINGS_NAMESPACE].get(key) != override[SETTINGS_NAMESPACE].get(key)
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
    """The native configuration, read-only, inside the confined harness home."""
    return (
        {"source": SETTINGS_SOURCE, "target": f"{HARNESS_HOME}/settings.yaml"},
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
        raise DshProductionTemplateError("DSH_ARTIFACT_TOKEN_INVALID")
    if not isinstance(tree_digest, str) or not tree_digest.startswith("sha256:") or len(tree_digest) != 71:
        raise DshProductionTemplateError("DSH_ARTIFACT_DIGEST_INVALID")
    if adapter_environment is not None and any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in adapter_environment.items()
    ):
        raise DshProductionTemplateError("DSH_ADAPTER_ENVIRONMENT_INVALID")
    mounts = runtime_artifact_mounts_override or ({
        "token": artifact_token, "target": ARTIFACT_TARGET, "treeDigest": tree_digest,
    },)
    return {
        "id": "dsh",
        "timeoutMs": timeout_ms,
        # 能力声明**派生**自注册表（`harnesses.toml`），不由本模板手写：see
        # `registry.capability_claims`。它是静态声明上限，测试逐项断言 true 项 == TOML，
        # 因此"生产部署声明的能力"与"注册表声明的能力"不可能漂移。
        "capabilityClaims": capability_claims(),
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
            "args": [ADAPTER_ARTIFACT_ENTRY, "--profile", "acp"],
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
    parser = argparse.ArgumentParser(description="Emit the dsh production deployment file.")
    parser.add_argument("--artifact-token", required=True,
                        help="mount token the deployment binds to the built dsh runtime artifact")
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
        "result": "DSH_PRODUCTION_DEPLOYMENT_EMITTED",
        "out": str(output), "artifactTarget": ARTIFACT_TARGET,
        "productModelId": PRODUCT_MODEL_ID, "nativeModelValue": NATIVE_MODEL_VALUE,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI parity with the module
    raise SystemExit(main())
