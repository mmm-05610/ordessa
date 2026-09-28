# Pi / Codex / Claude Code：品牌配置适配

目标注册点：Harness C2 `harness.configuration-adapters` v1，facet=`assets.model-provider`；实现模块分别为本业务域的 `adapters/pi.py`、`adapters/codex.py`、`adapters/claude.py`（实际语言/目录在 T00 随 Harness 导出冻结）。每个 adapter 纯 `assess/compile/verify`；它不读 HOME、网络、spawn、写配置或解析秘密。Harness C1 负责专用实例、目标句柄、同一原生会话 resume、受控观察。无 C1/ACP 真实接缝时不能把 E1 假实现升级为可交付。

| 品牌 | 官方语义与原生入口 | 首选下轮路径 | 未证明时 |
| --- | --- | --- | --- |
| Pi | 固定源码 [models](https://github.com/earendil-works/pi/blob/2b0a123de98318c2ff8069661721ce0c3794c34e/packages/coding-agent/docs/models.md)：`models.json` 可声明 provider、model；[RPC](https://github.com/earendil-works/pi/blob/2b0a123de98318c2ff8069661721ce0c3794c34e/packages/coding-agent/docs/rpc.md) `set_model` 返回命令结果 | 模型同连接、Provider 配置已在专用实例可用时走 session-local 控制 + readback；Provider 增删/认证变化走 generation reload 或 restart-resume（须真实入口证据） | RPC set_model 仅证明 model 参数处理，不证明 endpoint/secret 切换；拒绝“ready”。 |
| Codex | [config reference](https://learn.chatgpt.com/docs/config-file/config-reference)：`model_provider` 和 `model_providers.*`，项目配置禁覆这些键；[advanced](https://learn.chatgpt.com/docs/config-file/config-advanced) 自定义提供者 | 仅模型变更可先核 app-server thread/turn 控制；跨 provider 用实例私有 config generation + 受控重启/同 thread resume，若实际 pinned adapter 支持且 readback 匹配 | 不能写项目 `.codex/config.toml` 或共享 CODEX_HOME；仅 config 文件可写不等于当前会话生效。 |
| Claude Code | [model config](https://code.claude.com/docs/en/model-config) 的 model 与 `ANTHROPIC_BASE_URL` 分属两事。当前本仓 `packaging/claude/provider-session.test.mjs`/`provider-routing-smoke.mjs` 有假端点同进程 A/B 隔离和 A resume 证据 | 优先每原生 session Query 级配置+受控替换/原 session resume；经现有 ACP adapter session fingerprint、route、readback 核验 | 假 endpoint E2 只证明路线和 transcript；真实 OAuth/keychain/其他认证模式未证，不保证第三方提供者都兼容 Anthropic messages。 |

所有品牌都必须按目标**具体版本+入口**声明 supported/unsupported/unknown；`modelId`、`providerConfigId`、secret ref、原生协议及认证模式一并 assess。`compile` 对同一 native provider/model 数组给单一 owner 的最终快照，`BindSecret` 只传引用。不同 facet 争同字段由 Harness 类型化拒绝，不靠注册顺序。`verify` 只解释 Harness 采样：配置文件摘要仅是 projected，不等于当前进程/会话 applied；能力回读/provider 探针/消息实帧须分层。原生默认/登录状态可展示成只读 ProviderConfig，但不能未授权接管账户。

验证级别：E0 接口/官方文档；E1 本域 fake adapter；E2 固定真 Harness/ACP bridge + fake 下游，证 provider/model 路由、readback、resume ID、双会话隔离；E3 真实模型（本轮**不跑**，另需范围与费用授权）。Pi/Codex E2 尚未在本包实测；Claude 仓内已有 E2 的一部分，须按最终 pin/产品装配重跑。不得把 E0/E1 或单次 fake 响应写成三品牌已跑通。

重启事务：先保存旧 generation/原生 ID，取得 submit permit 后构造新私有 generation，验证 sibling 不共享可变根与进程级配置；若隔离不能证明则拒绝。停旧实例→启新实例→`resume(expectedNativeId)`→确认 ID 和目标选择→允许 prompt。失败时可恢复旧 generation 也必须经同一会话身份核验；如果不确定旧/新谁承接会话则进入 Unknown 而非静默双启动。不能通过恢复历史 transcript 后 `session/new` 伪装同会话续聊。
