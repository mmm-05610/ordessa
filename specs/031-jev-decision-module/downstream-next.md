# 后续真实家族验证：待扩展授权的具体范围

当前原冻结合同 python-freeze.md 明确 Existing providers stay unsupported。真实 Jev 合成调用授权不包含真实 Harness；本轮不能通过悄悄实现新家族或启动原生会话把 PARTIAL 改为全部完成。

建议第一步仅扩展 Codex 原 owner 的公开纯只读能力，修改位置为 plugins/harness/codex/src/ordessa_harness_codex/provider.py 及原家族测试／本 spec 契约。复用 CodexRuntimeProvider 现有 descriptor、原配置评估及原资料投影，声明 agent-configuration-read/1；不建立新 owner／执行器／状态库，不根据 schema 推断实际支持。

先盘点原 owner 实际可证明范围，再冻结外部配置 kind／schema／义务及映射。未知 installation/runtimeReady/实际生效继续 unknown/unverifiable；缺真实资料拒绝，不伪造支持。只读端口不得 start/connect/prepare/apply、spawn进程、写目录、收费网络或读登录文件。注册使用本树临时核心与合成数据，不接触用户 Environment。

| 场景 | 要求证据 |
| --- | --- |
| 正例／拒绝／缺席 | 原 CodexRuntimeProvider 实际公开调用与精确 input/descriptor/source/obligation 绑定；适用范围之外明确 unverifiable |
| 权限撤销／owner及来源换代 | 使用原准入及资料投影，不能旧回执 ready；mutation spy 计数0 |
| builder 错映射／第三方注入 | 外部映射 verifier 拒绝，或原 TaskGate 忽略非权威指令，不让模型获取核心操作权 |
| 取消／预算／崩溃窗 | 原 runtime/gateway/evidence 的已有离线反例复验，作用域不提升为真实断电 |
| 真实 Jev + 实际原家族只读 owner | 同一已授权 Zen 免费范围、合成数据、单批有限预算／重试0，原图返回提案，不执行操作 |

此步骤也不能证明真实原生启动／配置应用。若要实际 Harness 攻击链，须另批准隔离安装与进程启动／关闭、指定模型凭据和调用成本、临时实例 prepare/start/connect/apply 的动作及清理范围；不得重启现有服务或迁移用户资料。实际模型费用未授权前，不能让原生进程自动发请求。

本页是审阅计划，不是授权记录；尚未修改原家族或调用 Harness。即使扩展获批，其他 Pi/Claude 家族仍 unsupported，不宣称七动作全部可用。
