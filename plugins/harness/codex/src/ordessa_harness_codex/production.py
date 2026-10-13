"""Codex 生产部署模板（非秘密），由插件层唯一拥有。

这个模块拥有 Codex 部署里"属于这个 Harness"的部分：摘要固定的运行时工件在
guest 的挂载点、官方配置（`config.toml` + 完整 `models.json`）在隔离 HOME 里的
位置、原生状态目录（Codex 自己的 `$CODEX_HOME`）、凭据的环境变量名，以及适配器
的入口。它只输出**通用字段**：Server、Core、Worker 与 bwrap 只看到
`runtimeArtifactMounts` / `projectionFiles` / `stateProjection` / `adapter`，
任何一层都不认识 Codex。

与另外三家同构：这里**不复制第二套漂移实现**。原生配置逐字节来自
`deployment/config.toml` 与 `deployment/models.json`，后者等于官方
`codex-deepseek-setup.sh` 1.3.0 的 `write_models_json` heredoc 写出的文件字节
（由 `tests/test_codex_production_template.py` 用签入的脚本字节重算，不执行脚本、
不访问网络）。`deployment/models.json` 是唯一签入的模型目录源；其内容由官方
`codex-deepseek-setup.sh` heredoc 与固定 SHA-256 `bce20f679495809f4fa6e48672b6dcbab84b6adff5251890b6e6a21eddb9c12f`
共同约束。remote 投影与部署模板都读取该文件，不再保留第二份副本。

隔离约定（见 docs/server-round1/fullstack/profile-home-isolation.md §2.3）：

* `HOME=/runtime/home`（bwrap 模板创建），Codex 的原生默认路径就是
  `$HOME/.codex`；
* `CODEX_HOME=/runtime/home/.codex` —— 显式变量与 `$HOME` 派生的默认路径指向
  **同一目录**（同一份投影的两种寻址方式，不是两份拷贝）；
* 只读投影：`/runtime/home/.codex/config.toml`、`/runtime/home/.codex/models.json`；
* 有界可写 state 投影：`/runtime/home/.codex`（Codex 自己在其中写
  `sessions/`、`*.sqlite`、`skills/` 等）；两个只读文件落在 state 子树内，因此被
  Server/bwrap 按"受保护 state 路径"排除出 checkpoint（`home_projection` 的派生
  规则），恢复时同名的相对路径被类型化拒绝。

凭据的 **AgentBox 注入路径**只经
SecretStore → Worker secret 帧 → 环境变量到达适配器进程（AgentBox 自身不把凭据写进任何
文件或参数）；适配器/原生 Harness 拿到环境值之后是否落盘，由下面的 ephemeral 说明与
门内凭据扫描兜底——已证实 `auth.json` 未生成，其他 native state 路径已有反例（见
state-error-boundary.md §4.3），未经证明前不得进入真实凭据门：

* ACP 适配器 `@agentclientprotocol/codex-acp` 1.1.14 的 `api-key` 认证**只**读
  `CODEX_API_KEY`/`OPENAI_API_KEY` 两个环境变量（bundle 里 `readApiKeyFromEnv()`），
  而被复用的上游 bridge 一定会执行这一步认证；因此注入的名字必须是其中之一。
* 原生 Codex 的模型请求凭证来自 `env_key`，所以 `env_key` 与注入名必须是同一个
  变量（实测：两者都在时请求头用的是 `env_key` 的值；只有 `env_key` 没有
  ACP 认证变量时认证步骤失败）。
* `cli_auth_credentials_store = "ephemeral"` 让那次 ACP 认证在实测轮里不把凭据落成
  `$CODEX_HOME/auth.json`（实测：该值为 `file`/缺省时 app-server 会写出含原文的
  `auth.json`，sidecar 的 state 捕获会以 `SIDECAR_STATE_CONTAINS_SECRET` 拒绝这种捕获）。
  **这只证明 auth.json 未生成**；其他 native state 路径尚未证明安全——2026-09-15 的
  无模型门中约 1/15 轮凭据扫描在原生 state 命中过假 token（fail-closed 拦截，写入文件
  待捕获），见 docs/server-round1/fullstack/state-error-boundary.md §4.3。

本模块**不**读、不存、不产出任何凭据内容。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import tomllib
from typing import Any, Mapping, Sequence

from ordessa_execution_agents.harness.definitions.harness_capabilities import CANONICAL_CAPABILITY_IDS

HARNESS_ID = "codex"

#: 产品/ProviderModel 模型 id（用户确认过的那个），不得被静默改写。
PRODUCT_MODEL_ID = "deepseek-flash"
#: Codex 自己的模型目录（`models.json`）里的 slug 与产品 id **一字不差**：
#: 这里没有别名表，任何"Codex 也写成 provider/model"的假设都是错的（实测
#: `session/new` 播发的 configOptions.model.options = [deepseek-flash,
#: deepseek-v4-pro]）。产品白名单仍然是只允许 `deepseek-flash`。
NATIVE_MODEL_ID = PRODUCT_MODEL_ID
PROVIDER_ID = "deepseek"
OFFICIAL_BASE_URL = "https://api.deepseek.com/"
CREDENTIAL_KIND = "api-key"
#: 注入名与 `config.toml` 的 `env_key` 必须相同（见模块 docstring 的三条实测）。
CREDENTIAL_ENVIRONMENT = "CODEX_API_KEY"
#: 适配器的 ACP 认证方法 id（上游 profile 默认是 `chat-gpt`，那需要磁盘登录态，
#: 本隔离里没有也不得有）。
PREFERRED_AUTH_METHOD = "api-key"

#: 固定工件名与它在 guest 的挂载点；适配器入口由它派生，两者不可能不一致。
ARTIFACT_NAME = "codex-runtime"
ARTIFACT_TARGET = f"/runtime/artifacts/{ARTIFACT_NAME}"
ADAPTER_ARTIFACT_RELATIVE_ENTRY = "node_modules/@agentclientprotocol/codex-acp/dist/index.js"
ADAPTER_ARTIFACT_ENTRY = f"{ARTIFACT_TARGET}/{ADAPTER_ARTIFACT_RELATIVE_ENTRY}"
#: 由固定版本的构建器取证，部署只记录它。
ADAPTER_PACKAGE = "@agentclientprotocol/codex-acp"
ADAPTER_VERSION = "1.1.14"
#: 工件闭包里平台原生 Codex CLI 的版本（`codex --version` 取证）。
CODEX_CLI_VERSION = "0.147.0"

#: 隔离 HOME 以及 Codex 的原生目录（state 投影目标）。
AGENT_HOME = "/runtime/home"
CODEX_HOME = f"{AGENT_HOME}/.codex"
CONFIG_TARGET = f"{CODEX_HOME}/config.toml"
MODELS_TARGET = f"{CODEX_HOME}/models.json"
STATE_TARGET = f"{CODEX_HOME}/sessions"

#: 生产 adapter 环境。每一项都有理由：
#: * `CODEX_HOME` 把原生状态根固定到隔离投影（也是适配器传给 app-server 子进程的
#:   同一个环境，实测 app-server 自报 `codexHome=/runtime/home/.codex`）；
#: * `NO_BROWSER=1` 关掉适配器对 `chat-gpt` 浏览器登录方法的播发（guest 里没有
#:   浏览器，登录态也不得存在），只留 `api-key`。
ADAPTER_ENVIRONMENT = {
    "CODEX_HOME": CODEX_HOME,
    "NO_BROWSER": "1",
}

#: 产品模型控件 id：Codex 的 ACP 面**实测**在 `session/new` 返回
#: `configOptions`（id=model，值就是产品 id），所以这条控件可以声明；控件不给默认值
#: （模型是 Provider/Model 引用，由产品解析）。
MODEL_CONTROL_ID = "model"

#: A mount token is a name the operator binds to a machine-local path.
TOKEN = re.compile(r"[a-z][a-z0-9-]{0,31}")

DEPLOY_DIRECTORY = Path(__file__).resolve().parent / "deployment"
CONFIG_TEMPLATE = DEPLOY_DIRECTORY / "config.toml"
MODELS_TEMPLATE = DEPLOY_DIRECTORY / "models.json"
#: 官方安装脚本的签入字节（只做证据，从不执行、从不投影进 guest）。它们属于
#: Codex-owned optional tooling provenance. These bytes are evidence only; the
#: runtime never reads them during execution.
OFFICIAL_SCRIPT = Path(__file__).resolve().parents[2] / "tooling" / "provenance" / "codex-deepseek-setup.sh"
OFFICIAL_SCRIPT_METADATA = Path(__file__).resolve().parents[2] / "tooling" / "provenance" / "official-script.json"

CONFIG_SOURCE = "deploy/codex/config.toml"
MODELS_SOURCE = "deploy/codex/models.json"

#: 注册表里的 `harness_type`（与 `HARNESS_ID` 同值，保留显式常量便于审计）。
HARNESS_TYPE = HARNESS_ID

#: 明确的否定/肯定事实，供测试与审计断言：本 Harness 到本阶段为止是否有生产部署模板
#: 与真实链门证据。只有在 `codex-production-chain-gate.py` 两轮真实通过之后才为 True；
#: 模板先写下来不等于链门已通过，"两件事不是同一件事"。
HAS_PRODUCTION_DEPLOYMENT = True


class CodexProductionTemplateError(ValueError):
    """本模板拒绝输出的部署声明。"""


def capability_claims(*, capabilities_for) -> dict[str, bool]:
    """本模板部署时声明的 canonical 能力（派生自注册表，不手写）。

    派生自 `harnesses.toml` 的这一份是**静态上限**；`observed_capabilities()` 是
    链门真正观测到的子集。两者都不由本模板手写，测试逐项比对。
    """
    if not callable(capabilities_for):
        raise CodexProductionTemplateError("CODEX_CAPABILITY_SOURCE_REQUIRED")
    claims = capabilities_for(HARNESS_ID)
    if (not isinstance(claims, Mapping) or set(claims) != set(CANONICAL_CAPABILITY_IDS)
            or any(type(claims[key]) is not bool for key in CANONICAL_CAPABILITY_IDS)):
        raise CodexProductionTemplateError("CODEX_CAPABILITY_CLAIMS_INVALID")
    return {key: claims[key] for key in CANONICAL_CAPABILITY_IDS}


def observed_capabilities() -> frozenset[str]:
    """`codex-production-chain-gate.py` 在本阶段的运行里真正观测到的 canonical 能力。

    每一条都有运行期证据，证据形状与另外三家的门一致：

    * `start`/`finish`：sidecar 的 `create`+`prompt` 被真实调用且该轮交付为
      `completed`（门的 `rounds.*.state`）；
    * `stream`：终止前有 delta 且 `deltaSeq` 先于 `completedSeq`
      （门的 `rounds.*.deltasBeforeCompletion`）；
    * `observe`：`create` 返回了原生会话身份（门的 `nativeSessionId`）；
    * `native_continuation`：第二轮以**原生重开**打开同一个 native id，且第二轮上
      下文里带第一轮的 user+assistant（门的 `reopenObservation`）。

    `attach` 与 `permissions` **不在**这里：本阶段没有任何一次真实附件投递，也没有
    一次权限裁决请求，门的证据表里它们保持 not-observed。

    在 `codex-production-chain-gate.py` 真实跑通（exit 0，两轮 + 重开证据齐备）之前，
    这里返回**空集**：模板已经写下来，但没有任何一条运行证据可以被叫"已观测"。
    """
    if not HAS_PRODUCTION_DEPLOYMENT:
        return frozenset()
    return frozenset({"start", "stream", "finish", "observe", "native_continuation"})


def official_script_metadata() -> dict[str, Any]:
    """官方脚本的取证记录（URL/版本/SHA-256/heredoc 摘要），只读。"""
    return json.loads(OFFICIAL_SCRIPT_METADATA.read_text(encoding="utf-8"))


#: The official Codex feature flags this deployment turns off, with the
#: first-hand evidence recorded in the state-error-boundary report:
#: `plugins` materializes the bundled plugin/skill corpus into
#: `$CODEX_HOME/.tmp/plugins/` (measured 5,529 files) and `shell_snapshot`
#: writes the credential-bearing environment dump into
#: `$CODEX_HOME/shell_snapshots/*.sh`.
OFFICIAL_FEATURE_FLAGS_OFF = ("plugins", "shell_snapshot")


def config_bytes() -> bytes:
    """签入的原生配置，逐字节（只读投影进隔离 HOME）。"""
    return CONFIG_TEMPLATE.read_bytes()


def config_document() -> dict[str, Any]:
    """签入的原生配置按 TOML 解析后的字段视图（审计与逐字段测试用）。"""
    return tomllib.loads(config_bytes().decode("utf-8"))


def models_bytes() -> bytes:
    """签入的官方完整模型目录，逐字节（只读投影进隔离 HOME）。"""
    return MODELS_TEMPLATE.read_bytes()


def models_document() -> dict[str, Any]:
    """签入的官方模型目录按 JSON 解析。"""
    return json.loads(models_bytes().decode("utf-8"))


def loopback_config_bytes(base_url: str) -> bytes:
    """只替换 provider 的 `base_url` 的副本字节，把生产配置指向本机假端点。

    生产模板自身**从不**被改写：返回的是新字节。替换是逐行的、唯一的，因此除了
    这一处地址之外不可能悄悄改掉别的字段（`documented_differences` 用解析后的
    字段视图复核）。
    """
    if not isinstance(base_url, str) or not base_url.startswith("http://127.0.0.1:"):
        raise CodexProductionTemplateError("CODEX_LOOPBACK_BASE_URL_INVALID")
    text = config_bytes().decode("utf-8")
    official_line = f'base_url = "{OFFICIAL_BASE_URL}"'
    replacement_line = f'base_url = "{base_url}"'
    if text.count(official_line) != 1:
        raise CodexProductionTemplateError("CODEX_OFFICIAL_BASE_URL_NOT_UNIQUE")
    return text.replace(official_line, replacement_line).encode("utf-8")


def documented_differences(base_url: str) -> dict[str, tuple[Any, Any]]:
    """loopback 覆盖到底改了哪些**字段**，用于审计"只改了一处"。"""
    production = config_document()
    override = tomllib.loads(loopback_config_bytes(base_url).decode("utf-8"))
    changed: dict[str, tuple[Any, Any]] = {}

    def walk(before: Mapping[str, Any], after: Mapping[str, Any], prefix: str) -> None:
        for key in sorted(set(before) | set(after)):
            left, right = before.get(key), after.get(key)
            dotted = f"{prefix}.{key}" if prefix else f"{key}"
            if isinstance(left, Mapping) and isinstance(right, Mapping):
                walk(left, right, dotted)
            elif left != right:
                changed[dotted] = (left, right)

    walk(production, override, "")
    return changed


def model_aliases() -> dict[str, str]:
    """产品模型 id -> 原生目录值：**空表**（Codex 的目录值与产品 id 相同）。

    与另外三家不同，Codex 没有 `provider/model` 拼写，所以这里没有映射项；
    变体（reasoning effort）由适配器自己的 `reasoning_effort` 控件承载，不是模型别名。
    """
    return {}


def native_model(model: object) -> object:
    """翻译一个产品模型 id；没有别名时原样透传（未知模型由适配器在发包前拒绝）。"""
    if not isinstance(model, str):
        return model
    return model_aliases().get(model, model)


def projection_files() -> tuple[dict[str, str], ...]:
    """只读进入隔离 HOME 的原生配置（两份都在 `$CODEX_HOME` 下）。"""
    return (
        {"source": CONFIG_SOURCE, "target": CONFIG_TARGET},
        {"source": MODELS_SOURCE, "target": MODELS_TARGET},
    )


def harness_deployment(
    *, capabilities_for,
    artifact_token: str,
    tree_digest: str,
    timeout_ms: int = 120_000,
    adapter_environment: Mapping[str, str] | None = None,
    projection_files_override: Sequence[Mapping[str, str]] | None = None,
    runtime_artifact_mounts_override: Sequence[Mapping[str, str]] | None = None,
    preferred_auth_method: str | None = PREFERRED_AUTH_METHOD,
) -> dict[str, Any]:
    """一条生产 Harness 声明，可直接写进非秘密 deployment 文件。"""
    if not isinstance(artifact_token, str) or not TOKEN.fullmatch(artifact_token):
        raise CodexProductionTemplateError("CODEX_ARTIFACT_TOKEN_INVALID")
    if (not isinstance(tree_digest, str) or len(tree_digest) != 71
            or not tree_digest.startswith("sha256:")
            or any(character not in "0123456789abcdef" for character in tree_digest[7:])):
        raise CodexProductionTemplateError("CODEX_ARTIFACT_DIGEST_INVALID")
    if adapter_environment is not None and any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in adapter_environment.items()
    ):
        raise CodexProductionTemplateError("CODEX_ADAPTER_ENVIRONMENT_INVALID")
    if preferred_auth_method is not None and (
        not isinstance(preferred_auth_method, str) or not preferred_auth_method
    ):
        raise CodexProductionTemplateError("CODEX_PREFERRED_AUTH_METHOD_INVALID")
    mounts = runtime_artifact_mounts_override or ({
        "token": artifact_token, "target": ARTIFACT_TARGET, "treeDigest": tree_digest,
    },)
    declaration: dict[str, Any] = {
        "id": HARNESS_ID,
        "timeoutMs": timeout_ms,
        # 能力声明**派生**自注册表（`harnesses.toml`），不由本模板手写。
        "capabilityClaims": capability_claims(capabilities_for=capabilities_for),
        "credentialKind": CREDENTIAL_KIND,
        "credentialEnvironment": CREDENTIAL_ENVIRONMENT,
        "modelControlId": MODEL_CONTROL_ID,
        "controlOptions": {MODEL_CONTROL_ID: []},
        # Order 092: canonical protocols this family can speak -> native dialect value.
        "wireProtocols": {"openai-chat": "chat", "openai-responses": "responses"},
        # 生产默认选定的 ACP 认证方法：`chat-gpt` 需要磁盘登录态，本隔离里没有。
        "preferredAuthMethod": preferred_auth_method,
        "runtimeArtifactMounts": [dict(item) for item in mounts],
        "projectionFiles": [dict(item) for item in (
            projection_files_override
            if projection_files_override is not None else projection_files()
        )],
        # 用户裁决 A（2026-09-15）：`.tmp` 声明为 attempt-ephemeral——Codex 运行时把
        # 内置 plugin/skill 语料解包进 `$CODEX_HOME/.tmp/plugins/`（实测峰值 5,529 文件）。
        # 同日门内凭据路径诊断第一手定位：Codex 还会把 shell 快照（含全部环境导出，
        # 即注入的凭据环境变量原文）写进 `$CODEX_HOME/shell_snapshots/*.sh`。
        # bwrap 以 tmpfs 遮蔽这两个子路径：Harness 可写，但不进 view/state/checkpoint，
        # 尝试结束即消失。1024 列表上限与 fail-closed 凭据扫描保持不变。
        "stateProjection": {
            "target": STATE_TARGET,
            "ephemeralPaths": [".tmp", "shell_snapshots"],
        },
        "usageProbe": {"journalSuffix": ".jsonl", "format": "codex-rollout"},
        # §14: this family's session subtree is splittable from the rest
        # of its home, so it lives in the per-harness session store.
        "sessionStore": {"kind": "sessions-subtree"},
        # Order 56: the subscription login state is a managed account asset.
        # The path is first-hand (`$CODEX_HOME/auth.json`: 65 CODEX_HOME refs
        # and 4 auth.json refs in the pinned 0.147.0 binary), and the other
        # families are declared only once a real login run pins their file.
        "subscriptionCredential": {"files": [".codex/auth.json"]},
        "adapter": {
            "command": "/usr/bin/node",
            "args": [ADAPTER_ARTIFACT_ENTRY],
            # 环境只到达适配器进程；凭据以声明的环境变量在 guest 内注入，不写进任何
            # 文件或参数（`config.toml` 里的 `env_key` 只是那个变量的名字）。
            "environment": dict(
                ADAPTER_ENVIRONMENT if adapter_environment is None else adapter_environment),
        },
    }
    if preferred_auth_method is None:
        del declaration["preferredAuthMethod"]
    return declaration


def deployment_document(
    *, capabilities_for, artifact_token: str, tree_digest: str, **harness: Any,
) -> dict[str, Any]:
    """Server 加载的完整非秘密 deployment 文件。"""
    return {
        "schemaVersion": 1,
        "harnesses": [harness_deployment(
            artifact_token=artifact_token, tree_digest=tree_digest, capabilities_for=capabilities_for, **harness,
        )],
    }


def main(arguments: Sequence[str] | None = None, *, capabilities_for) -> int:
    """为一个已构建的工件输出生产部署文件。"""
    parser = argparse.ArgumentParser(description="Emit the Codex production deployment file.")
    parser.add_argument("--artifact-token", required=True,
                        help="mount token the deployment binds to the built Codex runtime artifact")
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
        "result": "CODEX_PRODUCTION_DEPLOYMENT_EMITTED",
        "out": str(output), "artifactTarget": ARTIFACT_TARGET,
        "productModelId": PRODUCT_MODEL_ID, "nativeModelId": NATIVE_MODEL_ID,
        "credentialEnvironment": CREDENTIAL_ENVIRONMENT,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":  # direct execution has no composing owner
    raise SystemExit("CODEX_CAPABILITY_SOURCE_REQUIRED: use an explicitly composed capability source")
