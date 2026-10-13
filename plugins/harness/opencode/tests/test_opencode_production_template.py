"""OpenCode 生产模板门。

模板只有在**与 42-D 预备配置逐字段相同**、且各层不该知道的东西都不在里面时才算
可信。这里断言两件事：配置等值（用 `model-validation-42d.mjs --dry-run` 的真实
输出比对），以及生产默认里没有 gate-only 的守卫/审计环境变量、没有凭据材料、
环境变量名不违反 Server/Core 的规则。驱动模块的通用契约与拒绝路径另有专门的
node 探针测试。
"""
from __future__ import annotations
import os

import json
from pathlib import Path
import subprocess
import sys

import pytest

from ordessa_harness_opencode import production


REPO = Path(__file__).resolve().parents[4]
RUNTIME = REPO / "plugins" / "harness" / "runtime"
DRIVER = production.DRIVER_TEMPLATE
#: Server/Core 在 deployment 环境变量名上执行的拒绝规则（与 runtime.py 一致）。
FORBIDDEN_ENVIRONMENT = ("TOKEN", "SECRET", "KEY", "PASSWORD", "CREDENTIAL", "AUTH")


from functools import partial
from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog
from ordessa_execution_agents.harness.providers.declarations.capability_claims import capability_claims

_captured_harness_catalog = capture_selected_harness_catalog()
registry_capabilities = partial(capability_claims, _captured_harness_catalog.registry)

def as_json(value):
    """JSON 归一化比较：键序与格式不是身份。"""
    return json.loads(json.dumps(value, sort_keys=True))


