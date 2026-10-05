# AU003 旧 native_runtime 三家选择早拒（PARTIAL）

基线 f08a635c85e930cfe80bc4db93fb929ffe8562b6，clean；所有子代理completed，主会话唯一共享源码/Git/测试/账本写者。Codex仅只读攻击与终审。此切片不删除旧模型编译器、配置服务或持久身份。

`ServerProductComposition.native_runtime` 在旧runtime/model import、legacy链注册、配置状态修改及目录/secret/store创建前，以既有公开 `GuaranteeUnavailableError` 拒绝 pi/codex/claude-code/已有claude别名。检查主选择、profile选择、additional_adapters和隐式Pi bridge。要求独立CoreRegistry provider admission，无fallback或新注册表。其他家族沿原路径；七项正控只证明原assembly入口可达，不证明七家完整运行。sidecar独立入口及旧C2 model plugin批量贡献仍未退役，未冒全产品清理完成。

## 主会话串行实测

解释器 `PY=/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`，pytest配置 `-c products/agent-tools/pyproject.toml`，下列均 `-q --tb=short`。

- 实现前 `products/server/tests/test_retired_native_assembly.py`：7P/10F，exit1，0.35s。真实反例到达被植入的legacy assembly门，证明旧primary/profile/additional/implicitPi仍可进入，不是无命中空检查。
- 实现＋别名后，同文件及 `plugins/harness/tests/test_retired_direct_factories.py`：36P，exit0，0.38s。
- 增加旧runtime/model import植入门后，上述二文件＋`plugins/harness/tests/configuration_model/test_adapters_conformance.py`＋`test_request_params.py`：105P，exit0，0.44s。新文件23项，旧门/语义82项，快照不累加。拒绝验证临时data/pluginRoot缺席、composition状态未变、无进程；配置语义原断言保持。
- `products/server/tests/test_native_profile_composition.py::test_native_product_owns_profile_management_without_claiming_application`：0P/1F，exit1，0.11s。旧正向用例仍要求统一Pi runtime，本次正确拒绝与旧预期冲突；原测试未改/未skip。后续必须迁移其消费到独立provider并逐项保留Profile/Skills/配置断言，不能把这项红冒成完成。
- 前缀 `PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:packages/backend/harness-transport/src`，`products/agent-tools/tests/integration`：297P，exit0，12.21s。

## 限制

C证据，无nativeHarness P和任务M，M0。未全Server/Core回归；Core继承三红与worker/sidecar/ACP/Claude资源ABSENT保持历史登记。独立三家生产模型/endpoint/SecretRef/managed-account/restart-resume owner尚未完备；拒旧入口并不提供新入口成功能力。旧Server上述红与全量未验证必须保留。原数据/身份不改，没有安装更新第三方、登录、模型、用户服务、用户DB/凭据/全局配置、push或主树合并。费用unknown。工单结构/diff只资料检查，不升格产品验收。
