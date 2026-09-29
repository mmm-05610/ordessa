# P-B report — memory 域（mem0 自托管补缺，015）

日期：2026-09-28。树 `worktrees/015-b-memory`，分支 `codex/015-b-memory`
（基线 = main + merge `codex/plugin-model-provider` @ `20085c0198` + merge
`codex/plugin-prompts` @ `3eded375ec`，即派出时两支最新实态；HEAD 起点 =
`3eded375ec`）。

**终态一句话**：`plugins/assets/memory` 叶子插件全量落地——八品牌 facet
`assets.memory` 进真实 C2（重叠注册拒/版本区间拒 conformance 绿）、置备器
（Docker/compose v2 检测【本机无 Docker 实测 unsupported 诚实路径】/.env 随机
密钥/双服务 compose 子栈/版本 pin+SHA）、生命周期（备份先行升级/卸载保留数据）、
bundled provider 解析（AR-2 反例：仅自定义端点→诚实 unsupported，绝不冒充
openai）、捕获与注入管线（假 mem0 REST 门面下全链绿 + 失败反例）、第三方标注
四处、**E2 实测定论：`POST /configure` 传 `openai_base_url` 生效**（pin SHA
的真 server + 假 OpenAI 兼容端点 A/B 实测，转录
`P-B-configure-probe-transcript.json`）。整体 **PARTIAL（诚实口径）**——AR-3
事件面缺失（已按登记报回）、AR-4 注入挂点未落地（compile 拒绝即登记的缝）、
Docker 前置缺失使 compose 全链与 POST /configure 的 compose 路径未在本机走
（改用 uvicorn 直跑 pin checkout 的受控探针完成实测），真实抽取仍默认关、
开启须显式授权且另受 E3 约束。

## 0. R0 基线

- 工具链：Python 3.12.14（本树本地 `.venv`，gitignored），与 `docs/baseline.md`
  钉定一致；Node 未动（本包无 JS/TS 面）。
- 安装序列（R0 实测）：lockfile → `-e packages/pacthold packages/server-plugin-api
  plugins/harness/api plugins/harness plugins/runtime-compat plugins/server-compat
  plugins/workspace plugins/assets/{sandbox/{api,backend,adapters},
  permissions/{api,backend,adapters},model-provider/{server,adapters,
  profile-contribution},prompts,memory}` → `-e products/server plugins/server`。
  顺序坑同 014 报告 §R0（pacthold_runtime_compat 须先于 harness；sandbox/
  permissions 系须先于 products/server——S-10 清单，本树第一手复现）。
- **本包套件 128 passed**（全绿，`pytest plugins/assets/memory/tests`）。
- 基线回归（同树同 venv，本包动工后复跑）：model-provider **189 passed**
  （唯一例外：profile-contribution 的 test_profile_glue 不可收集——其消费的
  `ordessa_profile` 在 profile 分支，不在本树基线，属基线限制非回归）；prompts
  **149 passed**。本包 git 零触碰他域文件（`git status` 可核）。

## 1. 提交链

| 提交 | 内容 |
| --- | --- |
| `773db1eb08` | MB-1..MB-9：包全量（13 源模块 + 10 测试文件，128 测试）+ report + E2 转录/原始请求日志，29 文件 +3896 行 |

**终提交 SHA**：`773db1eb08`（分支 `codex/015-b-memory`；派工单原文写新支名
`codex/plugin-memory`，实际工作树按派出方建树命名为 `codex/015-b-memory` 并已
携带基线合并——沿用现分支，不另开新支）。

## 2. MB-1 域骨架与 facet 注册进 C2

- 包结构：`plugins/assets/memory/{pyproject.toml,README.md,THIRD-PARTY-NOTICES.md,
  src/ordessa_memory/*,tests/*}`；dist `ordessa-memory 1.0.0a1`，依赖仅
  `ordessa-harness-api==1.0.0a1` + `ordessa-server-plugin-api`（零产品依赖，
  mem0 上游代码不入仓、不入依赖）。
