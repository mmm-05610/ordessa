# 012 最终交接报告（无人值守 2026-01-04 夜班收口）

**执行分支**：`codex/open-environment-migration`（本实施树，未 push、未合 main、未动源产品树）
**基线起点**：`ebe712c796`（实施树冻结基线）
**夜班起点**：`779b1b1902`（overnight goal charter）
**收口时点 HEAD**：见下方 SHA 链末项（本报告提交即最终检查点）

---

## 1. 约束遵守（全程零违反）

| 约束 | 状态 |
| --- | --- |
| 不 push / 不合 main / 不动源产品树 | ✅ 未有任何远端操作；全部为本地检查点提交 |
| 不装系统资产（/opt 等） | ✅ Electron 腿仅用本地 staging（`packaging/.staging`） |
| 不碰真实数据 / 不启停用户服务 | ✅ 测试数据全为 fixture/临时目录 |
| 不调真实模型 / GUI 未验不报 DONE | ✅ T011-08/T012-05 明确 BLOCKED-待授权 |
| 不读密钥、不写真实数据、无二进制入 git | ✅ |
| 最多 2 并发子代理、测试槽串行、Git/契约/status 独占 | ✅（子代理通道 GLM-5.3-Flash 整夜宕机，按"阻塞不停滞"自任打杂） |
| 红集 stash 对照、不删断言、不 skip 求绿 | ✅ 每次可疑红均 stash 对照；apps/server 红集恒 66F+2E（登记基线逐 ID 一致） |
| U 未验永不报 DONE | ✅ 报告与账本 S/I(codeReady) 与 U(fullDone) 分列 |

## 2. SHA 链（关键检查点，时间序）

**001–006 受控基线与底座**（基线段，先前已落）：
`51889021a0` 001 → `8155d4b1a5` 002 合同冻结 → `ceca96799f` 003 → `7c94ec8140` 004 → `5baa714cec` 005 → `a84852b4c5` 006 收口

**007/008/009（夜班前段）**：
`4d2309cf99` T007-01 → `a59f47ebb3` 批1 → `98e7a4ad7b`/`3a5037117c` 批2/3 → `923c5c0445` 样例#1 → `7fe33bcd70` R7/M14 合并 → `44239ca767` F5 冻结 oe-f5/1 → `9b36143924` extension-runtime 合并 → `b147e8ae94` T008-10 → `b7d722a5c5` **008 codeReady** → `3bfa7d6e3b` E2 出口 → `4a17fa9297` F1 SurfaceAPI → `61d12fe66b` 样例#3 → `4b3011aec6` 执行域门 → `2642603c7f` call-lease → `ebbb5a53eb` **009 codeReady**

**010（夜班后段，9/14 任务）**：
`9e4d29bc2c` T010-01 五 owner 骨架 → `843abb81c7` AgentOwnerPort → `565e04fc21` 产品装配+pin 93 → `32fd7f09f4` 本地 owner 端口（dispatch 基座）→ `0c419c39a0` selections/lastConfirmed 写权拆除 → `ebadd80517` bindings/retained 写权拆除（**五写权收口**）→ `cab78790c6`+`bf848cd3e1` next-turn client/entry 写权拆除（含 H1 红首修复）→ `0345e36206` 六语义钉面 → `5d8377f21d` ConfigEvidence 链 → `1cd090ba0d` target/binding/generation 钉面 → `a3d3a9811c` 草稿四语义（**双红首修复**）→ `6bce466b43` 五 owner 公开面补全（pin 95）→ `4f66503bc7` 公开贡献证据

**011（1/7）+ 012 收口**：
`9eb7477179` T011-01 capture 事务 → `0e9939b913` 账本 → `f75f446c9c` 本报告初版 →
`85a1199cf9` T012-01/02 清点 → `45a23f1493` T012-07 docs 清扫 → `1b35fb94b9` T012-06/13
完整性+回归证据 → `a1920a9af5` T012-03 typecheck/build 绿（含四处类型缺口修复）→
`7c2ecc6f3f` T012-04 bare-host wheel OK → `ad6c38b892` T012-04 deb 生成/解包/载荷净 →（终检查点）

## 3. 勾选账（tasks.md 129 任务：101 勾 / 28 空）