def test_native_configuration_is_the_prepared_42d_configuration(tmp_path):
    """签入的原生配置必须等于 42-D 预备的 OpenCode 配置。

    `model-validation-42d.mjs` 是 42-D 预备配置的地方；把一份手写的第二实现抄进
    插件，正是生产部署与被接受的预备方案漂移的方式。这里用测试自建的 0600 假
    token 跑 `--family opencode --dry-run` 并要求逐字段相等。
    """
    token = tmp_path / "not-a-real-token"
    token.write_bytes(b"opencode-template-test-token")
    token.chmod(0o600)
    result = subprocess.run(
        ["node", str(Path(__file__).resolve().parents[4] / "tooling/checks/harness/model_validation_42d.mjs"),
         "--family", "opencode", "--secret-file", str(token), "--dry-run"],
        capture_output=True, env={**os.environ, "ORDESSA_TEST_PYTHON": sys.executable}, text=True, timeout=180, cwd=str(REPO),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    prepared = json.loads(result.stdout.strip().splitlines()[-1])
    assert prepared["outcome"] == "PREPARED"
    assert prepared["version"] == "opencode-ai@1.18.21"
    assert as_json(prepared["config"]) == as_json(production.config_document())
    # 42-D 预备脚本里那个没有证据的 maxProviderAttempts=12 不是本模板的声明：
    # 本阶段用受控实验实测（一次 prompt 最多 6 次尝试，见门与证据文档）。
    assert prepared["maxProviderAttempts"] == 12
    assert production.MEASURED_RETRY_ATTEMPTS == 6
    assert production.PROVIDER_REQUESTS_PER_PROMPT == 1
    # 模板引用环境变量且不携带任何材料。
    assert "opencode-template-test-token" not in json.dumps(production.config_document())
    assert "{env:DEEPSEEK_API_KEY}" in json.dumps(production.config_document())


def test_production_template_pins_the_confirmed_model_and_official_root():
    config = production.config_document()
    provider = config["provider"][production.OPENCODE_PROVIDER]
    assert production.PRODUCT_MODEL_ID == "deepseek-flash"
    assert production.NATIVE_MODEL_VALUE == "deepseek/deepseek-flash"
    assert provider["options"]["baseURL"] == production.OFFICIAL_BASE_URL == "https://api.deepseek.com"
    assert provider["npm"] == "@ai-sdk/openai-compatible"
    assert provider["name"] == "DeepSeek official"
    assert provider["options"]["apiKey"] == "{env:DEEPSEEK_API_KEY}"
    model = provider["models"][production.PRODUCT_MODEL_ID]
    assert model["reasoning"] is False
    assert model["options"]["thinking"] == {"type": "disabled"}
    assert model["limit"]["output"] == production.OUTPUT_TOKEN_LIMIT == 64
    assert model["limit"]["context"] == 1000000
    assert config["$schema"] == "https://opencode.ai/config.json"


def test_loopback_override_changes_only_the_base_url():
    override = production.loopback_config_document("http://127.0.0.1:8080")
    differences = production.documented_differences("http://127.0.0.1:8080")
    assert list(differences) == [f"provider.{production.OPENCODE_PROVIDER}.options"]
    assert differences[f"provider.{production.OPENCODE_PROVIDER}.options"] == (
        production.config_document()["provider"][production.OPENCODE_PROVIDER]["options"],
        override["provider"][production.OPENCODE_PROVIDER]["options"],
    )
    assert override["provider"][production.OPENCODE_PROVIDER]["options"]["baseURL"] == "http://127.0.0.1:8080"
    # 只改了 baseURL 一个字段；模型条目与原配置逐字段相同。
    assert override["provider"][production.OPENCODE_PROVIDER]["models"] == (
        production.config_document()["provider"][production.OPENCODE_PROVIDER]["models"])
    assert production.config_document()["provider"][production.OPENCODE_PROVIDER]["options"]["baseURL"] == (
        production.OFFICIAL_BASE_URL)


def test_loopback_override_refuses_anything_but_a_loopback_url():
    for value in ("https://api.deepseek.com", "http://0.0.0.0:1", "http://192.168.0.1:1", "", None):
        with pytest.raises(production.OpenCodeProductionTemplateError):
            production.loopback_config_document(value)


def test_deployment_document_declares_the_managed_chain():
    document = production.deployment_document(
        binary_token="binary",
        binary_digest="sha256:" + "a" * 64,
     capabilities_for=registry_capabilities)
    assert document["schemaVersion"] == 1
    # The document names no host path at all: the plugin root and every mount
    # token are the loader's business, not the file's.
    assert "pluginRoot" not in document
    harness = document["harnesses"][0]
    assert harness["id"] == "opencode"
    assert harness["credentialKind"] == "api-key"
    assert harness["credentialEnvironment"] == "DEEPSEEK_API_KEY"
    assert harness["modelControlId"] == production.MODEL_CONTROL_ID
    assert harness["controlOptions"] == {production.MODEL_CONTROL_ID: []}
    # 单文件二进制只经 executableMounts 通道；摘要必须与授权工具取证的一致。
    assert harness["executableMounts"] == [{
        "token": "binary",
        "target": "/runtime/bin/opencode",
        "digest": "sha256:" + "a" * 64,
    }]
    assert "runtimeArtifactMounts" not in harness
    # 原生会话存储 = 驱动进程的默认数据目录 = state 投影目标。两者由同一个
    # `$XDG_DATA_HOME` 派生，模板**不**再自行声明 XDG_DATA_HOME：guest 环境
    # 给出的那个根是唯一真相，多声明一份只会制造第二处可漂移的事实。
    assert harness["stateProjection"] == {"target": production.STATE_TARGET}
    assert production.STATE_TARGET == f"{production.XDG_DATA_HOME}/opencode"
    assert "XDG_DATA_HOME" not in production.ADAPTER_ENVIRONMENT
    assert harness["projectionFiles"] == [
        {"source": "deploy/opencode/opencode.json", "target": production.CONFIG_TARGET}]
    assert production.ADAPTER_ENVIRONMENT["OPENCODE_CONFIG"] == production.CONFIG_TARGET
    assert production.CONFIG_TARGET == f"{production.XDG_CONFIG_HOME}/opencode/opencode.json"
    # 配置与 state 在**不同**子树里：不存在需要保护的 state 路径，也就不可能有
    # 只读配置被 state bind 遮蔽的情形。
    assert not production.CONFIG_TARGET.startswith(production.STATE_TARGET + "/")
    assert not production.STATE_TARGET.startswith(production.CONFIG_TARGET + "/")
    assert production.CONFIG_TARGET != production.STATE_TARGET
    assert production.GUEST_HOME == "/runtime/home"
    adapter = harness["adapter"]
    assert adapter["command"] == "/runtime/bin/opencode"
    assert adapter["args"] == []
    assert adapter["driver"] == {"source": "runtime/drivers/opencode-native.mjs"}
    assert adapter["environment"] == production.ADAPTER_ENVIRONMENT
    # 生产默认里不得出现 gate-only 的守卫、审计路径，也不得有凭据材料。
    rendered = json.dumps(adapter["environment"])
    for forbidden in ("LD_PRELOAD", "AGENTBOX_EGRESS_AUDIT", "AGENTBOX_DRIVER_AUDIT", "NODE_OPTIONS"):
        assert forbidden not in rendered, forbidden
    assert "DEEPSEEK_API_KEY" not in rendered
    assert "sk-" not in rendered
    # 环境变量名必须通过 Server/Core 的规则：不得含 TOKEN/SECRET/KEY/...
    for key in adapter["environment"]:
        assert not any(word in key.upper() for word in FORBIDDEN_ENVIRONMENT), key
    # 驱动模块只由 deployment 声明携带，Server 会把它的字节放进评审过的 bundle。
    assert production.DRIVER_TEMPLATE.is_file()
    assert not (Path(production.__file__).resolve().parents[3] / production.DRIVER_SOURCE).exists()


def test_deployment_document_refuses_invalid_binary_declarations():
    # A token is a name, never a path, and the digest has to be a full sha256:
    # each of these is refused by the template rather than written into a
    # document that could not be bound on any machine.
    for token, digest in (("relative/path", "sha256:" + "a" * 64),
                          ("/srv/artifact", "sha256:" + "a" * 64),
                          ("Artifact", "sha256:" + "a" * 64),
                          ("a" * 33, "sha256:" + "a" * 64),
                          ("artifact", "sha256:short"),
                          ("artifact", "md5:" + "a" * 32)):
        with pytest.raises(production.OpenCodeProductionTemplateError):
            production.deployment_document(binary_token=token, binary_digest=digest, capabilities_for=registry_capabilities)


def test_projection_sources_exist_next_to_the_deployment_template():
    for projection in production.projection_files():
        assert (production.DEPLOY_DIRECTORY / projection["source"].rsplit("/", 1)[-1]).is_file()
        assert projection["target"].startswith(f"{production.GUEST_HOME}/")
        assert projection["target"] == production.CONFIG_TARGET
    assert production.DRIVER_TEMPLATE.is_file()
    # 离线守卫是门资产，不是生产配置。
    assert production.EGRESS_GUARD.is_file()
    assert "egress-guard" not in json.dumps(production.deployment_document(
        binary_token="binary", binary_digest="sha256:" + "a" * 64, capabilities_for=registry_capabilities))


def test_product_model_translates_to_the_native_catalogue_value():
    assert production.native_model("deepseek-flash") == "deepseek/deepseek-flash"
    assert production.native_model("something-else") == "something-else"
    assert production.native_model(None) is None


def test_the_sidecar_glue_owns_the_same_model_mapping():
    """别名只能有一处定义，且两处不得分歧（Python 模板 vs Node 扩展层）。"""
    script = (
        "import('" + (Path(__file__).resolve().parents[4] / 'apps/server/tests/support/profile_claims.mjs').as_uri() + "').then((module) =>"
        " process.stdout.write(JSON.stringify({"
        " aliases: module.AGENTBOX_MODEL_ALIASES,"
        " translated: module.resolveNativeModel('opencode', 'deepseek-flash'),"
        " passthrough: module.resolveNativeModel('opencode', 'deepseek-unknown'),"
        " empty: module.resolveNativeModel('opencode', undefined) ?? null })))"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, env={**os.environ, "ORDESSA_TEST_PYTHON": sys.executable}, text=True,
                            timeout=60, cwd=str(REPO))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["aliases"]["opencode"] == production.model_aliases()
    assert payload["translated"] == production.NATIVE_MODEL_VALUE
    assert payload["passthrough"] == "deepseek-unknown"
    assert payload["empty"] is None


def test_the_driver_module_keeps_the_generic_contract(tmp_path):
    """驱动的机器可读契约：入口、事件名、模型形态、审计钩子、拒绝路径。

    用 stub fetch 直接驱动模块（不启动真实进程），断言：
      * `create` 在未知模型上**先拒绝**、不发任何 provider/SESSION 请求；
      * `open` 对不存在的会话失败，且**从不**新建会话；
      * 附件被显式拒绝，而不是静默丢弃；
      * 增量事件名是接缝的 `message_delta`；
      * 审计钩子只接受位于工作目录内的绝对路径。
    """
    probe = tmp_path / "opencode_driver_probe.mjs"
    probe.write_text(
        "import { createDriver, splitNativeModel, catalogHasModel, auditPathFor, withPure, textOfParts, tailSuffix }\n"
        f"  from {json.dumps(DRIVER.as_uri())}\n"
        "const calls = []\n"
        "globalThis.fetch = async (url, options = {}) => {\n"
        "  calls.push([options.method ?? 'GET', String(url).replace(/^http:\\/\\/127\\.0\\.0\\.1:\\d+/, '')])\n"
        "  const body = options.body ? JSON.parse(options.body) : null\n"
        "  const respond = (status, payload) => ({ status, ok: status < 300,\n"
        "    text: async () => JSON.stringify(payload) })\n"
        "  if (String(url).endsWith('/config/providers')) return respond(200, { providers: [\n"
        "    { id: 'deepseek', models: { 'deepseek-flash': { id: 'deepseek-flash' } } }] })\n"
        "  if (String(url).includes('/session/') && String(url).endsWith('/message')) return respond(200, {\n"
        "    info: { id: 'msg_1' }, parts: [{ type: 'text', text: 'fallback text' }] })\n"
        "  if (String(url).endsWith('/session')) return respond(200, { id: 'ses_new', title: body?.title })\n"
        "  if (String(url).includes('/session/ses_missing')) return respond(404, {})\n"
        "  if (String(url).includes('/session/')) return respond(200, { id: 'ses_stored', title: 'stored' })\n"
        "  return respond(200, {})\n"
        "}\n"
        "const emitted = []\n"
        "const driver = await createDriver({\n"
        "  profileID: 'opencode', command: '/runtime/bin/opencode', args: [],\n"
        "  environment: { AGENTBOX_DRIVER_AUDIT: '/workspace/audit' },\n"
        "  credentialEnvironment: 'DEEPSEEK_API_KEY', hasCredential: true,\n"
        "  directory: '/workspace', stateDirectory: '/tmp/agentbox-sidecar-state',\n"
        "  emit: (message) => emitted.push(message),\n"
        "  redact: (value, maximum) => String(value ?? '').slice(0, maximum),\n"
        "  spawnProcess: () => { throw new Error('the unit probe must not spawn') },\n"
        "})\n"
        "const report = { capabilities: driver.capabilities, helpers: {\n"
        "  split: splitNativeModel('deepseek/deepseek-flash'),\n"
        "  catalog: catalogHasModel({ providers: [{ id: 'deepseek', models: { 'deepseek-flash': {} } }] },\n"
        "    'deepseek', 'deepseek-flash'),\n"
        "  catalogMissing: catalogHasModel({ providers: [{ id: 'deepseek', models: {} }] }, 'deepseek', 'x'),\n"
        "  auditInside: auditPathFor({ AGENTBOX_DRIVER_AUDIT: '/workspace/a' }, '/workspace'),\n"
        "  auditOutside: auditPathFor({ AGENTBOX_DRIVER_AUDIT: '/etc/passwd' }, '/workspace'),\n"
        "  auditRelative: auditPathFor({ AGENTBOX_DRIVER_AUDIT: 'a' }, '/workspace'),\n"
        "  pure: withPure(['serve', '--hostname', 'h', '--port', '1']),\n"
        "  text: textOfParts([{ type: 'text', text: 'a' }, { type: 'reasoning', text: 'b' }]),\n"
        "  tail: [tailSuffix('ab', 'abcd'), tailSuffix('abcd', 'abcd'),\n"
        "    tailSuffix('ab', 'axcd'), tailSuffix('ab', null)],\n"
        "} }\n"
        "const created = await driver.create({ title: 'execution-1', model: 'deepseek/deepseek-flash' })\n"
        "report.created = created\n"
        "let unknownModel = null\n"
        "try { await driver.create({ title: 'x', model: 'deepseek-unknown' }) }\n"
        "catch (error) { unknownModel = { code: error.code, message: error.message } }\n"
        "report.unknownModel = unknownModel\n"
        "const afterUnknown = calls.length\n"
        "let missing = null\n"
        "try { await driver.open({ sessionId: 'ses_missing' }) }\n"
        "catch (error) { missing = { code: error.code, message: error.message } }\n"
        "report.missing = missing\n"
        "const stored = await driver.open({ sessionId: 'ses_stored' })\n"
        "report.stored = stored\n"
        "const prompted = await driver.prompt({ sessionId: 'ses_new', text: 'hello',\n"
        "  model: 'deepseek/deepseek-flash' })\n"
        "report.prompted = prompted\n"
        "let attachments = null\n"
        "try { await driver.prompt({ sessionId: 'ses_new', text: 'x', model: 'deepseek/deepseek-flash',\n"
        "  attachments: [{ type: 'file' }] }) }\n"
        "catch (error) { attachments = error.code }\n"
        "report.attachments = attachments\n"
        "report.calls = calls\n"
        "report.afterUnknownCalls = afterUnknown\n"
        "report.emitted = emitted\n"
        "process.stdout.write(JSON.stringify(report))\n",
        encoding="utf-8",
    )
    result = subprocess.run(["node", str(probe)], capture_output=True, env={**os.environ, "ORDESSA_TEST_PYTHON": sys.executable}, text=True, timeout=120,
                            cwd=str(tmp_path))
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["capabilities"]["sessionCapabilities"] == {"resume": {}, "list": {}}
    assert report["capabilities"]["promptCapabilities"] == {"image": False}
    assert report["helpers"]["split"] == {"providerID": "deepseek", "modelID": "deepseek-flash"}
    assert report["helpers"]["catalog"] is True
    assert report["helpers"]["catalogMissing"] is False
    assert report["helpers"]["auditInside"] == "/workspace/a"
    assert report["helpers"]["auditOutside"] is None
    assert report["helpers"]["auditRelative"] is None
    assert report["helpers"]["pure"][:2] == ["serve", "--pure"]
    assert report["helpers"]["text"] == "a"
    # 尾部校准规则：记录里可能多出流没送达的后缀（补），其余一律不猜。
    assert report["helpers"]["tail"] == ["cd", None, None, None]
    assert report["created"]["sessionId"] == "ses_new"
    assert report["missing"]["code"] == "OPENCODE_SESSION_NOT_FOUND"
    # 不存在的会话绝不能被静默新建：探针里没有任何 POST /session 发生在这之后。
    create_calls = [call for call in report["calls"] if call[0] == "POST" and call[1].endswith("/session")]
    assert len(create_calls) == 1, report["calls"]
    assert report["stored"] == {"sessionId": "ses_stored"}
    assert report["prompted"]["done"] is True
    assert report["attachments"] == "OPENCODE_ATTACHMENTS_UNSUPPORTED"
    # 未知模型在发出任何请求之前被拒绝（除了读取原生目录的那一次 GET）。
    assert report["unknownModel"]["code"] == "OPENCODE_MODEL_NOT_AVAILABLE"
    assert "deepseek-unknown" in report["unknownModel"]["message"]
    # 每一轮的真实文本都以接缝事件上报（这里是兜底路径：没有 SSE 订阅）。
    assert [item["event"] for item in report["emitted"]] == ["message_delta"]
    assert report["emitted"][0]["data"]["text"] == "fallback text"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