- facet `assets.memory`：单原子 item（memory 绑定），键 = `enabled`/
  `budgetTokens`/`extractionModelRef`/`boundBrands`。前三键与 P-A
  `assets.runtime-preferences` memory item **逐字镜像**（AR-5 契约；两侧测试
  各自钉住字面——跨包 import 被边界测试禁止）。默认值：挂载四家无原生记忆品牌、
  抽取关（真实模型调用默认关，红线 3）。
- C2 注册：八品牌适配器（`assets.memory.{brand}`）经插件声明面进真实点
  `harness.configuration-adapters`（`plugin.build()` 的 ContributionBatch）。
  conformance 门形照 model-provider:80-103（只仿形制不 import）：
  真实 `HarnessContributionRegistry` 重叠注册拒、同 harness 版本区间重叠拒、
  不相交区间后继接受（`test_adapters_conformance.py`，31 门）。
- profile 记忆绑定预设 item：`facet.facet_registration_manifest()` /
  `editor_registration_manifest()`（`ProfileContributions.forScope().addEditor(...)`
  的消费形状，profile-v2 契约 §2）。**Profile 侧实际注册是 Profile 域的动作**
  （profile-api v2 不在本基线），登记为待接缝。
- C2 语义的诚实裁定（模块头注 + 测试钉住）：memory 绑定在现基线**无 harness
  可写目标**（FieldClaim 闭合词汇 file/directory/environment 无 instruction
  槽类）→ descriptor claims 为空；`assess` 空探测=unknown、挂点缺席=unsupported
  （带 AR-4 原因，红线 5）、挂点在+品牌在绑定集=supported（原生记忆品牌附
  “并存可能重复”注记）；`compile` 诚实拒绝（INVALID_FRAGMENT 先行，再
  CAPABILITY_UNSUPPORTED 指明 in-domain 消费路径 `memory.binding.set`）。
  **该拒绝就是 AR-4 落地时要回访的缝**，不是静默 no-op。
- 错误码自发布：5 个 `MEMORY_*` 码经 `wire.error-families` 贡献（model-provider
  形制）。

## 3. MB-2 置备器

- **Docker/compose v2 前置检测**：`docker --version` + `docker compose version`；
  缺失=类型化 `ProvisioningUnsupported`（精确到缺失件+“不用本地假实现冒充”）。
  **本机实测**：无 docker 二进制，unsupported 路径第一手走通
  （`test_missing_docker_binary_is_honest_unsupported`）。
- **.env 生成**：`POSTGRES_PASSWORD`(token_urlsafe(24)) / `ADMIN_API_KEY`(32) /
  `JWT_SECRET`(48) 全随机；`MEM0_TELEMETRY=false` 强制（上游默认 true，F7——
  测试断言生成文本不含 `MEM0_TELEMETRY=true`）；`AUTH_DISABLED=false`；端口
  取产品 PortPlan（**无默认值**，上游文档端口 8888/8432 不出现在代码；测试钉
  端口回写一致）；文件 0600、写进 data-root `deploy/`，拒绝写入插件源码树。
- **compose 子栈**：字节稳定渲染（golden），恰两服务——postgres
  （`pgvector/pgvector:pg17`、绑定挂载 data-root `postgres-data/`、健康检查）
  + mem0 server（build context = data-root `vendor/mem0` pin checkout、
  env_file=生成的 .env、环境里再显式 `MEM0_TELEMETRY=false`、端口仅绑
  127.0.0.1）；**dashboard 不起**（REST 管理）；数据/历史全部 data-root。
- **版本 pin + SHA**：`common.MEM0_GIT_SHA = 94c3fe9f238f3dbf29c9ce98643bd71eb13077cd`
  （main @ 2026-09-28，Python SDK 2.2.1 发布提交）+
  `MEM0_SERVER_MAIN_SHA256`（pin 的 `server/main.py` 首手 sha256，测试对
  首手 checkout 复核）；`ensure_vendor` 克隆到 data-root 仓外、写 VENDOR_SHA、
  异 SHA 拒绝不静默换版。上游代码零拷入本仓。

## 4. MB-3 生命周期

