# AU003 Codex 纯模型配置能力迁移

基线 `6af84df2a426d2bc39d3f91f7db80adfa33ed845`。本轮保留上一上下文已做未提交迁移，当前 HEAD/dirty/代理写权实核；主会话唯一共享源码、测试、Git及账本作者。Codex/Claude 两代理只读审阅，均无写入、测试或 Git。上一状态问答是 no progress，本轮修反例、复跑、发行与记账属于 progress。

## 复用与所有权

旧 `ordessa_harness/codex/configuration/model.py` 纯 compiler 迁独立 `ordessa_harness_codex/acp_model_configuration.py`，旧文件物理删除，无 shim。初 class/function AST 等价证据与后续修补分开，见 `codex-model-migration-source.json`。复用已存在公共 `ordessa_harness_api.model_compilation` DTO/parser，无新合同包、Registry、授权或 Store。独立包不导入旧 Harness、Server 或产品。

独立 `acp_model_facts.py` 持有历史 ACP dialect/version/native target/effort/renderer。旧 shared common、codex/native.py、remote effort 与 native_materialization 消费此 owner；原 native_materialization wrapper 先执行旧 protocol validation，保留 NativeMaterializationError 表面。普通 provider/endpoint golden 字节不变；provider 含点/引号仍为一个 literal TOML key，endpoint 引号正确转义，C0/DEL 控制字符拒绝。

独立 Codex 明确增加已有 Harness API 依赖；旧 Harness 增加独立 Codex 依赖，以消费成熟纯编译能力，方向不可反转。bridge 与原测试直接使用新 compiler。源码 gate 只迁确切独立 compiler 白名单，未宽放私有 import。原 SecretRef 门此前 conditional skip，现改成有实际 binding 的正向 fixture并断言非 Refusal/实际 reference；没有删断言或用 skip 隐藏失败。

## 正向能力与反例

保留 model-only session-local、cross-provider routing selector/provider table/SecretRef 与同 thread restart-resume 计划、reasoning effort 正向 intent。同 provider 改 endpoint 现在保 routing；credential-only 保 BindSecret 与 model、不重写 endpoint。缺旧 provider 观察不猜未变。非 bool change flags、非法 ref/model/provider/target/endpoint typed 拒绝。verify 对缺失、bool/int 或非法 model/provider/thread 不会因相等而 match；ACK-only unknown，wrong thread mismatch。

历史 ACP `>=1.0 <2.0`（fixture 1.1.14）与当前 app-server 0.157.1 是两个版本轴。纯编译迁移未扩大 provider methods/schema、未授予 start/apply、未连接真实 native application。verify 的 match 仅 thread/model/provider readback；endpoint/credential/effort 完整 applied、managed-account 和实际 restoration 仍缺 scope/operation/capture/receipt/native owner 证据。resume_expectation 的 None/True 仍只是未经确认的纯计划值，verify unknown，不能声称保证恢复原 thread。

## 串行验证

`PY=/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`。
最终源码环境：`PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:plugins/harness/api/src:packages/backend/harness-transport/src`。

| 实际命令/场景 | 退出码、数量、耗时 |
| --- | --- |
| `$PY -m pytest plugins/harness/tests/configuration_model/test_adapters_conformance.py plugins/harness/tests/configuration_model/test_request_params.py plugins/harness/api/tests -q --tb=short` 初迁 | exit1、79P1F＋37subtests、0.41s：旧 compiler import 白名单 |
| `$PY -m pytest plugins/harness/codex/tests/test_acp_model_configuration.py -q --tb=short` 初32 | exit1、3P29F、0.19s：routing/ref/type/renderer 反例 |
| 新32＋原pure/API＋family tables | exit0、131P＋37subtests、0.45s |
| 增 missing-before 两反例未修 | exit1、32P2F、0.18s |
| 修 missing-before＋原pure/API/family/source gates | exit0、144P1skip＋37subtests、0.60s；skip 原 SecretRef conditional，不算该门验收 |
| 加真实 BindSecret 正控与加强断言，同组 | exit0、145P＋37subtests、0.58s、0skip |
| `$PY -m pytest plugins/harness/codex/tests -q --tb=short` env缺 transport | exit2、2 collection errors、0.24s；test_client/test_prepared_client 缺实际 source，不隐藏 |
| 补本树 transport 源码，同全包 | exit0、201P、7.57s，中间快照 |
| 新 DEL renderer/compile 两参数反例未修 | exit1、34P2F、0.18s |
| DEL typed 校验后，全 Codex | exit0、203P、7.57s、0skip，含 fresh 五 wheel安装闭包 |
| 最终 new model＋original conformance/request/API/family/source | exit0、147P＋37subtests、0.62s、0skip |
| `$PY packages/backend/harness-transport/tests/acceptance_install.py --evidence docs/implementation/agent-tools/evidence/agent-unit-model/au003-codex-model-install-final-6af84d.json` | exit0、13 command records 全0，7 wheel hashes、pip check、temporaryEnvironmentRemoved=true、M0/productReady=false |
| `$PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration -q --tb=short` | exit1、311P1F、16.98s；原 strict cold generation目标仍失败，未改断言 |

最终定向完整参数：`$PY -m pytest plugins/harness/codex/tests/test_acp_model_configuration.py plugins/harness/tests/configuration_model/test_adapters_conformance.py plugins/harness/tests/configuration_model/test_request_params.py plugins/harness/api/tests plugins/harness/tests/test_family_dialect_tables.py plugins/harness/tests/test_agent_unit_source_ownership.py -q --tb=short`。

新增36 pure 编译测试、1 fresh安装测试与1 ownership gate，不累计中间快照。全 Codex 203 = 原166＋新36＋新发行1。fresh 五 wheel test用 no-index/no-deps、自有源码复制与干净 HOME/Python -I，确认无旧Harness/Server/ServerAPI/产品/另外两家；实际编译 routing/ref/quoted-key 正控且 default provider start/apply仍拒绝。七包 helper 新证据未覆盖任何已有 receipt，final source SHA与13 exitCode、清理/M0标记实际核对。

## 未完成与资源

C＋自有 fresh distribution 进程，不等于 native Harness P 或真实任务 M。无真实模型调用，M0、费用unknown。production owner/routing/凭据/material/授权/恢复/完整生命周期/tasks/results/旧sidecar与C2消费者/A18仍 PARTIAL。冷代次初始化提案待裁定，不能用暂时 reopen guard称冷恢复完成；原 Core三红、旧ServerPi与C2 1F/27E均继续，Core/全Server本轮未跑。缺资源 ABSENT 不算绿。

独立发行闭包成功不证明通用历史 baseline 安装清单或整个 Server distribution闭包；该清单未包含新增 own family dependencies，待整合发行阶段修复与验证。未安装更新第三方、登录、修改用户数据/凭据/全局配置、重启用户服务、push或主树合并。所有测试句柄terminal；本切片检查点后继续 Pi 成熟能力迁移，不标 AU003_DONE。
