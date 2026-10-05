# Pi pure migration 前置盘点

基线 `8e49d0413e6119e8a05aad59aabbdd5f74f9244a`，Codex检查点后 clean。主会话唯一写者，Claude代理只读盘点，不测试/写文件/Git。保留三家成果与合同，只读核对之后可沿既有 harness-api.model_compilation迁移，无新共享接口。

目标：旧 `plugins/harness/src/ordessa_harness/pi/configuration/model.py` → 独立 Pi acp_model_configuration；common 的 Pi dialect/version/models/settings/maxTokens facts及 native_materialization.render_pi_provider → Pi facts；旧 common、pi/native.py、bridge和原 conformance/request params/family/native-materialization tests使用新 owner。独立Pi pyproject补既有API依赖，旧Harness明确Pi own dependency。fresh closure测试补API，验证无Server/monolith/产品或其他家族依赖。

保留 provider存在/无配置变更 set_model intent，provider/credential变更与SecretRef/sameSession restart-resume，maxTokens当前sample保 sibling/model fields，retry完整block与host-issued settings target，未知/ACK-only不报applied，未钉reasoning/timeout仍拒。现provider真实面仅pi.model/pi.thinking；历史ACP0.5轴不能升级为这些扩展参数的生产确认。

## 已复现反例

运行源码环境：`PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:plugins/harness/api/src:packages/backend/harness-transport/src`。
解释器 `$PY=/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`。
命令：`$PY docs/implementation/agent-tools/evidence/agent-unit-model/pi-model-pre-migration-probe.py`。

初 inline同一受控输入实跑exit1，0P/3F、receipt `pi-model-pre-migration-counterexamples-8e49d0.json`，随后保存可复跑script：retry-only写仅baseUrl/api的providers.acme，丢现有models；restart意图仅provider/retry，没有session model；空readback与无session返回match。不是pytest数量，也不是native P/M。script断言保留，迁移后更新import并复跑正反例；必须补 typed flags/target/session 和重复model id冲突边界，不能只修三个示例。

没有副作用/真实模型/凭据，M0，费用unknown；production routing/credential/budget/retry scope/revision/operation/capture/receipt/applied 仍未接线，不称成熟通道全面迁移。下一动作是原compiler/facts迁移与测试，非整单完成。
