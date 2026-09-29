# P-B report — model-provider 真实应用链（三品牌，014）

日期：2026-09-28。树 `worktrees/014-b-model-provider`，分支
`codex/014-b-model-provider`（基线 = main `491aa92392` + merge
`codex/plugin-model-provider` @ `245cd0f9ec`；PB-6 起 merge
`codex/014-a-profile` @ `fcf588b3d4`，消费 profile-api r2）。

**终态一句话**：C2 注册经本包声明面进真实点、C4 绑定+一次性 permit 生产
闸门、13 码 wire families 自发布、三品牌 E2 受控矩阵 **25 格全绿**（下游
实际路由证据）、Profile glue 接真实 profile-api r2、S-08①② 清单与金样
交付。整体 **PARTIAL（诚实口径）**——生产级 admission（S-06/P-E 未翻
转）、真实 CLI 装载（E3 禁跑 + codex/claude 二进制缺席）、产品装配归外部
依赖，不冒充完成。

## 0. R0 基线重建（PB-1；旧计数作废重测）

- 工具链：Python 3.12.14 / Node 22.22.1，与 `docs/baseline.md` 钉定一致。
- 安装序列（冻结，R0 实测；P-A 报告 §R0 的顺序坑在本树原样复现）：
  1. `pip install -r apps/server/lockfiles/server-linux-py312.txt`
  2. `pip install -e 'packages/pacthold[dev]' -e packages/server-plugin-api -e plugins/harness/api`
  3. `pip install -e plugins/assets/sandbox/{api,backend,adapters} -e plugins/permissions/{api,backend,adapters}`（**必须先于 products/server**，否则 pip 从 PyPI 找 0.1.0 必红——本树第一手复现）
  4. `pip install -e 'apps/server[dev]' -e 'plugins/harness[dev]' -e plugins/workspace -e plugins/runtime-compat -e plugins/server-compat -e products/server -e plugins/assets/model-provider/{server,adapters,profile-contribution}`（S-10 清单；PB-6 合并后追加 `-e plugins/profile`）
  5. imports 冒烟：`pacthold/server_plugin_api/ordessa_harness_api/ordessa_server/ordessa_harness/ordessa_server_product/ordessa_model_provider*/ordessa_profile` 全过
- npm：`npm ci` 实测红（根 lock 缺本包两个 workspace 条目）→ 本地
  `npm install --no-save`（根 lock 零改动），已回填 **S-02**。
- **R0 四套件计数（合并后、PB-2 动工前实测）**：Python **137 passed**
  （server 87 + adapters 37 + profile 13）/ desktop vitest **10 passed** /
  chat vitest **21 passed**（旧分支 alias 不解析问题在新基线消失，验证之）/
  contracts `tsc --noEmit --strict` exit 0。根 `package.json`/`package-lock.json`
  零改动（git status 空）。
- **消费 SHA（ancestry 实证）**：foundation =
  `910457d04e`（server-plugin-api consolidation，`wire_shape` 等）+ `4bba5f1c71`
  （runtime-compat consolidation）；chat-api = `ab9cb22bff`；harness-api/C4 =
  `edca4049b1`。四者均经 `git merge-base --is-ancestor` 实证为 HEAD 祖先
  （经 main `491aa92392` 的 consolidation 历史在位；011 时代的
  `8844c475bc`/`54ad26c15d` 在重基线上不再是祖先——消费关系以内容引入提交
  为准，已核实）。
- **S-11 核实**（第一手）：`wire-port.ts` 交付在 core 分支
  `codex/013-b-server-runtime @ 742389c2e6`（源码直读：三态 `WireResult`、
  `AbsentWirePort` 在案），**不在 main、不在本树**；R0 只完成存在性/形状核
  实，生产绑定归 INT-01。已回填 S-11 注记。

## 1. 提交链

| 提交 | 内容 |
| --- | --- |
| `d1cc14ee60` | PB-2：C2 注册落地（bridge 薄桥 + 插件声明面 + 真实 registry 重叠拒；43 adapters） |
| `ca85ef584d` | PB-3+PB-4：C4 绑定 submit permit + 13 码 error families（server 113） |
| `b37e846fdb` | PB-5：三品牌 E2 矩阵 25 门（全包 184） |
| `fcf588b3d4` | PB-6 消费：merge `codex/014-a-profile`（profile-api r2，implementationSha `e6f720d347d3258bfb795c12ee703676c24ca24f`；seams/tasks 共享文档冲突按 A 侧收口态取齐） |
| `79f4bdf391` | PB-6：Profile glue 接真实 FacetRegistry（全包 192；profile 侧 152 同树绿） |
| `4db11759c6` | PB-7：S-08①② 退役清单 + 金样一致性钉扩到注册路径（197） |

**终提交 SHA**：见本报告末行（tasks.md PB-8 勾选提交）。

## 2. PB-2 C2 注册（三品牌进真实点）

