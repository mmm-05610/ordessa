"""Hermes production deployment template for the managed sidecar chain (non-secret).

This module owns the Hermes-specific parts of a production deployment: which
artifact directory carries the interpreter closure, how the reviewed native
configuration is projected into the confined guest home, where Hermes keeps its
own session store, and which environment variable carries the credential
reference.

It is deliberately *data*: the Server, Core, Worker and bwrap layers only ever
see the generic `runtimeArtifactMounts` / `projectionFiles` / `stateProjection`
/ `adapter` fields this template produces, and never a Hermes branch.

The native configuration (`deploy/hermes/config.yaml`) is byte-equal in content
to the configuration Work Order 42-D prepared (`hermesModelConfig()` in
`scripts/server-round1/model-validation-42d.mjs`): one provider block, the
user-confirmed product model `deepseek-flash`, the official DeepSeek root, a
permissive default output ceiling (order 108; a no-model gate pins its own
bounded ceiling), thinking disabled, and the lowest retry count the
harness supports (`agent.api_max_retries: 1`, i.e. at most two provider attempts
per prompt). A test asserts that equality, so the template cannot drift into a
second implementation.

Three measured facts shape this template, and all three are re-checked by the
production chain gate rather than assumed:

* **The native session store is a file inside the Hermes home.** Hermes keeps
  its authoritative session database at ``$HERMES_HOME/state.db`` (SQLite, with
  ``-wal``/``-shm`` beside it), not in a subdirectory. The deployment persists
  exactly one writable *directory* per Harness home, so ``HERMES_HOME`` is that
  persisted directory (``STATE_TARGET``) and the reviewed `config.yaml` is
  projected read-only *inside* it, at exactly ``$HERMES_HOME/config.yaml`` - the
  path Hermes itself reads. Nothing is materialized at run time any more: the
  reviewed file is a read-only mount, a write to it fails instead of forking a
  second configuration, and the projection is therefore a **protected state
  path** - it is excluded from every checkpoint and a checkpoint that tries to
  restore it is refused (see
  `plugins/harness/deploy/hermes/bootstrap.py`, which now verifies
  rather than copies it).
* **Hermes 0.19's ACP surface has no model control this bridge can address.**
  Its adapter advertises the ACP `models` session state and implements
  `session/set_model`; it deliberately answers `session/set_config_option` with
  an empty `configOptions` list and returns no `configOptions` from
  `session/new`. The pinned upstream bridge selects a model only through that
  list, so *every* model value a deployment freezes is refused inside the
  sidecar with `Harness model is not available: <model>` before any provider
  request. This template therefore declares **no** product model control
  (`MODEL_CONTROL_ID is None`) and pins the model in the native configuration
  instead; the gate demonstrates the refusal explicitly so the limitation is
  recorded rather than papered over.
* **The model is declared through Hermes' own user-defined-provider kind, and
  that is deliberate.** `model.provider` reads `custom` and the configuration
  declares one `providers.custom` block holding the product's provider content:
  the official root, the `key_env` reference, the `chat_completions` transport,
  the model catalogue and `extra_body` thinking off. Hermes' built-in `deepseek`
  provider would instead rewrite the model id before the request
  (`hermes_cli.model_normalize.normalize_model_for_provider` ->
  `_normalize_for_deepseek`: only `deepseek-v<digit>...` ids and reasoner-like
  names survive, everything else becomes `deepseek-chat`), so the provider would
  receive a model id the product never declared. A custom provider passes the id
  through unchanged, which is what makes the wire value exactly
  `deepseek-flash`. The block key is the bare kind (`custom`, not
  `custom:deepseek`) because Hermes' ACP session store persists the *resolved*
  provider identity and resumes a session through it: with a `custom:<key>`
  reference a resumed session resolves no provider block and falls back to a
  placeholder credential (measured; without the restored base URL it would even
  fall back to Hermes' default OpenRouter root), while the bare kind resolves the
  declared block on both the fresh and the resumed path. Recorded cost of this
  declaration, measured and asserted rather than hidden: Hermes' resolved
  provider identity and its ACP model state read `custom` /
  `custom:deepseek-flash` (`NATIVE_PROVIDER_IDENTITY`, `NATIVE_MODEL_SELECTION`),
  and the model-metadata lookup no longer matches the built-in DeepSeek table, so
  the context window falls back to the heuristic 128,000 instead of 1,000,000.
  The endpoint, credential reference, transport, request body options, output
  ceiling and retry bound are unchanged; nothing proxies, patches or renames a
  model.

Nothing here reads, stores, or emits credential content: the API key is an
environment *reference* (`$DEEPSEEK_API_KEY`) resolved by the harness inside the
sandbox, where the Worker materialized it.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from ..registry.capability_claims import capability_claims as _derive_capability_claims

#: The block the configuration declares carries the product's provider identity in
#: its content: the official DeepSeek root, the credential reference, the
#: transport, the request body options and the model catalogue.
HERMES_PROVIDER = "deepseek"
#: The `providers.<key>` the reviewed configuration actually declares, and the
#: value `model.provider` carries. Both are `custom`: Hermes' user-defined-provider
#: kind, which passes the model id through unchanged, while its built-in
#: `deepseek` provider folds everything that is not a first-class
#: `deepseek-v<digit>...` id or reasoner-like to `deepseek-chat`.
#:
#: Measured, and the reason the declaration is the bare kind rather than a
#: `custom:<key>` reference: Hermes' ACP session store persists the *resolved*
#: provider identity (`custom`), and a session is resumed through that stored
#: value. `custom:deepseek` resolves the block on a fresh session but a bare
#: `custom` does not, so a resumed session would fall back to a placeholder
#: credential (and, without the restored base URL, Hermes' default OpenRouter
#: root). Naming the block `custom` is what keeps the same endpoint, the same
#: `key_env` reference and the same model on both paths. See the module docstring.
PROVIDER_BLOCK_KEY = "custom"
MODEL_PROVIDER_DECLARATION = PROVIDER_BLOCK_KEY
#: Hermes' resolved provider identity under that declaration (`custom`), and the
#: ACP `models` spelling it produces (`custom:deepseek-flash`). Both are
#: observations the chain gate records, not values any layer above may act on.
NATIVE_PROVIDER_IDENTITY = "custom"
NATIVE_MODEL_SELECTION = f"{NATIVE_PROVIDER_IDENTITY}:{'deepseek-flash'}"
#: The product/ProviderModel model id the user confirmed (unchanged).
PRODUCT_MODEL_ID = "deepseek-flash"
#: The model id Hermes sends. Unlike Pi there is no provider-prefixed native
#: value to translate to: the pass-through declaration above is exactly what
#: makes the provider request carry the product id itself. `model_aliases()` is
#: therefore empty, and a test asserts the sidecar glue has no entry for Hermes.
NATIVE_MODEL_VALUE = PRODUCT_MODEL_ID
OFFICIAL_BASE_URL = "https://api.deepseek.com"
CREDENTIAL_KIND = "api-key"
CREDENTIAL_ENVIRONMENT = "DEEPSEEK_API_KEY"
#: Order 108 (AQ-0004): the ceiling a *real* deployment sends. 64 was a gate-era
#: cost control that truncated ordinary answers ("本来就不该砍掉长度"); a managed
#: run now gets a permissive default. A deployment that declares its own value
#: overrides this - the deployment-doc field is the registered remaining work
#: (see the 108 evidence doc), so today the permissive default is what lands.
DEFAULT_OUTPUT_TOKEN_LIMIT = 8192
#: Order 108: this is now the *gate's* ceiling, not the production template's.
#: Each no-model chain gate projects its fixture with this explicit value (cost
#: bounded, stable, never inherited silently from the template); the gate records
#: it as `outputTokenLimit`. Deleting the pin would let the gate project the
#: permissive default and its request budget would no longer be bounded - that is
#: the G2 counter-example the fixture-builder test guards.
OUTPUT_TOKEN_LIMIT = 64
#: `agent.api_max_retries: 1` in the prepared configuration: one retry, so at
#: most two provider attempts for one prompt. This is the lowest retry count
#: Hermes supports without disabling retries entirely, and it is declared here
#: so a gate can compare what the fake endpoint actually saw against it.
API_MAX_RETRIES = 1
MAX_PROVIDER_ATTEMPTS = API_MAX_RETRIES + 1

#: Stable artifact name and the confined guest path it is projected to. The
#: interpreter path inside it is derived from the same constant, so the two can
#: never disagree.
ARTIFACT_NAME = "hermes-runtime"
ARTIFACT_TARGET = f"/runtime/artifacts/{ARTIFACT_NAME}"
ARTIFACT_SITE_PACKAGES = f"{ARTIFACT_TARGET}/site-packages"
#: The module the artifact's `site-packages` provides; it is run as
#: `/usr/bin/python3 -m hermes_cli.main acp`, so the entry point inside the
#: artifact is resolved by the interpreter, never by a path this template
#: spells out twice.
ENTRY_MODULE = "hermes_cli.main"
ENTRY_RELATIVE = "hermes_cli/main.py"
ADAPTER_COMMAND = "/usr/bin/python3"
ADAPTER_ARGS = ("-m", ENTRY_MODULE, "acp")

#: The confined guest home: the read-only projection of the reviewed
#: configuration and the persisted state directory are the *same* directory.
#: It is a projection inside the one isolated guest home root (`/runtime/home`),
#: never the host home: `HERMES_HOME` names it, and Hermes' own default
#: (`$HOME/.hermes`) resolves to it too, so the explicit variable and the
#: default path can never disagree.
AGENT_HOME = "/runtime/home/.hermes"
CONFIG_SOURCE = "deploy/hermes/config.yaml"
CONFIG_NAME = "config.yaml"
CONFIG_TARGET = f"{AGENT_HOME}/{CONFIG_NAME}"
#: Hermes' own home, i.e. the one directory the Worker binds writable and reads
#: back. The reviewed `config.yaml` is projected read-only *inside* it and is
#: therefore a protected state path (see the module docstring): it is not state
#: and never reaches or comes from a checkpoint.
# The authoritative session database is $HERMES_HOME/state.db: sessions and
# other state share one SQLite file, so this family is the shared-DB shape
# of s14.2 and its library stays in the profile home (kind: profile-home).
STATE_TARGET = AGENT_HOME
#: The artifact's own `sitecustomize.py` runs the deployment verifier
#: (`agentbox_hermes_bootstrap`) before Hermes reads any configuration; the two
#: names are what the builder publishes and what it looks for.
BOOTSTRAP_MODULE = "agentbox_hermes_bootstrap"
SITECUSTOMIZE_NAME = "sitecustomize.py"

#: No product model control: see the module docstring for the measured reason.
#: A deployment that declared one would freeze `model=<product model>` into
#: every execution, and the pinned bridge would refuse it inside the sidecar
#: before any provider request.
MODEL_CONTROL_ID: str | None = None

#: Production adapter environment. Every entry is here for a reason:
#:
#: * `PYTHONPATH` - the artifact's own site directory is the whole interpreter
#:   closure; nothing else may satisfy an import.
#: * `PYTHONNOUSERSITE` - the guest has no per-user site directory, and the run
#:   must not depend on any.
#: * `PYTHONDONTWRITEBYTECODE` - the artifact is mounted read-only, so Python
#:   must never try to write a `__pycache__` beside a module it imports.
#: * `HERMES_HOME` - the persisted native home (see `STATE_TARGET`); Hermes
#:   keeps `state.db` and the restored transcript there, and reads the reviewed
#:   `config.yaml` from `$HERMES_HOME/config.yaml`, which is exactly the
#:   read-only projection this template declares.
#: * `HERMES_IGNORE_USER_CONFIG` / `HERMES_IGNORE_RULES` - no ambient
#:   `AGENTS.md`, `SOUL.md`, memory or preloaded skills may reach a managed
#:   run; the projected configuration is the only configuration.
#: * `HERMES_SKIP_NODE_BOOTSTRAP` - never try to bootstrap Node/npm inside the
#:   sandbox.
#: * `HERMES_MAX_ITERATIONS` - the tool-iteration ceiling 42-D prepared, so a
#:   run cannot grow past it. The *output* ceiling is not declared here: the
#:   Server's deployment validation refuses a credential-shaped environment key
#:   (`TOKEN|SECRET|KEY|...`), and `HERMES_MAX_TOKENS` trips it on `TOKENS`
#:   (measured - `build_runtime_from_sidecar_deployment` raises
#:   `SIDECAR_DEPLOYMENT_INVALID`). The output ceiling is therefore declared
#:   where Hermes reads it, in the projected `model.max_tokens` (a permissive
#:   default in production; a no-model gate pins its own bounded ceiling - order
#:   108), and the gate asserts the value that actually reached the provider.
#: * `HERMES_MODEL` / `HERMES_INFERENCE_MODEL` / `HERMES_TUI_PROVIDER` /
#:   `HERMES_INFERENCE_PROVIDER` - the model and provider declarations 42-D
#:   prepared. Measured: the ACP entry point takes both from `config.yaml`
#:   (`model.default`, `model.provider`), so these are declaration-consistent
#:   rather than load-bearing; they are kept so the environment a managed run
#:   sees is the environment that was prepared. The provider value is the same
#:   `custom` declaration the configuration carries, so a path that ever
#:   consulted it could not silently resolve the built-in provider instead.
ADAPTER_ENVIRONMENT = {
    "PYTHONPATH": ARTIFACT_SITE_PACKAGES,
    "PYTHONNOUSERSITE": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
    "HERMES_HOME": STATE_TARGET,
    "HERMES_IGNORE_USER_CONFIG": "1",
    "HERMES_IGNORE_RULES": "1",
    "HERMES_SKIP_NODE_BOOTSTRAP": "1",
    "HERMES_MAX_ITERATIONS": "1",
    "HERMES_MODEL": PRODUCT_MODEL_ID,
    "HERMES_INFERENCE_MODEL": PRODUCT_MODEL_ID,
    "HERMES_TUI_PROVIDER": MODEL_PROVIDER_DECLARATION,
    "HERMES_INFERENCE_PROVIDER": MODEL_PROVIDER_DECLARATION,
}

#: A mount token is a name the operator binds to a machine-local path.
TOKEN = re.compile(r"[a-z][a-z0-9-]{0,31}")

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_DIRECTORY = PLUGIN_ROOT / "deploy" / "hermes"
CONFIG_TEMPLATE = DEPLOY_DIRECTORY / CONFIG_NAME
#: Reviewed offline gate asset. It is never referenced by a production
#: deployment: it is projected and preloaded by the gate only.
LOOPBACK_GUARD = DEPLOY_DIRECTORY / "loopback-guard.py"
LOOPBACK_GUARD_TARGET = f"{AGENT_HOME}/{SITECUSTOMIZE_NAME}"


class HermesProductionTemplateError(ValueError):
    """A deployment declaration this template refuses to emit."""


def capability_claims() -> dict[str, bool]:
    """本模板部署时声明的 canonical 能力（派生自注册表，不手写）。

    `native_continuation` 是**已观测**项：全链门直接看到 Hermes 以 `session/resume`
    重开同一个 native session（无重放）并回投 `state.db`。`attach` 与 `permissions`
    不声明——没有任何运行时证据。
    """
    return _derive_capability_claims("hermes")


def config_yaml_text() -> str:
    """The checked-in native configuration, exactly as it is projected."""
    return CONFIG_TEMPLATE.read_text(encoding="utf-8")


def config_document() -> dict[str, Any]:
    """The checked-in native configuration, parsed.

    `yaml` is imported lazily: importing this module must never require a YAML
    parser, because the Server side only ever reads the deployment document the
    gate or the CLI produced.
    """
    import yaml  # noqa: PLC0415 - deliberately lazy, see docstring

    document = yaml.safe_load(config_yaml_text())
    if not isinstance(document, dict):
        raise HermesProductionTemplateError("HERMES_CONFIG_TEMPLATE_INVALID")
    return document


def loopback_config_document(base_url: str) -> dict[str, Any]:
    """A copy of the configuration with only the endpoint replaced.

    A no-model gate needs Hermes to talk to a local fake endpoint. Everything
    else - provider, model id, the permissive output ceiling, retry bound,
    thinking mode - stays the template's, and the production template itself is
    never rewritten. The *cost* ceiling a gate projects is pinned separately, by
    :func:`gate_projected_config_document` / :func:`loopback_config_yaml`, so the
    endpoint override stays minimal ("only baseUrl") while the gate's bounded
    budget is an explicit, audited value rather than an inherited default.
    """
    if not isinstance(base_url, str) or not base_url.startswith("http://127.0.0.1:"):
        raise HermesProductionTemplateError("HERMES_LOOPBACK_BASE_URL_INVALID")
    document = copy.deepcopy(config_document())
    document["model"]["base_url"] = base_url
    providers = document.get("providers") or {}
    if PROVIDER_BLOCK_KEY not in providers:
        raise HermesProductionTemplateError("HERMES_CONFIG_TEMPLATE_INVALID")
    providers[PROVIDER_BLOCK_KEY]["api"] = base_url
    return document


def gate_projected_config_document(base_url: str) -> dict[str, Any]:
    """The loopback fixture a chain gate projects, with the gate's own ceiling.

    Order 108: the gate does not inherit the template's permissive ceiling -
    it pins `model.max_tokens` to the explicit :data:`OUTPUT_TOKEN_LIMIT` so a
    no-model gate's request budget stays bounded and stable no matter what the
    production default is. The endpoint swap remains :func:`loopback_config_document`
    (only baseUrl); the ceiling pin is this separate, named step.
    """
    document = loopback_config_document(base_url)
    document["model"]["max_tokens"] = OUTPUT_TOKEN_LIMIT
    return document


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    if isinstance(value, Mapping):
        for key, item in value.items():
            flat.update(_flatten(item, f"{prefix}.{key}" if prefix else str(key)))
        return flat
    if isinstance(value, list):
        flat[prefix] = json.dumps(value, sort_keys=True)
        return flat
    flat[prefix] = value
    return flat


def documented_differences(base_url: str) -> dict[str, tuple[Any, Any]]:
    """Exactly which fields a loopback override changes, for auditing it.

    The prepared configuration records the endpoint twice (`model.base_url`,
    which the runtime provider resolution prefers, and `providers.custom.api`,
    the declared provider block's own endpoint). Both must point at the loopback
    endpoint for the gate to be able to prove that nothing else was contacted,
    and every difference is listed here rather than assumed.
    """
    production = _flatten(config_document())
    override = _flatten(loopback_config_document(base_url))
    keys = sorted(set(production) | set(override))
    return {key: (production.get(key), override.get(key)) for key in keys
            if production.get(key) != override.get(key)}


def loopback_config_yaml(base_url: str) -> str:
    """Serialize the gate's projected fixture (endpoint swapped, ceiling pinned).

    The projection target is one flat file; a small, deterministic serializer
    keeps the emitted YAML identical to the checked-in document's shape. The
    ceiling comes from :func:`gate_projected_config_document`, so what a chain
    gate projects is the gate's own bounded budget, not the template default.
    """
    loopback = gate_projected_config_document(base_url)
    # The projection target is one flat file; a small, deterministic serializer
    # keeps the emitted YAML identical to the checked-in document's shape.
    lines: list[str] = []
    _emit(loopback, lines, 0)
    return "\n".join(lines) + "\n"


def _emit(value: Any, lines: list[str], indent: int) -> None:
    pad = "  " * indent
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(item, (Mapping, dict)) or (
                isinstance(item, list) and item and isinstance(item[0], Mapping)
            ):
                lines.append(f"{pad}{key}:")
                _emit(item, lines, indent + 1)
            elif isinstance(item, list):
                if not item:
                    lines.append(f"{pad}{key}: []")
                    continue
                lines.append(f"{pad}{key}:")
                for entry in item:
                    lines.append(f"{pad}  - {json.dumps(entry)}")
            elif isinstance(item, bool):
                lines.append(f"{pad}{key}: {'true' if item else 'false'}")
            elif isinstance(item, str):
                lines.append(f"{pad}{key}: {item}")
            elif item is None:
                lines.append(f"{pad}{key}: null")
            else:
                lines.append(f"{pad}{key}: {item}")
        return
    raise HermesProductionTemplateError("HERMES_CONFIG_TEMPLATE_INVALID")


def model_aliases() -> dict[str, str]:
    """Product model id -> native catalogue value (empty for Hermes).

    Hermes receives the product id itself: the configuration declares the
    pass-through provider reference (`MODEL_PROVIDER_DECLARATION`) instead of the
    built-in provider that would fold the id, so there is nothing to translate
    and no alias may be invented here. A test compares this table with the
    sidecar glue's own.
    """
    return {}


def native_model(model: object) -> object:
    """Pass a product model id through untouched (no alias exists).

    The translation Hermes needs is *not* a model-name mapping: it is the
    provider declaration that stops Hermes from normalizing the id. The value the
    sidecar glue carries therefore stays the product id.
    """
    return model


def projection_files() -> tuple[dict[str, str], ...]:
    """The reviewed native configuration, read-only, inside Hermes' own home.

    `HERMES_HOME` is the persisted state directory, and the file Hermes reads is
    `$HERMES_HOME/config.yaml` - the path this projection names. Nothing copies
    or materializes it at run time: the reviewed file *is* the file Hermes
    opens, so configuration cannot drift into a second, writable copy.
    """
    return ({"source": CONFIG_SOURCE, "target": CONFIG_TARGET},)


def harness_deployment(
    *,
    artifact_token: str,
    tree_digest: str,
    timeout_ms: int = 120_000,
    adapter_environment: Mapping[str, str] | None = None,
    projection_files_override: Sequence[Mapping[str, str]] | None = None,
    runtime_artifact_mounts_override: Sequence[Mapping[str, str]] | None = None,
    model_control_id: str | None = MODEL_CONTROL_ID,
) -> dict[str, Any]:
    """One production Harness entry, ready for a non-secret deployment file."""
    if not isinstance(artifact_token, str) or not TOKEN.fullmatch(artifact_token):
        raise HermesProductionTemplateError("HERMES_ARTIFACT_TOKEN_INVALID")
    if not isinstance(tree_digest, str) or not tree_digest.startswith("sha256:") or len(tree_digest) != 71:
        raise HermesProductionTemplateError("HERMES_ARTIFACT_DIGEST_INVALID")
    if adapter_environment is not None and any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in adapter_environment.items()
    ):
        raise HermesProductionTemplateError("HERMES_ADAPTER_ENVIRONMENT_INVALID")
    mounts = runtime_artifact_mounts_override or ({
        "token": artifact_token, "target": ARTIFACT_TARGET, "treeDigest": tree_digest,
    },)
    deployment: dict[str, Any] = {
        "id": "hermes",
        "timeoutMs": timeout_ms,
        # 能力声明**派生**自注册表（`harnesses.toml`），不由本模板手写：see
        # `registry.capability_claims`。该表里 hermes 已包含 `native_continuation`
        # （全链门直接观测到同 native id 的 `session/resume` 重开），并且**不**包含
        # `attach`/`permissions`——本模板无权自行加项。
        "capabilityClaims": capability_claims(),
        "credentialKind": CREDENTIAL_KIND,
        "credentialEnvironment": CREDENTIAL_ENVIRONMENT,
        # Order 092: canonical protocols this family can speak -> native dialect value.
        "wireProtocols": {"openai-chat": "chat_completions"},
        "runtimeArtifactMounts": [dict(item) for item in mounts],
        "projectionFiles": [dict(item) for item in (
            projection_files_override
            if projection_files_override is not None else projection_files()
        )],
        "stateProjection": {"target": STATE_TARGET},
        "usageProbe": {"journalSuffix": "state.db", "format": "hermes-state-db"},
        "adapter": {
            "command": ADAPTER_COMMAND,
            "args": list(ADAPTER_ARGS),
            # The environment reaches the adapter process only, and the
            # credential is injected there as the declared environment
            # variable; no secret is written into any file or argument.
            "environment": dict(ADAPTER_ENVIRONMENT if adapter_environment is None else adapter_environment),
        },
    }
    if model_control_id is not None:
        # Declared only where a caller explicitly asks for it (the production
        # chain gate, to demonstrate the refusal above). No default value is
        # advertised, because a model selection is a Provider/Model reference
        # the product resolves, not one of a fixed set of native strings.
        deployment["modelControlId"] = model_control_id
        deployment["controlOptions"] = {model_control_id: []}
    return deployment


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
    parser = argparse.ArgumentParser(description="Emit the Hermes production deployment file.")
    parser.add_argument("--artifact-source", required=True,
                        help="canonical WSL path of the built Hermes runtime artifact")
    parser.add_argument("--tree-digest", required=True,
                        help="the artifact manifest's sha256: tree digest")
    parser.add_argument("--out", required=True, help="path of the deployment file to write")
    parser.add_argument("--timeout-ms", type=int, default=120_000)
    parser.add_argument("--model-control-id", default=None,
                        help="test-only: declare a product model control (see the module docstring)")
    options = parser.parse_args(arguments)
    document = deployment_document(
        artifact_token=options.artifact_token, tree_digest=options.tree_digest,
        timeout_ms=options.timeout_ms,
        model_control_id=options.model_control_id,
    )
    output = Path(options.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "HERMES_PRODUCTION_DEPLOYMENT_EMITTED",
        "out": str(output), "artifactTarget": ARTIFACT_TARGET,
        "productModelId": PRODUCT_MODEL_ID,
        "modelProviderDeclaration": MODEL_PROVIDER_DECLARATION,
        "stateTarget": STATE_TARGET,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI parity with the module
    raise SystemExit(main())
