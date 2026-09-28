# Research、现成资产与复用裁定

## 证据与版本口径

先分清官方当前文档、已固定源码、Ordessa 已运行证据：官方页面说明**品牌能力**，不证明当前固定 adapter/ACP 路径可调用。2026-09-28 复核：[Codex 配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)、[Codex 自定义供应商](https://learn.chatgpt.com/docs/config-file/config-advanced)、[Claude 模型配置](https://code.claude.com/docs/en/model-config)、[Pi 固定源码模型文档 @ `2b0a123d`](https://github.com/earendil-works/pi/blob/2b0a123de98318c2ff8069661721ce0c3794c34e/packages/coding-agent/docs/models.md)、[Pi RPC](https://github.com/earendil-works/pi/blob/2b0a123de98318c2ff8069661721ce0c3794c34e/packages/coding-agent/docs/rpc.md)。Codex `model_provider/model_providers` 存在，但项目 `.codex/config.toml` **不能覆盖**这两个键；绝不把写项目文件当按会话供应商切换。Claude `ANTHROPIC_BASE_URL` 只改路由、不改模型。Pi 自定义 models.json 与 session `set_model` 分开，RPC command success 不保证后续模型请求成功。

## 旧设计与部分实现：沿用/修订/补缺

| 来源 | 沿用 | 本包修订或未完 |
| --- | --- | --- |
| `worktrees/model-provider-spec/docs/specs/model-provider/design.md` @ `4346da2` | 三层身份、七态、手动探测、单一 owner、原子 ModelChoice、Profile/Chat 可选贡献 | R1 “不重启”改为 C2 可证实 restart-resume；目录目标改 `plugins/assets/model-provider/`；正式接 Harness C2，不能只消费 fake seam。 |
| `worktrees/plugin-model-provider-impl/specs/002-model-provider/*`、`plugins/model-provider/**` @ `9305563` | 77 后端测试、设置 10、Chat 8、Profile 引用/覆盖测试与实施骨架应优先择取 | DELIVERY 明确 PARTIAL：Compat 六方法未退、真实 ACP seam/产品装配/TurnFact 未接、品牌仅 E1 fake。旧 `Chat` stub 不当成发布契约。需先移植/合并审核，不从零再写。 |
| 本树 `plugins/server-compat/src/ordessa_server_compat/model_configs/**` | 旧行为比较 oracle、表与 wire 标识 | 是待退业务，不作为新插件长期依赖；业务代码入新所有者后退同名注册。 |
| 本树 `plugins/harness/src/ordessa_harness/native_materialization.py` | 已固定方言/endpoint 校验参考 | 现在含品牌渲染，需依 C2 所有权转到本插件品牌模块；Harness 仅保留通用 codec/target/应用。搬迁前后 byte/行为对照，禁互相调用旧品牌函数。 |

工作树只读调查，未在其上写入、切分支或合并。主树 `docs/design/harness-v2`/`profile-v2` 是**目标规格**，不是已发布 API；实施 T00 对 main 实际导出核验。

## 模块级复用矩阵（不是“自行寻找项目”）

| 模块 | 具体来源 | 方式与保留 | 剥离/禁止 | 许可/停点 |
| --- | --- | --- | --- | --- |
| 记录/CAS/幂等 | `plugins/server-compat/.../model_configs/repository.py` 与旧实现 `plugins/model-provider/src/.../records.py` | 先同输入同输出比较，再迁移现有代码 | 不保留 compat import/双 writer | 自仓代码；确认两树分支差异后择取，保留 ID/scope。 |
| 协议与模型事实 | `.../model_configs/provider_protocols.py`、旧 `plugins/model-provider/src/.../protocols.py` | 保留四值 canonical 映射和 unknown 拒绝 | 不让空能力默认全可用 | 自仓；对旧测试词表逐项比对。 |
| 安全探测 | `.../model_configs/probe.py`、旧 `plugins/model-provider/src/.../probe.py` | 保留 HTTPS/loopback 例外、SSRF、重定向、大小/超时上限 | 不在 UI render 自动请求、不开放任意网络代理 | 自仓；测试 fake HTTP 与网段反例。 |
| 下一轮状态机 | 旧 `plugins/model-provider/src/.../next_turn.py`、测试 `test_next_turn_pipeline.py` | 复用拒绝/unknown/零 prompt 状态机与测试 | fake seam 不能当生产证据；补 C2 permit/真实 owner | 自仓；先同契约适配，勿并造第二状态库。 |
| 桌面设置/选择器 | 旧 `plugins/model-provider/desktop/**`、`chat-contribution/**` | 复用两列 UI/状态文案、键盘测试 | 剥离 stub Chat contract、固定 token/color，改用已审平台 UI/真实贡献点 | 自仓；需检查实际平台 API。 |
| Profile glue | 旧 `plugins/model-provider/profile-contribution/**` | 复用引用检查/逐项覆盖反例 | 旧服务对象直绑改已审 facet 接缝 | 自仓；Profile 无装配仍能管理目录。 |
| Claude 会话隔离证据 | `plugins/harness/packaging/claude/provider-session.test.mjs` 和 `provider-routing-smoke.mjs` | 借用已检受控 fake endpoint 测试：A 重路由 B 不变、resume transcript 保留 | 不能把受控假 API 宣称真实模型成功 | `@agentclientprotocol/claude-agent-acp` 供应商包需再核锁定版本/许可证；本包不复制其源码。 |
| Codex/Pi native 适配 | `plugins/harness/src/ordessa_harness/{codex,pi}/native.py`、ACP 桥相关测试 | 借字段证据与受控 harness 行为；新 C2 代码本域自写 | 不复制 Go 桥内核，不把模型 ID 成功当 provider 改好 | 自仓；工具/二进制版本在 T00 固定。 |
| cc-switch | [官方仓](https://github.com/farion1231/cc-switch) 的 provider 列表/预设/探测概念 | **只借鉴设计** | 不复制路由、账号接管、全局配置切换代码 | 如改为移植代码，先固定 SHA/文件、核许可证并留归属；本批禁止未审移植。 |

Pi/Codex/Claude 以外只登记 `unknown/not-scoped`，不从库存清单“有 config 键”推导 Ordessa ACP 可以下轮切。用户数据/secret 禁作测试 fixture，必须使用受控引用与本地假端点。