- **类型对齐**：`adapters/bridge.py` 把 011 时代本地 typed 面
  （types.py 自写）翻译到 harness-api 真实类型
  （`ConfigurationAdapterDescriptor`/`Assessment`/`IntentSet`/`Match|Mismatch|VerificationUnknown`）；
  方向 adapters→harness-api 单向（pyproject 依赖 + conformance 边界测试
  双重钉住）；brand 模块一字未动（语义 conformance 已锁）。
- **声明面**：`adapters/plugin.py` `ModelProviderAdaptersPlugin` 经本包
  ContributionBatch（open_points）把三品牌进 `harness.configuration-adapters`；
  **products/server 组合零改动**（装配归 core S-03，S-08① 之后）。
- **真实 registry 复验**：重叠注册拒（adapter_id 重复→`adapter_id already
  registered`）、同 harness 版本区间重叠拒、不相交接受——全部走
  `ordessa_harness.contributions.HarnessContributionRegistry` 真实
  stage/commit（不再是本地 stand-in）；host 级 MP-11 见 PB-5。
- conformance 注册段（旧 :80-103 门）改真实 registry 驱动，保护面只增不减
  （规格驱动改写，理由=派单点名真实 registry）。

## 3. PB-3 C4 绑定与 submit permit（MP-05 生产闸门）

- `server/harness_binding.py`：`ConfigurationServiceHarnessPort` 把
  `HarnessConfigPort.apply/read_back` 从 `testing.FakeHarnesses` 换绑真实
  `ConfigurationApplicationService`——plan→`apply(plan_id, operation_key,
  submission_permit)`→adapter verify→read-back 全链；同 choice 复用同 plan
  （C4 journal 一 key 一 plan 纪律）。
- **受控级全绿**（E2 证据，`test_harness_binding.py`）：一次性 permit 下
  三品牌 apply→Confirmed+`verification_evidence_ref`+下游路由真变；
  重放回耐久结果零新效果；过期 permit 拒；跨会话 key 隔离；效果后失联
  →`unknown-outcome` 阻塞。
- **生产级诚实分层**（不混写）：无 permit source（S-06 admission 未翻转，
  P-E 未交）时**每个 apply 都在原生效果之前被拒**
  （`AUTHORIZATION_REFUSED`/"submission permit refused"，`apply_count==0`、
  零 endpoint 流量）——测试断言在案，报告口径=生产级 refused/unknown 待
  S-06，**不报绿**。
- 秘密边界：credential 携带 choice 编译为 BindSecret→C4 物化层
  fail-closed 拒（"secret or action requires separate controlled
  executor"）——plan 前拒绝，零耐久痕迹（MP-10）。

## 4. PB-4 wire error families（REQ-Z3-7 本包自解）

- `plugin.py` `_ERROR_FAMILIES`：api-requests.md REQ-Z3-7 的 13 码→family
  清单**逐字**自发布（`wire.error-families` 开放点，owner=宿主注入的
  `ordessa.model-provider`）。
- 门（`test_error_families.py`）：激活后 13 码经 `family_for` 全部解析正确
  （无 UNAVAILABLE 冒充）；停用随 owner 回滚；**反例**：第二 owner 异族
  冲突→整批 stage 拒且首 owner 行存活；静态表矛盾拒；未知码仍 UNAVAILABLE
  （发布不掩盖）。
- 011 的 REQ-Z3-7（原 OPEN，owner=C0 host 文件）就此**由本包自己解决**
  （派单首要认知第三条）。

## 5. PB-5 三品牌 E2 受控矩阵（DONE 必要条件；25 格全绿）

E2 口径（verification.md）：受控真桥 = build_runtime 真实 host + 本包声明
面插件 + C4 plan/apply(permit) + adapter verify + **FakeEndpoint（loopback
HTTP，记录收到的 path/model/auth 存在性）**；证据=下游实际路由，配置文件
读回/option ack 不算。全序 `initialize→session/new→prompt(fake)→换
choice→必要时 resume(同 native id)→下一 prompt`。

| 品牌 | MP-03 目录事实 | MP-06 restart-resume | MP-07 失败不撒谎 | MP-10 秘密哨兵 | MP-11 C2 单 owner |
| --- | --- | --- | --- | --- | --- |
| pi | ✓ 损坏 generation 响亮拒绝非空页；unknown 不默认 supported | ✓ provider 对象单 intent 重启同 native id；模型随 session-local 切换（品牌两阶段语义保真） | ✓ 不支持协议 typed 拒+零 prompt+状态原样 | ✓ 哨兵零命中（journal/文件/流量），bind-secret plan 前拒 | ✓ host 级第二 client 必红 |
| codex | ✓ 同上 | ✓ provider 变更 restart-resume 同 thread；model-only session-local | ✓ 同上 | ✓ 同上 | ✓ 同上 |
| claude-code | ✓ 同上 | ✓ endpoint 变更 restart-resume 同 native id；model/endpoint 两件事；session/new 冒充→unknown 不确认（三品牌） | ✓ 同上 | ✓ 同上 | ✓ 同上 |

- 反例格（三品牌通用，同一文件内逐条）：`session/new` 冒充 resume →
  unknown 永不 Confirmed + reconcile 可查；双会话交错独立路由
  （comp_A=acme/mA、comp_B=acme/mB 交错 prompt 各走各）；E3 真实模型零调用。
