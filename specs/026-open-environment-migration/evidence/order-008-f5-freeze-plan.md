# 008 首切片设计 — T008-11 F5 增量冻结（主代理裁决，008 开工即派）

依据：contracts/frontend-infrastructure.md（R7/M14）+ T008-11 文本。002 冻结不重开：本文件是
002 六台账的**增量登记**，版本向前（oe-contract/1 不动，新增 F5 命名空间 `oe-f5/1`）。

## 复用路线裁决（F5 §8 要求实现前定案）

**本轮自建最小机制，不引入 Zustand/TanStack 新依赖。**理由：F5 §8 明确候选采用须"窄范围源码/
许可/发行检查、固定版本/lock、测试真实包入口"——本轮无网络/许可核验预算与授权，且 §8 同时允许
"候选无法满足时可沿用现有小工具补齐，记录原因"。现有基础：入口已有 `useSyncExternalStore` 消费
面（packages/workbench 等），通知/进度在 workbench 已有局部实现可合并。登记：若 012 前获得候选
核验预算，可再评估替换（语义门 A96–A103 不因实现库而变）。

## F5 冻结面（TS，落 packages/desktop-platform/contracts/foundation/src/open-environment/f5/）

| 模块 | 冻结内容（名称即 API） | 关键反例（进测试） |
| --- | --- | --- |
| state.ts | `createStateStore<S>(initial)` → `{getSnapshot, subscribe, set(ownerOnly), notifyBatched}`；owner 写入口不经消费者暴露；快照身份稳定（未变化同引用）；批量只暴露完整快照 | 消费者拿到的对象上无 setState；嵌套变更后旧快照不被改写 |
| selectors.ts | `selectField(lens, equality)`；`useStoreSelection(store, selector)`（React 绑定独立 exports） | 无关字段零通知；卸载退订；旧 dispose 不触新 owner |
| projection.ts | `AuthorizedProjection<T>`：readAndSubscribe 复用 E3 语义（cursor/credit/lease），gap→`resync-required` | 撤权后投递停止、可访问快照清空 |
| query.ts | `createQueryCache`：声明式 key（环境+连接代次+授权范围+目标+合同版本+参数）；合并/分页/invalidate/有界清理；`refreshPolicy` 显式 | 非幂等效果冒 query 拒；跨授权 key 不共享 |
| tasks.ts | `createTaskScope(scope)`：句柄含 target/activation/generation/请求关联；`cancelWait`≠操作取消；晚到结果屏障（代次校验） | A 晚到覆盖 B 拒；unknown 保原关联不重发 |
| editing.ts | `EditSession`：editId/baseRevision/editRevision/dirty/错误/保存关联；`commit(capture)` 只清未变字段；冲突保本地 | 迟到成功清 B 编辑拒（ABA）；秘密字段禁入通用表单 store（类型层 SecretRef-only） |
| uiStorage.ts | `UiStoreContract`：pluginNamespace/workspace/window-or-shared/schemaVersion 分区；读/条件写/删自有/迁移；无适配=`session-only` 显式标记 | 未知 schema 拒写；scope 释放不删持久偏好 |
| interactions.ts | `NotificationHandle/ProgressHandle/QuickPickHandle`：稳定 ID 更新（不重开红提示）、取消投影任务声明、`when` 仅展示 | 取消即显示"已停止"拒；重复事件刷屏拒 |
| errors.ts | `F5Error` 族：`WriteAccessDenied/SnapshotMutated/StaleGeneration/QueryEffectMismatch/EditConflict(ABA)/UiSchemaUnknown/InteractionScopeRevoked` | 每错误一条定向反例 |
| tokens.ts | 单点构造：`StateStoresToken/F5QueryCacheToken/UiStorageToken/InteractionServiceToken`（字面量 `ordessa.f5.*.v1`） | 第二构造点=Token 两份反例（沿用 C7 token-identity 模式） |

**缺席矩阵**：每能力声明 `available|session-only|unavailable`（如 uiStorage 无宿主适配=session-only；
React 绑定在中性入口 absent 时 unavailable 而非降级模拟）。

## 增量台账登记（对 002 六台账的 diff，T008-11 交付物）

- public-api.json：+foundation/src/open-environment/f5/* 导出面与消费者（先两个 fixture 消费者）。
- identity-map.json：+4 Token 字面量、f5 模块路径；无新发行单元（仍在 contracts-foundation 载体内）。
- authority-map.json：+“前端本地 UI 状态/编辑草稿（非后端事实）”条目——owner=创建它的域，平台仅工厂。
- capability-matrix.json：+F5 各能力 available/session-only/unavailable 初值。
- contract-tests.json：+f5 套件（向量沿用 002 双语对照模式；TS 单侧为主，Python 侧仅 errors/DTO 镜像）。
- domain-paths.json：无新路径（R4 已冻结 frontend 包组）。

## 两个中性 fixture 消费者（T008-13/T008-20 用）

1. `examples/external-samples/f5-counter/`（非 React：纯状态+查询+任务演示，AST 门禁 React import）。
2. `examples/external-samples/f5-react-panel/`（React 选择订阅+编辑会话；独立 vitest）。
两者不 import Agent/Profile/Chat/Harness；接入证明沿用样例#2 的 pathspec 模式。

## 切片分解（007 收口后依序派发）

S1=T008-11 冻结+向量+台账增量；S2=T008-12/13 状态容器+React 绑定+两 fixture；
S3=T008-14/15 投影+查询+任务；S4=T008-16/17 编辑+UI 存储；S5=T008-18/19 Workbench 交互+上下文；
S6=T008-20 全发现+A96–A103/A109 正反例收口。