- provision（检测→vendor→密钥→.env+compose）/ up / stop / ps / health
  （REST `/docs` 探活，dispatch 指定）/ upgrade（**先备份**：`pg_dumpall` 经
  compose exec 落 data-root `backups/`，备份失败拒绝升级——测试断言
  dump < stop < up 顺序）/ uninstall（`down --remove-orphans`，**数据目录与
  .env 保留**——测试断言 PG_VERSION 幸存）。
- 密钥不落仓不进 Profile：admin key 只存在 data-root .env，客户端用零参
  getter 调时取用；`read_admin_key` 从 .env 现读；隔离测试扫描包树证明生成
  密钥零泄漏。

## 5. MB-4 LLM 接线（AR-2）

- `model_provider.catalog` provided port（`requires=("ordessa.model-provider",)`
  访问授权；duck-typed，零 import）。bundled 判定=provider 名 ∈
  {openai,anthropic,gemini}（LLM）/{openai,gemini}（embedder）——与 pin server
  的 `BUNDLED_*_PROVIDERS` 逐字一致（E2 B6 步 `GET /configure/providers`
  实测核对）。anthropic LLM 自动从 openai/gemini 行取 embedder。
- **AR-2 失败反例**：仅自定义 OpenAI 兼容端点（provider 名 `acme`）→
  `WiringUnsupported("当前无可用 bundled provider…")`，记忆保持关闭；
  绝不把自定义端点塞 OPENAI_API_KEY 冒充 openai（测试钉）。
- **POST /configure 实测定论（E2，第一手）**：**生效**。pin SHA 真 server +
  假 OpenAI 兼容端点 A/B 对照：configure 前注入请求走默认 api.openai.com
  （502，假端点零请求）；`POST /configure` 下发 `openai_base_url` 后，同调用
  的 chat/completions 与 embeddings 请求以配置中的 model/base_url 出现在假
  端点。实现侧 `llm_wiring.configure_payload` 只对 openai 写
  `openai_base_url`（源码证据：pin 的 `mem0/llms/openai.py:51` 读
  `config.openai_base_url`）；GET /configure 回读可见且 api_key 被 [redacted]。
  转录：`P-B-configure-probe-transcript.json`（A/B 六步 + 附带发现）+ 原始
  逐请求日志 `P-B-e2-fake-endpoint-requests.jsonl`。
- 实测附带发现（已入转录）：pgvector 连接池在 `Memory.from_config` 急切
  连接——server 硬依赖活 Postgres；`require_admin` 的 admin key 路径查
  users 表——未跑 alembic 迁移时 configure 500（官方 compose 启动命令含
  `alembic upgrade head`，本置备器 compose 走官方 Dockerfile 等价覆盖）。

## 6. MB-5 捕获管线（AR-3）

- **AR-3 实测结论（第一手）**：`plugins/agent/contracts`（agent.ts）暴露的是
  UI 快照 store（`AgentClient.subscribe(listener)` 的变更通知 +
  `AgentSnapshot`），**无服务端“轮次完成/会话结束”事件面**可被插件消费；
  sessions/conversation 包同为视图层。**按登记报回，不改 agent 域**。
  需要的最小事件形状已随包给出：`events.TurnEvent`（profileId/sessionId/
  turnId/userText/assistantText/sessionEnded）+ 文档化端口名
  `agent.turn_events`（`subscribe(listener)->unsubscribe`），供事件生产方
  未来对答。
- 缺席语义：捕获源缺席=可诊断状态（`memory.status` 的
  `capture.source={state:"absent",note:"AR-3…"}`），捕获停止、**注入照常**
  （读旧记忆），不因捕获失败阻断会话。
- 门序：源绑定→绑定启用→品牌在绑定集→**显式授权**（默认关，授权状态可诊断
  `extractionAuthorized`；`memory.extraction.authorize` wire 方法显式开）→
  栈可达。每格拒绝都有可诊断 reason（`capture-blocked` 诊断行）。
- 受控测试（E2，假 mem0 REST 门面）：轮次→durable 队列（SQLite，
  cap 500 防漏）→flush 请求形状断言（`POST /memories` 的 messages 对 +
  `user_id=ordessa:{server_scope}:profile:{profile_id}` 命名空间）。