- 证据文件：`server/tests/test_e2_brand_matrix.py`（25 测试）+
  `_controlled_harness.py`（受控基建，显式标注受控替身）。
- **诚实边界**：真实 CLI（pi 二进制在位但钉版缺席、codex/claude 缺席）
  → "真实进程 restart-resume"格三品牌均 unknown，不冒充；CLI 装载归
  装配后复跑。

## 6. PB-6 Profile glue（消费 P-A r2）

- 消费方式：**merge `codex/014-a-profile`**（合并式消费，012 规则），
  merge 提交 `fcf588b3d4`；r2 `implementationSha = e6f720d347…`（A 报告
  §1）。合并后本包 184 绿 + profile 152 绿同树互证。
- `profile_glue.py`：`ModelProviderFacetProvider` 实现**真实**
  `FacetProviderV2` 协议，`register_model_provider_facet` 经真实
  `FacetRegistry.register(v2=True)`（owner 注入）——REQ-Z3-3 的注册口由
  P-A 落地后本包正式消费；`plugins/profile` 零改动。
- 门（`test_profile_glue.py`，8 条）：真实 registry 注册/第二 owner
  `FACET_ID_CONFLICT` 拒/卸载重挂生命周期/品牌 applicability/原子 choice
  校验（MP-01 不拆分）/compile 产 ConfigIntent/`EffectiveChoiceResolver`
  会话覆盖与切换清除语义/`ProfileViewReferencePort` 活跃档案引用核查。

## 7. PB-7 退役准备与金样（S-08①②；只清单不执行）

- `specs/011-z3-model-provider/retirement-request.md`：server-compat
  `model_configs` writer **W1-W15 逐行退役清单**（行号=现行树实测；派单
  旧引 `:238-276` 已漂移并声明）；**消费者核查**（products 装配注入、
  apps/server 边界测试断言、兼容回归四件、execution 冻结面 W5 跨域引
  用）；**顺序确认**=先退 compat writer（同批含边界断言更新）→再装配
  model-provider（S-03）→两步之间无双写窗口。已回填 seams S-08①。
- **金样一致性钉扩到注册路径**（S-08② 承接方证据，conformance +5）：
  codex TOML 逐字节 ≡ harness `render_codex_provider_section`；pi 对象/
  claude env ≡ harness 金样；adapters `DIALECTS` ≡ harness
  `_FAMILY_DIALECTS`；描述符 native target ≡ harness `_NATIVE_TARGET`。
  harness 品牌渲染退役时字节事实已由本包持续守护。

## 8. 门与反例总账（派单表逐行）

| 门 | 断言 | 实测 |
| --- | --- | --- |
| 注册 | 三品牌注册进真实点；重叠必拒 | 真实 registry + 真实 host 双级 ✓（"只在本地 registry 测过"已消除） |
| permit | 无 permit 必拒；重放必拒 | 服务级 + port 级双覆盖 ✓（重放=回耐久结果，非新效果） |
| E2 矩阵 | 逐格证据 + 下游路由证明 | 25/25 格 + FakeEndpoint 实收请求 ✓；缺格不报 ready（真实 CLI 格如实 unknown） |
| 品牌语义 | 三品牌 dialect 钉不漂移 | conformance 旧钉全保持 + PB-5 端到端复验；pi 对象单 intent 形状变更=合并后 C4 数组子树纪律的规格驱动适配（金样 ≡ harness render 为证，非漂移） |
| 回归 | R0 重测全绿不回退 | 137→**197**（+60 全部新门）；desktop 10 / chat 21 / tsc 0；profile 152 ✓；新增红=0 |
| 诚实 | 生产级 vs 受控级分开 | 本报告 §3 分层 + S-06/INT-01/S-08 依赖逐条登记 ✓ |

## 9. 缺口与未测（诚实边界，不阻塞收口）

- **生产级 admission**：S-06 翻转链依赖 P-E（第二批）；本包生产路径=
  诚实 refused/unknown（已断言）。
- **E3 真实模型**：未授权未跑（禁跑项遵守）；真实 CLI 装载格 unknown。
- **产品装配实测**（extensions.json 启停、三组合、浏览器矩阵）：归接缝
  落地后的集成轮（S-01/S-03 清单已给）。
- **旧 DELIVERY/IR**：IR-1 compat 退行=S-08① 执行窗口；IR-4 像素 GUI、
  IR-5 Chat 默认对话回归等维持原归属。
- **子代理**：0 次派发（quota 环境先例沿用；lead 串行实施，单包所有权保持）。

## 10. 纪律自查

无 push、无外并 main、不动兄弟树、不 kill/restart 服务、根锁零改动、
零凭据读取（仅测试哨兵）、零真实模型调用；写入面 = `plugins/assets/
model-provider/**` + `specs/011-z3-model-provider/**` + `specs/
014-plugin-release/**`（seams/tasks 共享文档按段回填；PB-6 的 A 分支
merge 仅带入 A 的写入面文件，属合并式消费的既有内容）。

**终提交**：（本提交）
