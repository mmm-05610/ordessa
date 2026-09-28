# Z3 线报告 — Model-provider v2

日期：2026-09-28。分支 `codex/011-z3-model-provider` @ 本报告提交（起点 `96fef2db47`，
快照父 main `cd7d31f3cf`）。最终状态：**PARTIAL（本线可独立完成项全部完成并验证；
E2/生产闸门缺上游检查点，逐项列明）**——按 verification.md，"若上游接缝没落地，
状态 PARTIAL 并列明哪个 FR 缺真实证据；不得以设计稿、fake 或历史轮证据补绿"。

## 1. 交付概览（全部条目附 SHA）

| 阶段 | 提交 | 内容 | 证据 |
| --- | --- | --- | --- |
| R0 | `1660f66920` | T00 冻结（树/接缝/wire/钉版/R1→restart-resume 差异）+ api-requests.md | t00-freeze.md §1–9 |
| T03a | `3fa031c947` | contracts 三文件逐字迁移 | `tsc --strict --noEmit` exit 0 |
| T01 | `639fe5ef60` | server 包迁移 + 七个 `modelProvider.*` 新方法 + 13 失败码 | 先红 15F+2E → 后绿 87 |
| T02 | `b7afe1c464` | Pi/Codex/Claude 三品牌 C2 适配器（E1） | 先红 collection error → 后绿 37 |
| T03 | `fe50f4433a`+`40aaf4d6bd` | desktop 设置分区迁移（真实 Workbench composition 契约） | 10 passed |
| T04 | `e698d584a5` | profile-contribution 迁移 + 原子 facet descriptor | 先红 1 collection error → 后绿 13 |
| T05 | `6ba35dfb20` | chat-contribution 迁移 + next-turn 消费端 | 先红 exit=1 → 后绿 16 |
| 消费 chat-api | `25f726dc3e` merge `54ad26c15d` | 真实注册表接线（composer.toolbar 槽位映射已记录） | `2855c768ba`：先红 exit=1 → 后绿 21 |
| R3 | `fb01ccc179` | integration-request.md（IR-1…IR-6） | — |
| 消费 foundation | merge `8844c475bc` | `b0921009b2`：适配 Database/wire 助手搬迁，MP-12 复证 | 先红 2E+2F → 后绿 137；六形状 AST 比对全一致 |

最终全量（foundation 合并后实测，本报告同一工作树）：
Python **137 passed**（server 87 + adapters 37 + profile 13）；desktop vitest **10 passed**（exit 0）；
chat vitest **21 passed**（exit 0）；contracts `tsc --noEmit` exit 0。根 `package.json`/
`package-lock.json`/`tooling/**` 零改动（`git status` 空）。

## 2. FR→门禁实测矩阵（证据等级：E0 契约/静态，E1 本域假适配，E2 受控真桥，E3 真实模型）