- **失败反例**：端点 500 → 记录在队、不抛异常、会话路径零扰动；
  不可达同；事件处理器抛错→该事件丢失、错误入 `source_status`，源与源订阅
  方不倒。

## 7. MB-6 注入管线（AR-4）

- 产出：`<memory-context facet="ordessa.memory" source="mem0 self-hosted">`
  块，逐条 `•` 行；字节稳定 golden；控制字符折叠、`&`/`<`/`>` 转义（记忆
  正文不能伪造标签或提前闭合块）；budgetTokens×4 字符截断（`…` 标记）。
- AR-4 对齐（登记为准）：合并顺序=指令在前、记忆块在后（api-requests.md
  AR-4 行）；转义如上；**块自足**——prompts facet 缺席时块照常产出（反例
  绿），两侧皆缺→空串，instruction 槽不产空壳（反例绿）。**合并挂点本身是
  prompts 域 instruction facet merge（八家 EXT），不在本基线**——挂点缺失
  如实登记：本包的 C2 `compile` 拒绝（§2）即该缝的显式标记。
- 挂载默认：无原生记忆四家（pi/dsh/qwen/kilo）默认挂载；有原生四家默认不挂
  （`boundBrands` 可改，改挂处一律携带“与原生记忆并存可能重复”注记——
  C2 assess reason 与注入面 `coexistenceNote` 双暴露）。
- 缺席≠错误：server 未置备/不可达/500 → 空块+reason（诊断可查），会话照常。

## 8. MB-7 第三方标注（四处）

`common.ATTRIBUTION = "记忆引擎 mem0（Apache-2.0）· 本地自托管（Docker）·
遥测已关闭"`，四处：

1. **诊断**：`memory.status` 顶层 `attribution` + `telemetry:"disabled"` +
   `deployment:"本地自托管（Docker）"`（测试钉）。
2. **设置页/编辑器**：`facet.editor_registration_manifest()` 的 `note` 与
   `attribution` 字段（profile 域编辑面渲染该清单）+ `memory.binding.get/set`
   响应内嵌 `attribution`。
3. **记忆查看界面**：`memory.memories.list` 与 `memory.injectionBlock` 响应
   内嵌 `attribution`（前端渲染消费）。
4. **THIRD-PARTY-NOTICES.md**：包根文件（mem0 Apache-2.0、pin SHA、上游代码
   不入仓的 vendor 机制、pgvector 镜像、遥测关闭声明）。
- 物理设置页 DOM 归 profile/前端域渲染（本包无 UI 面）——清单与响应字段
  已就位，组合验收（IR-3）在并合分支复核可见性。

## 9. MB-8 边界测试（择要）

- 数据目录在 data-root：memory.db/.env/compose/postgres-data/history/backups
  全在 `<data_root>/memory/**`；写 .env 拒绝源码树（测试）。
- 两 profile 命名空间隔离：管线级（假 mem0 记录 user_id 逐轮核对）+ **E2
  上游侧第一手**（B5 步：同查询词 p1/p2 各自只见己方事实）；server scope
  参与命名空间（同 profileId 不同 Server 不同域）。
- 服务停止/断网=缺席非错误：注入空块+reason、health `reachable:false`、
  捕获入队等待，全程零异常出面（测试）。
- 无凭据入库：生成密钥对包树全文件扫描零命中；.env 0600 且仅 data-root；
  wire 面与 configure 载荷只载引用不载内容（测试钉）。
- 基线回归数字见 §0（model-provider 189 / prompts 149 / 本包 128 全绿）。

## 10. known-issues 登记清单（物理登记归主会话，本报告为账）

写入面限 `plugins/assets/memory/**` 与 `specs/.../reports/`，`docs/known-issues.md`
不在本包写入面。以下条目已如实成形，**请主会话/集成波次转登**：