| 工单 | 勾/总 | 状态 |
| --- | --- | --- |
| 001–006 | 全勾 | codeReady（S/I 完成） |
| 007 | 全勾 | codeReady（三样例+顶层化批1–3） |
| 008 | 19/20 | codeReady；**T008-04 待用户裁决**（载体三选项） |
| 009 | 全勾 | codeReady（SurfaceAPI/SDK 出口/dialog/lease/样例#3） |
| 010 | 9/14 | 01/02/03/04/05/06/07/10/11 完成；**T010-01 未勾**（主体已落，DraftOwner/通用edit 分离缺专项边界核验）；08/09/12/13/14 待续 |
| 011 | 1/7 | T011-01 capture 事务完成；02–07 待续；**T011-08 需真实模型许可（BLOCKED）** |
| 012 | 5/13+3 部分 | **已勾**：T012-01（旧引用清点）、02（包组+测试映射审计）、06（数据/秘密扫描）、07（docs 清扫）、08（本报告）；**部分有据**：T012-03（typecheck+build+Python 全绿）、T012-04（wheel/bare-host OK=30 模块 host-only + deb 生成/解包/载荷净，不签名不 publish）、T012-13（A96–A107/A109/A110 绿，A108/A111 缺授权）；**未跑**：09/10/12（发行产物逐项闭包，命令已可达）、11（E 系+守卫 177F 已绿，A66–A95 逐 ID 表待补）；**BLOCKED**：05（真实用户动作，缺授权明文不算完成） |

## 4. 夜班实质交付（按价值序）

> 012 段追加：docs 清扫（baseline 命令恢复可用、architecture/naming 路径更新、known-issues
> 新增 5 行登记）、完整性扫描（零追踪二进制/凭据）、A96–A111 逐项回归证据表、
> typecheck+build 全绿（修复夜班 TS 工作引入的 4 处类型缺口，行为零改动）。

1. **A1 单写者落地全链**：五 owner（Python）+ 双面端口（wire/local，sync 与 Python `submit_operation` 对位）+ 产品装配 + wire pin 88→93→95 命名化。前端**五处写权全部拆除**（selections/lastConfirmed/bindings/retained/clickQueues），profile/model/chat 三域状态全部 owner 化——**既有断言零改动通过**（83→88→91→93、115→117→119→120、86→88）+ 20 项结构正反例新钉。
2. **双红首语义修复**：H1（submit 在飞新 pick 被旧 tracked 误清，违 FR-04）；草稿 ABA（值比较清稿误删 A→B→A 新输入）+ view 离开仍收尾（早退跳过 settle）。修复前后红→绿全链有据。
3. **ConfigEvidence 链**（T010-05 五语义）+ **capture 事务**（T011-01 八要素深冻结）——受控全链的输入与证据侧基座。
4. **H2 观察登记**（ready 迟到回执回退 M12 序栅栏）：行为保持，三选项待裁（见待裁清单）。

## 5. 缺口（28 未勾逐项 + 原因）

**需用户授权/裁决（不能代决）**：
- T008-04 carrier 载体（三选项，建议 A）｜T011-08 真实三品牌模型两轮（缺许可/成本授权）｜T012-05 真实用户动作截图（GUI/模型缺授权，明文不算完成）｜T012-06 真实数据迁移（未获批准不许诺已升级）

**实现待续（无需用户输入，可直接开工）**：
- T010-01 余项（DraftOwner/通用 edit 合同分离专项边界核验）
- T010-08 禁用 Profile 产品矩阵 controlled 构建运行两轮｜T010-09 ACP connector 字段逐项迁移（E2）
- T010-12/13/14 公共消费者迁移（选择控件/草稿编辑页/任务通知机制）
- T011-02 可靠路径持久 request+fingerprint/reservation 后条件提交｜T011-03 create/existing 分离｜T011-04 结果分记｜T011-05 崩溃只读 reconcile｜T011-06 输出期稳定｜T011-07 三品牌 controlled 切换｜T011-09 C2 跨库 kill 窗口
- T012-01/02 旧路径清零与包组核验｜T012-03 全链构建回归｜T012-04 干净 venv wheel/deb 验证｜T012-07 docs 清扫（写权已在本单）｜T012-09/10 发行产物闭包验证｜T012-11 E3/E4/E5/A1+A66–A95 回归｜T012-12 F5 发行面验证｜T012-13 A96–A111 逐项回归

