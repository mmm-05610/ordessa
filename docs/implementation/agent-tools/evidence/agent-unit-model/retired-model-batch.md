# AU003 旧三家 C2 批量发布入口退役

基线 `b5f17678c9` clean，主会话唯一源码/测试/Git/账本作者；Codex只读复核，无测试/Git。只修改旧Harness入口和受控边界测试，不改变公开AgentUnit合同或新三家提供者。

`ModelProviderAdaptersPlugin` 原先顶层导入三brand registration、无条件以一个owner发布三家配置适配器。现在descriptor、插件ID `ordessa.model-provider.adapters`、point `harness.configuration-adapters` 和版本保持；build在读取context、发布、IO之前以既有公共 `GuaranteeUnavailableError` 明确拒绝，要求独立provider admission。移除批量factory和三brand顶层imports，不触碰纯bridge/brand compiler、原生配置格式、账户或用户数据。此plugin只注册三家，所以没有封闭七家独立旧注册。

新4项覆盖直接缺context拒绝、稳定descriptor、reload不导入旧registration、实际自有Server PluginHost激活失败不发布贡献。真实native/M均0。C2不再发布不代表独立生产配置已接线；直接pure adapter仍可构造，live_service及sidecar旁路仍需处理。

## 实际串行验证

解释器 `/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`（以下 `$PY`）。

| 命令 | 结果 |
| --- | --- |
| `$PY -m pytest plugins/harness/tests/test_retired_model_adapters.py -q` guard前 | exit1、1F、0.15s：旧build未拒绝 |
| 同门guard后初稿 | exit1、2P1F、0.09s：测试误写descriptor.plugin_id，改已有descriptor.id |
| `$PY -m pytest plugins/harness/tests/test_retired_model_adapters.py plugins/harness/tests/configuration_model/test_adapters_conformance.py plugins/harness/tests/configuration_model/test_pi_live_model.py plugins/harness/tests/configuration_model/test_request_params.py -q` | exit1、86P1F、0.85s：原pure import gate缺公开environment-api拒绝类型 |
| 同组合修门后 | exit0、87P、0.72s |
| 同组合加 `products/server/tests/test_retired_native_assembly.py` | exit0、110P、0.77s：原七家assembly reach正控保留；不称七家实际可运行 |
| `$PY -m pytest plugins/harness/tests/test_brand_organization_gates.py::test_model_provider_adapter_plugin_publishes_all_three_on_the_neutral_point plugins/harness/tests/configuration_model/test_pi_live_runtime.py -q --tb=short` | exit1、2P1F27E、2.01s：旧批量发布正例1F；live_runtime前两pure compiler正例2P，其余27参数化场景setup早拒 |

边界门只新增允许公共 `ordessa_environment_api` 的拒绝类型，保留原AST扫描/禁止IO/brand纯度所有断言；未允许私有Server或effect依赖。原正向消费者与断言完全保留，未skip/删除/改期待绿。新增4项，不累计测试快照；全Core/Server/产品integration本切片未复跑。

27个setup errors来自 `test_pi_live_runtime.py::rig/native_rig → make_rig → ModelProviderAdaptersPlugin`；包含C4确认、零作用拒绝、stale capture、adapter卸载、readback mismatch、SecretRef绑定变动与跨品牌配置变化。它们是本次退役导致的消费者迁移债，不是继承绿或缺资源skip。另ModelProvider E2、Server受控C4和packaging probes源码可见消费者尚未实跑，仍未验证。不能用110项成功替代这些门。

## 后续

应将原消费者接到独立provider实际owner后保留并重跑所有原配置/凭据/unknown/restore断言，不复活旧三家batch。sidecar Runtime的部署解析在server-compat，产品先读再由域重读会有TOCTOU；该域不在当前AU003 write_paths，所以仅记录所需共享接缝，不在产品复制parser或以外部编排绕过。直接live_service/NativeModelServices仍有作用入口和成熟独有配置能力，需在允许域逐项迁移。

整体PARTIAL：生产授权/材料/凭据/owner、coldgeneration裁定、三家native P/M、full lifecycle/tasks/results/完整A18仍未完成。M0、成本unknown；无第三方安装更新、登录、用户服务/DB/凭据/全局配置、push或主树合并。
