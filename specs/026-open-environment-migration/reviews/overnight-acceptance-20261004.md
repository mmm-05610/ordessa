# 2026-10-04 夜间迁移成果验收

## 结论

有大量有效交付，但整项迁移验收不通过，不建议此时整体合入 main。底座、目录迁移、前端工具及部分领域改造已有提交和受控测试；生产单一配置权威、可靠提交与恢复链、发行闭包和真实界面验收尚未完成。不能归纳为“只剩用户裁决/授权”。

## 快照与范围

- 实施树：`worktree/026-open-environment-migration`。
- 分支：`codex/open-environment-migration`。
- HEAD：`0887b95bf900f50d2021a673aa7cfce967a2c3c2`。
- 工作区仍有三个已跟踪文件的未提交修改：`package-lock.json`、`packaging/bundle-manifest.json`、`products/desktop/extensions.lock.json`。本次未修改它们。
- 本次只读审查和受控测试；未修实现、未合并或推送、未启停产品、未调用模型、未迁移真实数据。

## 本次亲自验证

| 检查 | 结果与边界 |
| --- | --- |
| 方案结构校验 | 12 工单 / 129 任务 / 111 case / 30 mutation；仅设计结构校验 |
| Agent 后端测试 | 15 通过；不等于生产 wire 闭环 |
| ui-components Vitest | 8 文件 / 77 测试通过 |
| model-provider/chat-contribution Vitest | 12 文件 / 120 测试通过 |
| profile/integrations/chat Vitest | 8 文件 / 93 测试通过 |
| 三个独立反例 | 均复现，见下文；未修改原测试或源码 |

构建、654 项前端全量、裸宿主 wheel、deb 解包，以及 Server 继承红集对照，是执行者的记录，本次未完整复跑；不能将其写成本次独立验证。deb 解包和载荷扫描不等于安装后可启动和可聊天。

## 必须处理的发现

### P1：生产控件尚未收口到同一个 Agent 配置权威

`plugins/profile/integrations/chat/src/selection.ts:79` 默认创建自己的 `LocalAgentOwnerPort`，`glue.ts:76` 默认使用该 store。`plugins/model-provider/chat-contribution/src/next-turn-client.ts:161` 另外创建自己的 local owner，内部仍持有 pending/current/lastConfirmed 等字段；`chat-api-entry.tsx:127` 没有注入共享 owner。

在 plugins/apps 生产源码中检索 `createAgentOwnerPort`，仅找到其定义，没有调用者。把每个本地 store 的字段移入各自的 owner，并未证明同一会话的 Profile、model 和确认状态共享一个后端权威。不同领域的操作缓冲可以独立，但必须与已确认配置事实分清。

这是 T010-12 未完成的实质接线缺口；不能据此报告“A1 单写者落地全链”。验收条件：两个控件读取同一会话同一代次的权威配置，按操作覆盖字段，迟到确认不回退，不依赖各自镜像拼出当前模型。

### P1：跨窗口条件保存不是原子比较并写入

`packages/frontend/ui-components/src/state/uiStorage.ts:86` 先读取判断 revision，再在另一次异步调用写入；HostUiAdapter 没有原子条件写入口。revisionSeq 还分别属于各个 store。

独立反例：两个 store 共用同一 adapter，以 `ifRevision=base` 并发保存 A/B，得到 `[written, written]`，最终 B 覆盖 A，版本都是 `r-1`。正确结果应只有一个成功、另一个冲突。不能由客户端“读后写”声称跨窗口 CAS。

### P2：公开快照仍可被直接修改且没有通知

`packages/frontend/ui-components/src/state/stateStore.ts:45` 看到子对象已被冻结便跳过递归，但浅冻结对象内部仍可能含可变对象。

独立反例：初始值 `{child: Object.freeze({nested:{value:1}})}`；读者直接把 `snapshot.child.nested.value` 改为 2，成功且通知数为 0。这违反快照不可变和 owner-only 写语义。

### P2：投影关闭后仍接受迟到回调

`packages/frontend/ui-components/src/state/projection.ts:95` 的 close 只 detach，没有让 snapshot/delta 回调失效。

独立反例：先 snapshot revision=1，再 close，再模拟已排队的 snapshot revision=2；observe 返回 revision=2。detach 不能替代本地代次/关闭围栏。另有 overflow 判断在 slice 之后执行，条件不可达，应补反例核查。

### P1：验收证据表把尚未验证的场景标绿

`evidence/t012-13-regression.md` 把 A104–A106 标绿，但 T010-12/13/14 消费者迁移尚未完成；把 A107 标绿，同时注明发行验证 T012-12 未跑；把 A110 标绿，但本次并发反例失败。

需要逐 case 对照原验收条件，重列“已覆盖子条件/未执行/失败”，不能拿某套件全绿代替该 case 的场景证据。

## 剩余工作的实际顺序

1. 修复上述快照、原子保存及投影关闭反例，并加入针对性的回归测试。
2. 完成 T010-12 的共同配置权威接线，随后完成 T010-08 无 Profile 路径、T010-09 connector 归属，以及 T010-13/14 公共消费者迁移。
3. 完成 T011-02/03/04：持久请求及条件提交、首次与已有会话分流、配置/输入/原生结果分记。
4. 完成 T011-05/06/07/09：只读恢复、输出期不打断、三品牌受控切换隔离、跨库真实 kill 窗口。
5. 完成 T012-03/04/09/10/11/12 的剩余聚合和干净发行产物验证；修正证据映射与交接清单，收口三个脏文件。
6. 在受控链通过后，再进行获授权的 T011-08、T012-05、A108/A111 真实三品牌和 Electron 操作验收。

普通实现顺序、CSS 布局、迟到结果的单调围栏不应转嫁成用户阻塞。真正改变公开契约、默认装配行为的选择需按已冻结方案核对后再提出；系统安装、真实模型调用和真实数据迁移仍须明确授权。

## 交接记录质量

`tasks.md` 当前实际为 106 勾 / 23 空，而最终报告写 101 勾 / 28 空；011 实际有 9 任务，报告写 1/7。部分证据日期写成 2026-01-04。需要统一任务、状态和报告，但勾选率不是产品完成率。