**兼容余项**（既有登记，非遗留）：legacy-compat 读取器保持 sealed 只读（`LegacyCompatReader`）；C95-1–7 退役账在 012-01/07 完成时终账。

## 6. 待裁清单（醒后一次性决定即可）

1. **H2 ready 序栅栏**（evidence/t010-03-h2-observation.md）：建议 **A**（ready 应用加单调围栏，红首测试可先落）。
2. **T008-04 载体**（evidence/decision-pending-harness-carrier.md）：建议 **A**（新 harness-contracts 载体）。
3. **agent-server 装配开关**（007/010 遗留）：是否默认启用（影响 Electron 腿 2/6）。
4. **ui-foundations CSS padding**（008/012）：品牌适配裁决。
5. **runtime-preferences 顶层化归属**（M07 冻结扁平 import 名，归属待确认）。
6. **排期**：T010-08/09/12–14、T011-02..07/09、T012 全单的优先序（建议 T011-02/09 可靠链先行，再 012-03/09/10 发行验证，最后 T010-12..14 消费者迁移）。

## 7. 可试入口（醒后即验）

```bash
# A1 单写者 + 五写权拆除全绿（88+16+120+93+21+37）
npx vitest run --root plugins/agent/contracts
npx vitest run --root plugins/profile/integrations/chat
npx vitest run --root plugins/model-provider/chat-contribution
npx vitest run --root plugins/chat/frontend
npx vitest run --root packages/frontend/workbench

# Python：五 owner + wire + capture（15F）
.venv/bin/python -m pytest plugins/agent/backend/tests -q

# wire pin 门禁（95 命名 pin）
.venv/bin/python -m pytest apps/server/tests/test_plugin_host_gate.py apps/server/tests/platform/test_platform_t023_wire_loopback.py -q

# apps/server 全量红集对照（66F+2E/1215P，登记基线一致）
.venv/bin/python -m pytest apps/server -q

# 双红首修复的最短复现（修复前红）：composer-flow H1/ABA/settle 三用例
npx vitest run --root plugins/chat/frontend -t "T010-07"
```

## 8. 运行操作步骤（下次会话接续）

1. `git log --oneline -1` 对 SHA 链末项（本报告提交）。
2. 从待裁清单取 1/2 决议（H2-A、T008-04-A 可直接实施）。
3. 实现待续段按第 6 节建议排期开工；每任务沿用：红首测试→实现→全套对照→pathspec 提交→账本。
   012 余项多为**验证执行**（T012-04/09/10/12 发行产物、T012-03 aggregate/smoke、T012-11 A66–A95
   逐 ID 表）：命令已全部可达（baseline.md 修复后），执行即可补账，无实现工作。
4. 012-07 docs 清扫（architecture/baseline/naming/reference/migration/known-issues）在实现状态稳定后一次成文（目标与实现状态分开）。
5. T012-08 本报告随进展增量更新；合 main 前必须用户批准。

## 9. 安全回退点

- **全部工作在独立分支 `codex/open-environment-migration`，每任务独立 pathspec 提交**——任何单任务可 `git revert <sha>` 而不动其他。
- 双语义修复（H1/ABA/settle）各自独立提交（`cab78790c6`/`a3d3a9811c`），如需回退行为可单独 revert（将恢复旧行为，含已知缺陷）。
- wire pin 95 是**命名集合自洽算术**——增删方法只动集合不重排。
- 无数据库迁移、无磁盘格式变更、无 wire 合同变更（oe-contract/1 冻结未动，新增面均在消费侧）。
- 本地 staging 产物（`packaging/.staging`）可整目录删除重建；无系统状态残留。

## 10. main 集成请求（用户批准前不合 main 不 push）

**请求**：将 `codex/open-environment-migration`（HEAD=本报告提交）按任务段分组 review 后合入 main。
**建议 review 序**：合同冻结（002）→ 底座（003–006）→ 007/008 前端迁移 → 009 → 010 owner 化（最大的一段，含双语义修复）→ 011-01。
**注意**：T010/T011 段含**行为修复**（H1/ABA/settle），对既有测试全部零改动通过；若 review 要求行为保持可单独 revert 这三个提交。
**不包含**：T008-04（待裁）、T011-08/T012-05（待授权）、真实数据迁移（未获批）。

---

*本报告为012-08 交付物初版（收口时点）；T012 其余项完成时增量更新。*
