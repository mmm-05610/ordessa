"""OpenCode 生产部署模板（非秘密），由插件层唯一拥有。

这个模块拥有 OpenCode 部署里"属于这个 Harness"的部分：单文件二进制在 guest 的
固定挂载点、原生配置进入隔离 HOME 的位置、原生会话存储（SQLite）所在的 state
投影、凭据的环境变量名，以及驱动模块的声明。它只输出**通用字段**：Server、
Core、Worker 与 bwrap 只看到 `executableMounts` / `projectionFiles` /
`stateProjection` / `adapter`，任何一层都不认识 OpenCode。

与 Pi 一样，这里**不复制第二套漂移实现**：原生配置逐字节来自
`deployment/opencode.json`，而该文件等于 `scripts/server-round1/
model-validation-42d.mjs` 的 `openCodeModelConfig()`（模板测试用 `--family
opencode --dry-run` 逐字段比对）。里面没有任何秘密：API key 是环境引用
`{env:DEEPSEEK_API_KEY}`，由 Harness 在沙箱内解析 Worker 物化出来的凭据。

本阶段实测记录（详见 docs/server-round1/fullstack/opencode-production-packaging.md）：

* guest 布局是四家共用的那一套：唯一隔离 HOME 根 `/runtime/home` 下，只读配置
  `/runtime/home/.config/opencode/opencode.json`（= `$XDG_CONFIG_HOME/opencode/
  opencode.json`），唯一可写 state `/runtime/home/.local/share/opencode`
  （= `$XDG_DATA_HOME/opencode`，OpenCode 自己的默认数据目录）。两者**不同子树**，
  因此本家没有受保护的 state 路径：只读配置不可能被 state bind 遮蔽。
* `limit.output: 64` 真的进入 provider 请求体（假端点看到 `max_tokens=64`），
  因此不需要 42d 用过的 `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX`；后者的名字
  含 `TOKEN`，会被 Server/Core 的环境变量名规则拒绝，本模板不得声明它。
* 带标题创建会话时，一轮 prompt 恰好产生 **1** 次 provider 请求；不带标题时
  OpenCode 会为了生成标题多发一次请求，因此驱动始终随会话写入标题。
* 对可重试的 5xx，一次 prompt 实测最多产生 **6** 次 provider 尝试（受控实验，
  见门的 retry 观测）。42d 预备脚本里的 `maxProviderAttempts: 12` 没有证据，
  本阶段以实测值取代，并由门在真实链路中复核。
* 会话与消息持久化在 `$XDG_DATA_HOME/opencode/opencode.db`（SQLite，连同
  `-wal`/`-shm`），所以 state 投影目标就是 `$XDG_DATA_HOME` 下的 `opencode/`。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from ordessa_execution_agents.harness.definitions.harness_capabilities import CANONICAL_CAPABILITY_IDS

OPENCODE_PROVIDER = "deepseek"
#: 产品/ProviderModel 模型 id（用户确认过的那个），不得被静默改写。
PRODUCT_MODEL_ID = "deepseek-flash"
#: OpenCode 自己的模型目录地址形态（由 Harness 扩展层翻译）。
NATIVE_MODEL_VALUE = f"{OPENCODE_PROVIDER}/{PRODUCT_MODEL_ID}"
OFFICIAL_BASE_URL = "https://api.deepseek.com"
CREDENTIAL_KIND = "api-key"
CREDENTIAL_ENVIRONMENT = "DEEPSEEK_API_KEY"
OUTPUT_TOKEN_LIMIT = 64
#: 本阶段授权的单文件二进制版本（由 build-opencode-authorization.mjs 取证）。
OPENCODE_VERSION = "1.18.21"

#: 固定 guest 挂载点：Worker 校验摘要后只读挂载单文件，bwrap 模板只允许
#: `/runtime/bin/<name>` 这一种目标形态。
BINARY_NAME = "opencode"
BINARY_TARGET = f"/runtime/bin/{BINARY_NAME}"
#: 生产 argv：直接执行挂载好的二进制（不加壳、不加解释器）。
BINARY_ARGV: tuple[str, ...] = ()

#: 隔离 HOME 下的原生配置与原生数据目录（state 投影）。两者都由 guest 环境里
#: 那一个 HOME/XDG 根派生：`OPENCODE_CONFIG` 指向只读配置的**确切路径**，
#: 而 state 投影目标正是 `$XDG_DATA_HOME/opencode`，即 OpenCode 自己的默认
#: 数据目录——显式声明与默认解析收敛到同一目录，不可能分裂成两个 home。
#: guest 环境给出的两个 XDG 根（`sidecar.GUEST_HOME` 派生），这里的常量只是把
#: 同一份事实写下来，供模板测试断言"默认路径 == 显式目标"。
GUEST_HOME = "/runtime/home"
XDG_CONFIG_HOME = f"{GUEST_HOME}/.config"
XDG_DATA_HOME = f"{GUEST_HOME}/.local/share"
CONFIG_TARGET = f"{XDG_CONFIG_HOME}/opencode/opencode.json"
STATE_TARGET = f"{XDG_DATA_HOME}/opencode"

#: 生产 adapter 环境。每一项都有明确理由：
#: * `OPENCODE_CONFIG` 指向只读投影进来的原生配置（避免读 guest 里的用户目录），
#:   该路径同时等于 `$XDG_CONFIG_HOME/opencode/opencode.json`（guest 环境已给出
#:   XDG 变量），因此显式变量与默认路径同一文件；
#: * 三个 DISABLE_* 关闭自动更新、模型目录下载与 LSP 下载，使一次运行只与
#:   provider 端点通信（42d 预备运行同样设置）。
#: **不声明 XDG_DATA_HOME**：guest 环境已给出 `/runtime/home/.local/share`，
#: 声明它只会制造第二处真相；state 目标就是它下面的 `opencode/`。
#: 依赖环境变量名里**不得**出现 TOKEN/SECRET/KEY/PASSWORD/CREDENTIAL/AUTH，
#: 因此这里没有 `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX`（输出上限由配置的
#: `limit.output` 承载，已实测进入请求体）。
ADAPTER_ENVIRONMENT = {
    "OPENCODE_CONFIG": CONFIG_TARGET,
    "OPENCODE_DISABLE_AUTOUPDATE": "1",
    "OPENCODE_DISABLE_MODELS_FETCH": "1",
    "OPENCODE_DISABLE_LSP_DOWNLOAD": "1",
}

#: 驱动模块：随 deployment 进入评审过的 bundle，sidecar 只从同一 bundle 的
#: `deployment/` 目录加载它（Server/Core/Worker 只搬运声明，不认识内容）。
DRIVER_SOURCE = "runtime/drivers/opencode-native.mjs"

#: 产品模型控件：模型是 Provider/Model 引用，控件不给默认值。
MODEL_CONTROL_ID = "model"

#: 一轮 prompt 的 provider 请求预算：带标题的会话恰好 1 次（实测）。
PROVIDER_REQUESTS_PER_PROMPT = 1
#: 对可重试失败，一次 prompt 的 provider 尝试上界（受控实验实测 6 次）。
MEASURED_RETRY_ATTEMPTS = 6

TOKEN = re.compile(r"[a-z][a-z0-9-]{0,31}")

DEPLOY_DIRECTORY = Path(__file__).resolve().parent / "deployment"
CONFIG_TEMPLATE = DEPLOY_DIRECTORY / "opencode.json"
DRIVER_TEMPLATE = Path(__file__).resolve().parent / "acp" / "opencode_native.mjs"
#: 仅供不得访问真实网络的门的离线资产：预载到 opencode 进程的 loopback 守护。
#: 生产部署**从不**引用它（模板测试断言生产默认里没有 LD_PRELOAD / 审计路径）。
EGRESS_GUARD = DEPLOY_DIRECTORY / "egress-guard.c"

CONFIG_SOURCE = "deploy/opencode/opencode.json"


class OpenCodeProductionTemplateError(ValueError):
    """本模板拒绝输出的部署声明。"""


def capability_claims(*, capabilities_for) -> dict[str, bool]:
    """本模板部署时声明的 canonical 能力（派生自注册表，不手写）。

    `native_continuation` 是**已观测**项：门的重开相位 `createsInsideReopenPhase=[]`
    且 native session id 不变。`attach` 不声明：驱动在发包前以
    `OPENCODE_ATTACHMENTS_UNSUPPORTED` 显式拒绝附件，原生 `promptCapabilities.image`
    也是 false。`permissions` 无任何运行时证据。
    """
    if not callable(capabilities_for):
        raise OpenCodeProductionTemplateError("OPENCODE_CAPABILITY_SOURCE_REQUIRED")
    claims = capabilities_for("opencode")
    if (not isinstance(claims, Mapping) or set(claims) != set(CANONICAL_CAPABILITY_IDS)
            or any(type(claims[key]) is not bool for key in CANONICAL_CAPABILITY_IDS)):
        raise OpenCodeProductionTemplateError("OPENCODE_CAPABILITY_CLAIMS_INVALID")
    return {key: claims[key] for key in CANONICAL_CAPABILITY_IDS}


def config_document() -> dict[str, Any]:
    """签入的原生配置（官方根地址，无秘密）。"""
    return json.loads(CONFIG_TEMPLATE.read_text(encoding="utf-8"))


def loopback_config_document(base_url: str) -> dict[str, Any]:
    """只替换 `baseURL` 的副本：把生产配置指向本机假端点。"""
    if not isinstance(base_url, str) or not base_url.startswith("http://127.0.0.1:"):
        raise OpenCodeProductionTemplateError("OPENCODE_LOOPBACK_BASE_URL_INVALID")
    document = config_document()
    document["provider"][OPENCODE_PROVIDER]["options"]["baseURL"] = base_url
    return document


def documented_differences(base_url: str) -> dict[str, tuple[Any, Any]]:
    """loopback 覆盖到底改了哪些字段，用于审计"只改了一处"。"""
    production = config_document()
    override = loopback_config_document(base_url)
    changed: dict[str, tuple[Any, Any]] = {}
    for provider_id, provider in production["provider"].items():
        other = override["provider"][provider_id]
        for key in sorted(set(provider) | set(other)):
            if provider.get(key) != other.get(key):
                changed[f"provider.{provider_id}.{key}"] = (provider.get(key), other.get(key))
    return changed


def model_aliases() -> dict[str, str]:
    """产品模型 id -> 原生目录值；与 own public ACP profile declarations 必须一致。"""
    return {PRODUCT_MODEL_ID: NATIVE_MODEL_VALUE}


def native_model(model: object) -> object:
    """翻译一个产品模型 id；其它值原样透传（未知模型由驱动在发包前拒绝）。"""
    if not isinstance(model, str):
        return model
    return model_aliases().get(model, model)


def projection_files() -> tuple[dict[str, str], ...]:
    """只读进入隔离 HOME 的原生配置。"""
    return ({"source": CONFIG_SOURCE, "target": CONFIG_TARGET},)


def executable_mount(binary_token: str, digest: str) -> dict[str, str]:
    """单文件二进制的可执行挂载声明（摘要由授权工具取证）。

    声明里给的是**令牌**：这台机器上这个二进制在哪，由加载部署的人绑定，
    不写进文档——同一份文档因此可以在本机、WSL 或远端使用。
    """
    if (not isinstance(binary_token, str) or TOKEN.fullmatch(binary_token) is None):
        raise OpenCodeProductionTemplateError("OPENCODE_BINARY_TOKEN_INVALID")
    if (not isinstance(digest, str) or len(digest) != 71 or not digest.startswith("sha256:")
            or any(character not in "0123456789abcdef" for character in digest[7:])):
        raise OpenCodeProductionTemplateError("OPENCODE_BINARY_DIGEST_INVALID")
    return {"token": binary_token, "target": BINARY_TARGET, "digest": digest}


def validated_mounts(override: Sequence[Mapping[str, str]]) -> tuple[dict[str, str], ...]:
    """调用方给出的挂载覆盖必须与模板自己产生的形状完全一致。"""
    mounts = []
    for item in override:
        if not isinstance(item, Mapping) or set(item) != {"token", "target", "digest"}:
            raise OpenCodeProductionTemplateError("OPENCODE_EXECUTABLE_MOUNT_INVALID")
        if item["target"] != BINARY_TARGET:
            raise OpenCodeProductionTemplateError("OPENCODE_EXECUTABLE_MOUNT_INVALID")
        mounts.append(executable_mount(item["source"], item["digest"]))
    return tuple(mounts)


def harness_deployment(
    *, capabilities_for,
    binary_token: str,
    binary_digest: str,
    timeout_ms: int = 120_000,
    adapter_environment: Mapping[str, str] | None = None,
    projection_files_override: Sequence[Mapping[str, str]] | None = None,
    executable_mounts_override: Sequence[Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """一条生产 Harness 声明，可直接写进非秘密 deployment 文件。"""
    if adapter_environment is not None and any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in adapter_environment.items()
    ):
        raise OpenCodeProductionTemplateError("OPENCODE_ADAPTER_ENVIRONMENT_INVALID")
    mounts = (validated_mounts(executable_mounts_override) if executable_mounts_override is not None
              else (executable_mount(binary_token, binary_digest),))
    return {
        "id": "opencode",
        "timeoutMs": timeout_ms,
        # 能力声明**派生**自注册表（`harnesses.toml`），不由本模板手写：see
        # `registry.capability_claims`。该表里 opencode 已包含 `native_continuation`
        # （门的重开相位 `createsInsideReopenPhase=[]` + 同一 native session id），
        # 并且**不**包含 `attach`（驱动显式拒绝附件）与 `permissions`。
        "capabilityClaims": capability_claims(capabilities_for=capabilities_for),
        "credentialKind": CREDENTIAL_KIND,
        "credentialEnvironment": CREDENTIAL_ENVIRONMENT,
        "modelControlId": MODEL_CONTROL_ID,
        "controlOptions": {MODEL_CONTROL_ID: []},
        # Order 092: canonical protocols this family can speak -> native dialect value.
        "wireProtocols": {"openai-chat": "@ai-sdk/openai-compatible"},
        "executableMounts": [dict(item) for item in mounts],
        "projectionFiles": [dict(item) for item in (
            projection_files_override
            if projection_files_override is not None else projection_files()
        )],
        "stateProjection": {"target": STATE_TARGET},
        # Order 66: the family library owns the live session database and the
        # revert/diff snapshots; log/, repos/ and auth.json stay in the
        # profile home (auth.json is a credential carrier and is never shared).
        "sessionStore": {
            "kind": "whole-db",
            "shared": [
                       {"name": "opencode.db", "kind": "file"},
                       {"name": "opencode.db-wal", "kind": "file"},
                       {"name": "opencode.db-shm", "kind": "file"},
                       {"name": "snapshot", "kind": "directory"},
                   ],
        },
        "adapter": {
            "command": BINARY_TARGET,
            "args": list(BINARY_ARGV),
            # 环境只到达 Harness 的原生进程；凭据以声明的环境变量在 guest 内注入，
            # 不写进任何文件或参数。
            "environment": dict(
                ADAPTER_ENVIRONMENT if adapter_environment is None else adapter_environment),
            "driver": {"source": DRIVER_SOURCE},
        },
    }


def deployment_document(
    *, capabilities_for, binary_token: str, binary_digest: str, **harness: Any,
) -> dict[str, Any]:
    """Server 加载的完整非秘密 deployment 文件。"""
    return {
        "schemaVersion": 1,
        "harnesses": [harness_deployment(
            binary_token=binary_token, binary_digest=binary_digest, capabilities_for=capabilities_for, **harness,
        )],
    }


def main(arguments: Sequence[str] | None = None, *, capabilities_for) -> int:
    """为一个已授权的二进制输出生产部署文件。"""
    parser = argparse.ArgumentParser(description="Emit the OpenCode production deployment file.")
    parser.add_argument("--binary-token", required=True,
                        help="canonical path of the authorized single-file binary")
    parser.add_argument("--binary-digest", required=True, help="its full sha256: digest")
    parser.add_argument("--out", required=True, help="path of the deployment file to write")
    parser.add_argument("--timeout-ms", type=int, default=120_000)
    options = parser.parse_args(arguments)
    document = deployment_document(
        binary_token=options.binary_token, binary_digest=options.binary_digest,
        timeout_ms=options.timeout_ms, capabilities_for=capabilities_for,
    )
    output = Path(options.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "OPENCODE_PRODUCTION_DEPLOYMENT_EMITTED",
        "out": str(output), "binaryTarget": BINARY_TARGET,
        "productModelId": PRODUCT_MODEL_ID, "nativeModelValue": NATIVE_MODEL_VALUE,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":  # direct execution has no composing owner
    raise SystemExit("OPENCODE_CAPABILITY_SOURCE_REQUIRED: use an explicitly composed capability source")