| FR | 门（verification.md） | 实测 | 等级 | 缺口 |
| --- | --- | --- | --- | --- |
| MP-01 恒定身份 | 同名不串/改 harness 拒 | `SELECTION_UNSUPPORTED`（config 绑定他 harness）测试绿；原子 facet 拆分拒绝测试绿 | E1 | 会话建后换 harness 的 E2 归 T06 |
| MP-02 双来源同目录 | 明文进 UI/日志即失败 | 秘密哨兵 `test_no_credential_leak`（金丝雀证明扫描有效）绿；登录来源只读沿用 compat 投影 | E1 | — |
| MP-03 目录事实 | 失败报 error 非[]；unknown 不默认 supported | `OPERATION_UNKNOWN` 反例绿；inspectChoice 无端口→unknown 绿 | E1 | 三品牌 E2 待 T06 |
| MP-04 七态不混同 | 渲染零 outbound；手动探测有界 | desktop G6 渲染零探测绿；probeProvider 只读+observedAt 绿；probe 边界 13 反例沿用绿 | E1 | — |
| MP-05 下轮提交闸门 | 输出不打断；P 更新与覆盖并存；apply+verify 后 prompt 一次 | 排队零 apply 绿；P 更新传播/切 P 清覆盖（T04 迁移测试）绿；**apply+verify→prompt 一次缺真实 submit permit（REQ-Z3-2 OPEN）** | E1 | **生产闸门缺** |
| MP-06 受控重启 resume | A 改 B 不动；HOME 字节不变；同 native id；session/new 必红 | 适配器层：B 不动跨会话隔离测试绿；session/new 冒充 mismatch 绿；HOME 零引用边界扫描绿；**真实进程 restart-resume 待 harness-api/T06** | E1 | **三品牌 E2 全缺** |
| MP-07 失败不撒谎 | 草稿原样零 prompt；unknown 不重发 | 拒绝/unknown 终态零 prompt（迁移 11 例）绿；晚到/异会话 resolution 拒绝（T05 3 例）绿；reconcile 无端口→unknown 绿 | E1 | E2 缺 |
| MP-08 CAS/引用保护 | stale/同 key 异 payload 拒；端口缺席不归档；卸载数据在 | `CONFIG_REVISION_CONFLICT`+current 绿；`IDEMPOTENCY_CONFLICT` 绿；`REFERENCE_STATE_UNKNOWN` 绿；G3 卸载留记录绿 | E1+宿主 | 装配归 C0 |
| MP-09 Settings 独立 | 三组合可用；误依赖 Chat 必红 | G10 缺席对照绿（desktop 10 例）；依赖边界 AST 测试绿（Profile/Chat 名不可达） | E1+装配 | 产品三组合实测归 C0（IR-3） |
| MP-10 秘密零泄漏 | 哨兵扫 wire/日志/TurnFact/错误/导出零命中 | 哨兵测试绿（核心+BindSecret ref-only 扫描绿） | E1 | E2 缺 |
| MP-11 C2 单 owner | 冲突注册拒；第二 client 必红 | 重叠注册/不可证不相交拒绝绿；manifest 形状绿；**真实 C2 注册点不存在（REQ-Z3-1 OPEN）** | E1 | **注册点缺** |
| MP-12 wire/DB 保真 | 六方法同形状/错误/ID；双 owner 启动失败 | 形状门绿 + 与**现行** compat `_PARAM_SHAPES` AST 逐项比对全一致；G2 双 owner 反例绿（含新方法） | E1 | 退 compat 行归 C0（IR-1） |

## 3. 完成 / 阻塞 / 未测 三类事实

### 完成（真实证据，全部可复现）
- 本线五个包全部落地且套件全绿（137+10+21，含先红后绿记录）；无生产假接口（探测全走
  `_open_request` 假传输/loopback 反例；TS 无网络桩）。
- 六方法 + 表/ID/幂等/CAS/KEEP-null 逐字保真，并对**消费 foundation 后的现行 compat** 复证一致。
- 七个新 wire 方法 + 13 失败码 + 新 typed surface（choices.py）按冻结命名（t00 §8）实现并反例覆盖。
- 检查点消费：chat-api `54ad26c15d`、foundation `8844c475bc`（均 ancestor 核实、固定 SHA merge、
  合并后全量复跑）。api-requests.md 回填 CONSUMED 记录。
- 文档四件套齐：t00-freeze / api-requests / integration-request / report（本文件）+ 三包 README/MIGRATION。

### 阻塞（BLOCKED_INTEGRATION，逐项有 owner 与请求记录）
- REQ-Z3-1（C0 harness-api）：C2 `harness.configuration-adapters` 注册点不存在——本域 adapter
  只能以 manifest+纯函数形态交付（E1），真实注册不可伪造。
- REQ-Z3-2（C0）：`harness.configuration` plan/apply/verify + submit permit 不存在——T05 生产闸门、
  `resolve_next_turn` 生产调用不可接。
- REQ-Z3-3（Z1 profile-api）：facet 注册口/overlay 端口未发布——descriptor/校验已就绪（E1），
  实际 `addEditor` 不可注册。
- REQ-Z3-5（C0）：桌面 Server wire 传输口——已类型化拒绝兜底，production 绑定归装配。
- REQ-Z3-7（C0）：13 新失败码进 wire family 映射（host 文件 owner 面）——现走 `internalCode` 精确携带。
- 旧 DELIVERY #1/#7/#8/#9/#10：compat 退行、TurnFact 持久化、产品装配、像素级 GUI、Chat 默认对话
  回归——全部在 integration-request.md IR-1…IR-6 归 C0 集成波次。

### 未测（诚实边界）
- **E2 受控真桥三品牌**（verification.md DONE 必要条件）：Pi/Codex 无本包实测；Claude 仓内
  `provider-*.mjs` 假端点证据未按本线最终装配重跑。全部标注，不计作通过。
- **E3 真实模型**：本轮无授权，未跑（严禁清单项）。
- Windows 侧、未知品牌（仅登记 unknown/not-scoped）、产品级三组合缺席对照的 GUI 实测：归集成树。