| Issue | Class | Notes |
| --- | --- | --- |
| memory 域运行前提 Docker/compose v2；本开发机无 Docker | Untested scope | 置备器 unsupported 诚实路径已实测；compose 全链（up/备份/探活/官方 compose 路径的 POST /configure）未在本机执行，探针以 uvicorn 直跑 pin checkout 等价完成（偏差与理由见 §5/转录） |
| mem0 server 硬依赖活 Postgres（pgvector 连接池急切连接） | Upstream fact | initialize_state 仅告警；update_config 与 /memories 即失败。置备器 compose 的 service_healthy 依赖顺序正确且必要 |
| POST /configure 在未跑 alembic 迁移时 500（require_admin 查 users） | Upstream fact | 部署必须先 `alembic upgrade head`；官方 compose 启动命令已含，本置备器走官方 Dockerfile 等价覆盖 |
| mem0 上游 requirements 的 mem0ai 约束为 `>=0.1.48`（非精确 pin） | Upstream fact | 本包 pin=git SHA（vendor checkout）+ server/main.py sha256；镜像内 mem0ai 解析版本随上游约束漂移，Upgrade 流程以 vendor SHA 对齐为准 |
| AR-3：agent 域无服务端轮次/会话事件面 | Gap（已登记报回） | 最小事件形状 `TurnEvent`+端口名 `agent.turn_events` 随包交付；捕获源缺席=可诊断状态，注入不受影响 |
| AR-4：instruction 槽 facet 合并挂点未在本基线 | Gap（EXT 落地前） | C2 compile 诚实拒绝+`memory.binding.set` in-domain 路径；块自足性/空壳语义已测试钉住 |
| Profile 侧 facet/编辑器实际注册归 profile 域 | Gap | 清单（facet_registration_manifest/editor_registration_manifest）已就位待消费 |
| 真实抽取/embedding 默认关；本批全部受控测试走假端点 | E3 边界 | 显式授权（`memory.extraction.authorize`）+bundled provider 双门；开启后的真实调用另须 E3 授权 |

## 11. 未决项与原因

| 项 | 状态 | 原因/去向 |
| --- | --- | --- |
| compose 全链实跑（up/备份/官方镜像构建） | 未执行 | 本机无 Docker（第一手实测 unsupported）；置备器逻辑经 FakeRunner argv 级全测；待有 Docker 环境按 report §3/§4 复跑 |
| 官方 compose 路径的 POST /configure | 以 uvicorn 直跑 pin checkout 完成实测 | 同上；实测偏差在转录 environment 字段声明 |
| AR-3 事件生产方 | 缺失，已报回 | 归 agent 域后续波次；本包给出最小契约 |
| AR-4 合并挂点 | EXT 未落地 | 归 prompts 域八家 EXT；本包 compile 拒绝即缝 |
| Profile facet 注册/编辑器挂接 | 待 profile 域 | 清单就位 |
| 真实模型调用（抽取/embedding） | 未执行（默认关） | E3：须显式授权+成本scope，且仅 bundled provider |

## 12. 完成定义对照

- report.md 齐全：本文。
- 任务全勾或如实标注：见下表——无未声明的折扣。
- 组合验证：归 integration-request（IR-1..5），单包未做（凭据指针已留给
  IR 各条）。

## 13. 任务勾选对照（tasks.md MB-1..9）

| 任务 | 勾 | 证据 |
| --- | --- | --- |
| MB-1 | ✅ | §2；tests/test_adapters_conformance.py（31）、test_facet.py |
| MB-2 | ✅ | §3；test_provisioning.py（Docker 检测本机第一手 unsupported、.env、compose、pin） |
| MB-3 | ✅ | §4；test_lifecycle.py（备份先行、卸载保留数据、密钥不落仓） |
| MB-4 | ✅ | §5；test_llm_wiring.py + E2 转录（POST /configure 生效实测定论） |
| MB-5 | ✅（AR-3 缺席如实登记） | §6；test_capture_pipeline.py、test_mem0_client.py |
| MB-6 | ✅（挂点缺失如实登记） | §7；test_injection.py |
| MB-7 | ✅ | §8；标注四处 + test_facet/plugin_surface 断言 |
| MB-8 | ✅ | §9；test_isolation.py + E2 B5 步 |
| MB-9 | ✅ | 本文 + known-issues 清单（§10，物理登记归主会话） |
