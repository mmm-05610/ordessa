# AU003 Pi纯模型配置能力迁移

基线 `65e409534505d5701d87a84d58c6138671bdd5d9`，clean。上一轮Codex与Pi反例检查点属于progress；本轮主会话独占共享源码/测试/Git/账本，代理只读审阅，不存在第二共享写者。合同只读，三家成果保留，不扩张新核心或授权协议。

## 迁移与复用

旧 `ordessa_harness/pi/configuration/model.py` 纯compiler物理迁到独立 `ordessa_harness_pi/acp_model_configuration.py`，旧文件删除无shim；DTO/parser复用既有 `ordessa_harness_api.model_compilation`。初compiler class/function AST相等、初renderer原函数体相等；最终compiler有明确安全修补，`pi-model-migration-source.json`分开记录初AST与final SHA，不称最终零语义变更。

独立acp_model_facts持有Pi dialect、历史ACP >=0.5.0 <0.6、models/settings targets、maxTokens、renderer；oldcommon/pi.native/native_materialization/bridge全部消费独立owner。native_materialization wrapper保留原protocol validation和异常表面，renderer函数体原样，普通golden无变化。原registration metadata/持久IDs不改。独立Pi新增既有API依赖，旧Harness显式依赖own Pi，以消费纯编译；独立包无旧Harness/Server/product导入。

consumer搜索只剩ownership gate中断言旧路径不存在，原pure/conformance/request params导入改新owner；bridge只允许确切三家独立compiler imports，不宽放私有包。原missing host-issued settings target测试补明确provider-add endpoint，保留原typed refusal和“has not issued”断言；原helper的Pi provider presence为显式受控观察，不在生产假设missing=false。

## 正向能力和安全修补

保留已有provider的model session-local、新provider routing/SecretRef、预算从native sample重写且保siblings/metadata/原值、retry闭合block和host-issued pi.settings.json target、同Session restart-resume计划。

修复三个已实测原漏洞：retry-only与credential-only不再覆盖provider subtree；全部restart计划保desired session model；缺model/session不再None相等误match。其他新增反例修typed provider/change flags、instance/family/target/model/ref/endpoint、missing provider观察、direct DTO malformed budget/retry、预算重复desired id拒绝。endpoint-only基于原provider sample修改routing并保models，无sample拒绝；预算未提供endpoint时只能复用原观察，有两者皆无则拒绝。

原预算直接复制provider样本可能携带native inline apiKey/headers。现在 `safe_provider_sample` 对原Pi apiKey仅保既有 `$ENV_NAME` 引用，非空headers拒绝，不在Refusal写secret内容。它依赖owner给真实native sample，不是通用任意对象脱敏器；未在这里扩张SecretRef解析或新native凭据协议。凭据应用仍需production credential owner。

verify match仅model/same-session样本；无native readback/ACK-only unknown，foreign/new Session mismatch。不能据此将provider routing、credential、预算、retry整份配置标applied。resume expectation仍纯计划，不证明真实恢复；历史ACP0.5 fixture与当前RPC source pin `13cbf77df2396303013a41646bcfa77b4271ae56`是独立版本轴。默认provider methods/schema未扩大，安装后缺生产ports仍不支持start/apply。

## 实际命令与结果

`PY=/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`。
源码环境：`PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:plugins/harness/api/src:packages/backend/harness-transport/src`；初new tests仅Pi/API两个source。

| 场景/命令 | 实际退出码、数量、耗时 |
| --- | --- |
| `$PY -m pytest plugins/harness/pi/tests/test_acp_model_configuration.py -q --tb=short` 初迁30反例 | exit1、1P29F、0.21s |
| new30＋原conformance/request params/API/family | exit0、129P＋37subtests、0.47s |
| missing observation/direct DTO/endpoint扩至43 | exit1、39P4F、0.15s |
| 二审routing/secret反例扩至48 | exit1、40P8F、0.16s |
| 全修new48＋原pure/API/family/ownership初 | exit1、159P1F＋37subtests、0.56s，原host-issued settings target测试provider-add endpoint缺席抢先拒绝 |
| fixture补明确endpoint，原断言保持，同组合 | exit0、160P＋37subtests、0.63s、0skip |
| `$PY -m pytest plugins/harness/pi/tests -q --tb=short` 初fresh | exit0、262P、8.67s，fresh five own wheel与pipcheck |
| fresh安装正控再补budget/retry，末端全Pi同命令 | exit0、262P、8.58s、0skip |
| `$PY -m pytest apps/server/tests/test_native_materialization_093.py plugins/harness/tests/test_family_dialect_tables.py plugins/harness/tests/test_agent_unit_source_ownership.py -q --tb=short` | exit0、57P、0.46s、0skip；native materialization pure gate，输出worker/sidecar/ACP/Claude ABSENT不算该层资源验证 |
| `$PY docs/implementation/agent-tools/evidence/agent-unit-model/pi-model-pre-migration-probe.py` 新owner | exit0、3 pure assertions成立，provider writes为空、session/model保留、emptyReadback unknown；原反例JSON不覆盖 |
| `$PY packages/backend/harness-transport/tests/acceptance_install.py --evidence docs/implementation/agent-tools/evidence/agent-unit-model/au003-pi-model-install-final-65e409.json` | exit0、13 command records全部0，七自有wheel hashes/pipcheck/cleaned，M0/productReady=false |
| `$PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration -q --tb=short` | exit1、311P1F、16.40s，仍strict cold generation目标未改断言 |

最终160组合完整参数：`$PY -m pytest plugins/harness/pi/tests/test_acp_model_configuration.py plugins/harness/tests/configuration_model/test_adapters_conformance.py plugins/harness/tests/configuration_model/test_request_params.py plugins/harness/api/tests plugins/harness/tests/test_family_dialect_tables.py plugins/harness/tests/test_agent_unit_source_ownership.py -q --tb=short`。

新增48pure tests、1fresh发行test与1ownership gate；全Pi262=原213＋新48＋发行1，不累计中间快照。fresh test五包no-index/no-deps复制own源码、净HOME/环境、Python-I验证无monolith/Server/ServerAPI/产品/其他两家，实际credential/budget/retry编译，default start/apply拒。七包helper不覆盖旧证据，实际核对13退出码与清理标记。最终Pi与product句柄均terminal；product结果收集在末端Pi调用后，没有以未收集输出称terminal。为消除这一串行证据不确定，最后由同一orchestrator明确先等待product terminal，再执行全Pi：product exit1、311P1F、16.85s；随后Pi exit0、262P、8.48s，均terminal。最终采这组串行结果，前组保留，不累计。没有用户服务/native模型进程。

## 仍未完成

C＋own安装进程，非native Harness P/M；M0，费用unknown。production routing/credential/budget/retry确认、scope/operation/capture/receipt/authority/material/Session recovery/完整生命周期/tasks/results/Skill实用/A18仍PARTIAL。coldgeneration提案待裁定；旧C2 consumer 1F/27E、旧ServerPi、Core三红与资源ABSENT沿前账本继续，Core/全Server/旧C2本轮未跑。

通用历史baseline安装清单未补own family依赖，wholeServer发行未验证，七包独立安装不关闭它。未安装更新第三方、登录、改用户DB/凭据/全局配置、重启用户服务、push或合并主树。资料strict与diff仅资料门，两只读审查不冒测试。本切片检查点后继续独立production consumer与装配缺口，不标AU003_DONE。
