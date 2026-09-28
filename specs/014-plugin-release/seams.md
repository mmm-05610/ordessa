# 接缝请求单（014 → core/013 线）

> 用法：本文件是 plugin 线对 core 线的全部跨线请求。**逐条与用户讨论后**转交 core 线（pi/013）；plugin 侧在接缝落地前以受控 fixture / 诚实缺席推进，不越界代写。状态：`open`（待讨论）/ `relayed`（已转 core）/ `landed`（已落地，回填 SHA）。

| id | 请求 | 落点（core 侧文件） | 解锁什么 | 状态 |
| --- | --- | --- | --- | --- |
| S-00 | `docs/release/first-release-handoff.md` 与 `specs/013-desktop-product/` **入库**（当前 main 未跟踪，发行门依据不在版本控制内） | 随 013 收口提交 | 三包引用发行门时有权威版本可指 | open |
| S-01 | `products/desktop/extensions.json` 启停：enabled 增 `ordessa.chat-api`、`ordessa.chat`、`ordessa.profile-api`、`ordessa.profile-frontend`、`ordessa.profile-chat`；C 退役后移除 `ordessa.agent-conversation` 并删除 `apps/desktop/renderer/agent-conversation.test.tsx`（等价覆盖已由 chat composer-flow 声明，C 侧负责逐条核对后在本单确认）（依赖闭包：profile-chat 需 chat-api 同时启用，`plugins/profile/integrations/chat/src/glue.ts:17`） | `products/desktop/extensions.json`、`apps/desktop/renderer/**` | A 桌面三包与 C chat 的产品激活 | open |
| S-02 | `extensions.lock.json` 与根 `package-lock.json` 重生成（esbuild 非确定性，以 core 构建为准；C 退役后 `@assistant-ui/react` 从根锁摘除） | `products/desktop/*.lock.json`、根 lock | 装配实测 | open |
| S-03 | Server 默认插件集增 profile 入口（entry point `agent_box.plugins → ordessa_profile.plugin:create_plugin`）；model-provider 的装配**必须排在 S-08 compat 退役之后**（反序双 owner 起不来） | `products/server/src/ordessa_server_product/composition.py:146-153` | A/B 服务端激活 | open |
| S-04 | `tooling/vitest-extensions.mjs` CONTRACT_SOURCES 增 `ordessa.chat-api`、`ordessa.profile-api`（现仅 contracts/agent-contracts 两行） | `tooling/vitest-extensions.mjs:13-16` | 契约测试进根套件 | open |
| S-05 | 附件 prepare 生产 owner：`AcpAttachmentPreparePort`（`plugins/connectors/acp/src/attachments.ts:35-41`）的宿主实现（内容上传/哈希往返）与 `BackendAdmissionState` 生产供给（`plugins/connectors/ordessa/src/acp-next-submit.ts:3-8` 头注自述缺 owner） | harness/server 侧（归属 core 讨论） | C 的附件生产链与三态 accepted 生产形态 | open |
| S-06 | admission `ready=False` 翻转链：`bootstrap/runtime.py:607` 装 authority + SR-3c 三事实（`acp.admission.native_evidence`/`principal`/`server.instance_id`）。**overnight-review 明令不得简单翻转 ready**；翻转前生产环境必须保持诚实 refused/unknown | `apps/server/**` | C 三态生产 accepted；B 的 MP-05 真实生产门 | open |
| S-07 | **需用户裁定**：Claude Code 无 ACP 桥 backend（Go 桥仅 codex|pi），命令目录与附件无承载。默认=claude 行诚实缺席过门；若要求三品牌全绿，需 harness 线为 claude 补承载（成本另估） | `plugins/harness/adapters/acp-adapter`（harness-internal） | C 的三品牌矩阵 claude 行 | open（裁定项） |
| S-08 | compat/旧 writer 退役顺序（均 core 集成时执行）：① server-compat `model_configs` writer（`core_wire.py:238-276`）先退，再装 model-provider（双 owner 门 `DuplicateMethodError`）；② harness 品牌渲染（`native_materialization.py:114-145`）退役，由 B 的 adapters common.py 金样承接；③ profile 旧 writer（harness `generic/profile_*.py`、`harness-profile-store` entrypoint、server-compat `server_profiles`）退役 + `agent-box.profile@1` **双声明仲裁**（harness 侧与 profile-api 都声明，先加载者赢后者 FAIL） | `plugins/server-compat/**`、`plugins/harness/**`、`products/**` | B 装配；A 唯一声明；旧链退出 | open |
| S-09 | canonical SessionRef 服务端映射（现仅 legacy `realm='local', uid='legacy:<id>'`；跨连接真实映射归会话所有者） | apps/server 会话 owner | A 的跨连接 profile 绑定 | open |
| S-10 | `docs/baseline.md` 可编辑安装清单补 `plugins/profile` 与 model-provider 各包（各包 R0 已在树内补录命令，请求正式入库） | `docs/baseline.md:41-43` | 环境可复现 | open |
| S-11 | desktop PluginContext 的 Server wire invoke 生产绑定（REQ-Z3-5：`TRANSPORT_MISSING` 类型化拒绝已就位，缺生产绑定；foundation 是否已提供由 B 在 R0 核实） | `packages/desktop-platform/**` | B 的 MP-03/09 桌面半格 | open（R0 先核实） |

## 转交记录

（由主会话维护：日期 / 转交对象 / core 侧回应 / 落地 SHA）