## 4. 过程事实（诚实记录）
- 子代理派发 4 次（3 并行 + 1 单发）均被环境即时拒绝（exceed quota limit，2026-09-28）——与旧树
  DELIVERY §5 同先例；按协议「普通阻塞自行解决」改 lead 亲自逐包实现，单包所有权纪律保持
  （串行实施、每包独立提交），派单文件保留于 `specs/011-z3-model-provider/dispatch/`。
- 迁移文件唯一非逐字修改共三处，全部规格驱动并记录：`test_plugin_registration` 计数断言（6→6+7）、
  `test_dependency_boundary` 白名单（foundation 搬迁后的宿主指定叶子）、foundation 后的导入适配
  （conftest×2/records.py/plugin.py，详见 server/MIGRATION.md「foundation 消费适配」）。
- 无 push、无 merge main、不动他树、不重启服务、零真实模型调用、零凭据读取（仅测试哨兵）。

## 5. 复现命令（从仓库根，venv=python3.12）

```sh
.venv/bin/pip install -e plugins/assets/model-provider/server \
  -e plugins/assets/model-provider/adapters -e plugins/assets/model-provider/profile-contribution \
  -e plugins/runtime-compat
.venv/bin/pip install --no-deps -e plugins/server-compat
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest plugins/assets/model-provider -q   # 137 passed
(cd plugins/assets/model-provider/desktop      && ../../../../node_modules/.bin/vitest run --maxWorkers=1)  # 10 passed
(cd plugins/assets/model-provider/chat-contribution && ../../../../node_modules/.bin/vitest run --maxWorkers=1)  # 21 passed
node_modules/.bin/tsc --noEmit --strict --target es2022 --module esnext \
  --moduleResolution bundler --skipLibCheck plugins/assets/model-provider/contracts/*.ts  # exit 0
```

---

## 014 增补 — P-B：真实应用链收口（2026-09-28，分支 `codex/014-b-model-provider`）

011 的 PARTIAL 状态在此线被推进到受控级全绿；完整证据见
`specs/014-plugin-release/reports/P-B-report.md`。与 011 台账的对照：

| 011 阻塞项 | 014 结果 |
| --- | --- |
| REQ-Z3-1（C2 注册点不存在） | **CLOSED**：注册点已在 main（harness-api `edca4049b1` 经 consolidation 入线）；三品牌经本包声明面（`adapters/plugin.py`）进真实 `harness.configuration-adapters`，真实 registry 重叠拒复验（`d1cc14ee60`） |
| REQ-Z3-2（C4 plan/apply/permit 不存在） | **CLOSED（受控级）**：`HarnessConfigPort` 绑真实 `ConfigurationApplicationService`，一次性 permit 全链 + 反例四件；生产级 admission 诚实 refused/unknown 待 S-06/P-E（`ca85ef584d`） |
| REQ-Z3-7（13 码进 wire family） | **CLOSED**：由本包自己经 `wire.error-families` 自发布（派单裁定路径），冲突/静态表矛盾/未知码三反例在案（`ca85ef584d`） |
| REQ-Z3-3（profile facet 注册口未发布） | **CLOSED**：P-A r2（`e6f720d347`）落地后本包 glue 消费真实 `FacetRegistry`（`79f4bdf391`，merge `fcf588b3d4`） |
| E2 三品牌全缺 | **受控级全绿 25 格**：`initialize→session/new→prompt(fake)→换 choice→必要时 resume→下一 prompt`，下游实际路由证据（FakeEndpoint 实收）；`session/new` 冒充 resume、双会话交错、MP-10 哨兵、host 级 MP-11 全在案（`b37e846fdb`）。真实 CLI 装载格如实 unknown（E3 禁跑；codex/claude 二进制缺席） |
| REQ-Z3-5（桌面 wire 传输口） | S-11 核实：`HttpWirePort` 交付在 core 分支 `codex/013-b-server-runtime @ 742389c2e6`（不在 main/本树），生产绑定归 INT-01 |
| IR-1（compat 退行） | S-08①② 清单与顺序交付（`specs/011-z3-model-provider/retirement-request.md`，`4db11759c6`），执行归集成波次 |

测试账（R0 重测口径）：137 → **197 passed**（+60 新门，新增红=0）；
desktop 10 / chat 21 / contracts tsc 0 不回退；profile 152（合并后同树）。
REQ-Z3-6 消费 SHA 补正：011 记录的 `8844c475bc`/`54ad26c15d` 在重基线上非
祖先，消费关系以内容引入提交为准并已 ancestry 实证（`910457d04e`/
`4bba5f1c71`/`ab9cb22bff`/`edca4049b1`，见 P-B 报告 §0）。
