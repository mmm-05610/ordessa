# Z2 integration-request（交 C0 集成时处理）

## 1. 产品装配（R09：products 归 C0）

- `products/desktop/extensions.json` enabled 列表需加入 `ordessa.chat-api` 与 `ordessa.chat`（必须同时含 `ordessa.chat-api`：`ordessa.chat` 的入口以 `@extensions/ordessa.chat-api/contract.js` 导入共享契约，`tooling/build-all.mjs` 的 sourceDependencies 检查要求其处于 enabled 集）。当前本树未改 products（线界约束），装配验证由 C0 在集成树执行。
- 旧 `ordessa.agent-conversation` 的关闭（保留 manifest ID 与用户数据）：CHAT-V08 归集成裁决。本线新 Chat 页 view id 为 `chat.page`，模块 id `ordessa.chat`；旧 view id `agent.conversation` 未复用。

## 2. 根 lock 变化（plan：本线只登记，最终根锁由 C0 生成）

本线为 `plugins/chat/frontend` 新增依赖（声明在该包 package.json，根 workspace 解析）：

- streamdown 2.5.0 / @streamdown/cjk 1.0.3
- shiki 4.0.2
- use-stick-to-bottom 1.1.3
- radix-ui ^1.6.7（沿用根锁已有版本，未引入新版本）
- devDependencies：vitest（既有版本）复用根锁，无新增版本

根 `package-lock.json` 相对基线的增量即上述闭包；根 `package.json` 未改。C0 重新生成最终根锁时以上述声明为准。另外：本树 `npm run build` 会重生成 `products/desktop/extensions.lock.json` 中 ordessa.workbench entry 的哈希（esbuild 产物非确定性），本线已还原、不携带该变化；集成时以 C0 构建为准。

## 3. 非线界的一处机械修改（请 C0 复核）

- `apps/desktop/tsconfig.json`：paths 增加一行 `@extensions/ordessa.chat-api/contract.js → ../../plugins/chat/api/src/contract.ts`（与既有 contracts 条目同型，纯粹为根 typecheck 解析插件消费的共享契约；不动 include/编译选项）。

## 4. 旧文件退役清单（全产品完成条件，等公共收尾）

| 旧文件 | 处置 | 阻塞条件 |
| --- | --- | --- |
| `plugins/agent/conversation/src/view.tsx` | 关闭注册链，文件随旧插件退役 | C0 关闭 `ordessa.agent-conversation` 注册时 |
| `plugins/agent/conversation/src/interaction-card.tsx` | 语义已迁入 `plugins/chat/frontend/src/components/interactions/approval-panel.tsx`（原动作语义保留：choices/fields/confirm/input/editor、FC-0029 能力门） | 同上 |
| `plugins/agent/conversation/src/styles.ts`、`entry.tsx` | 退役 | 同上 |
| `@assistant-ui/react` 依赖（plugins/agent/conversation/package.json） | 旧链退役后从根锁移除 | 同上 |
| `apps/desktop/renderer/agent-conversation.test.tsx` | 旧 UI 断言映射：草稿 pane/FC-0052、IME、发送拒绝保草稿等已在 `plugins/chat/frontend/tests/composer-flow.test.tsx` 以新组件等价覆盖；退役时删除旧文件 | 旧链关闭时 |

`plugins/agent/sessions/**` 是否并入：按共同 plan 由 C0 统一裁决，本线只读，无请求。

## 5. 对 C0 的接缝依赖（对应 api-requests.md）

- R-Z2-1 提交三态、R-Z2-2 附件 prepare/refs、R-Z2-3 命令目录、R-Z2-5 reasoning 状态/块序列、R-Z2-6 文件 picker：落地后 Z2 在本树以固定 SHA 消费并接线；当前 Chat 以诚实缺席呈现（附件入口禁用带原因、无伪命令目录），UI/fixture 已按契约就绪。
- foundation 发布后：chat-api 出修订版把 `defineChatComponentKey` 构造切到平台 `defineUiComponent`（id/major/运行时对象不变）；ChatPage 贡献渲染从本地默认 provider 表切换为 C7 binding 解析。

## 6. C7 产品级接线（chat-api-r3 限制项，机械改动，归 C0）

chat-api r3 已把 `ChatComponentKey` 对齐为平台 `UiComponentKey` 类型（type-only）。剩余的产品级切换为三处机械改动，建议随 chat 扩展启用一起做：

1. `packages/desktop-platform/extension-host/src/main/extension-protocol.ts` import map 增加 `'@ordessa/ui-components/api': '/shared/ui-components-api.js'`（shared 产物由 apps/desktop/scripts/build.mjs 的 shared splitting build 增加一个入口即可）。
2. `tooling/build-extension.mjs` externals 增加 `@ordessa/ui-components`（或按现有共享模块模式处理），避免各扩展 bundle 内联平台 Token 拷贝（CN-08）。
3. `plugins/chat/api/src/contract.ts` 的 `defineChatComponentKey` 改为直接 re-export 平台 `defineUiComponent`（id/major/运行时对象不变；chat-api 是 ordessa.chat.* 键唯一构造点，无 UI_KEY_IDENTITY_CONFLICT）。

在 1/2 落地前，chat 扩展以类型对齐 + 本包构造运行，行为与 r2 完全一致。
