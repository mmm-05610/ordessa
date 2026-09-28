# Q4 — MCP 定义与托管：交付报告

日期：2026-09-28（晚）。线：`codex/011-q4-mcp`。分工执行：主代理派单包写包代理实现/改测试，逐批审差分、复跑验证、维护文档与 git；全部数字为本树实测退出码。

- 起点：`96fef2db47`（父 main `cd7d31f3cf`）
- 检查点消费（publication SHA，正常 merge，详见 checkpoint-consumption.md）：
  foundation `8844c475bc02a185ab194c69eed873122aa48349` → merge `837a915723`；
  profile-api `4943628f47ab65dc08c060beff973adfaa4ab58b` → merge `29f4538e5d`（组合不兼容，已路由 Z1）；
  chat-api r3 `3d8c3fa410cd898a44c682b74458cc8f41ef7489` → merge `81edcca3dc`；
  permissions-api `bcd4387becc3c29b6786efa7bff822f430ea0460` → merge（T06-wiring 批）；
  harness-api `d3f026904ead6c7ce58df26f2536175ce6179de7` → merge `810ef8095a`。
- 交付 commit 链（本线阶段提交）：`e00311dbcd`(R0) → `f382aceecf`(T01/T02) → `02e4175f13`(T03+研究) → `1553fbfbe3`(T05–T07) → `d534d89db5`(消费账) → `29f4538e5d`/`81edcca3dc`/`810ef8095a`(消费) → `3fea4e5569`(T08/T09-service) → `9d6c89e273`(T06 真实接线) → `964bea3937`(T05 client L2) → `1636310405`(T04-L1/迁移) → `49dfa61522`(converge) → `f1d8478f7a`(T011) → `bbc36849b1`(T013) → `1e7f3733c7`(T012/T014)。

## 一、完成（有真实证据）

| 范围 | 证据（报告/测试） | 证据等级 |
| --- | --- | --- |
| T01 定义/修订：legacy 字节互证（digest/布局/0o644/错误文本逐字对照真实 legacy 模块）、literal/secretRef 类型化、CAS、不可变修订、旧摘要采纳不重算 | reports/t01-t02.md，V01 17 例 | L0/L1（+与 legacy 互证） |
| T02 四类作用域分配与解析序、批准修订、工具子集冻结、catalog 漂移 needs-revalidation、跨 principal/scope 冒领拒 | 同上 V02 13 例 | L0/L1 |
| T03 受控 probe：stdio/HTTP、版本协商（按服务端回值）、取消、进程树（子+孙）回收、大帧/假响应/超时/401/redirect/TLS、无凭据单列、绝不声称 catalog | reports/t03.md 49 例 | L2（loopback fake） |
| T05 受管域：lease 状态机+六级事实、唯一 owner、native/managed 互斥、close/drain/unknown-reconcile、catalog 观察与漂移失效、无池化 | reports/t05-domain.md 51 例 | L0/L1 |
| T05 受管 client：限定替代 stdio 最小 client（协商/门序/UNKNOWN_OUTCOME）+ T011 Streamable HTTP client（瞬时授权 header、明文哨兵扫描、远端 not-owned） | reports/t05-client.md 17 例、t011-http-client.md 33 例，含服务端零收到 tools/call 反例与变异审计 | L2（受控 fake server） |
| T06 双门 fail-closed + 真实 permissions-api 接线（AllowedOnce/Pending/Denied/过期/跨主体；admin ceiling→policy_denied provider） | reports/t06-wiring.md 23 例，真实 ordessa_permissions_backend+合成 DB | L1（受控真件） |
| T07 credential glue：plan 绑定 revision、轮换整批 stale 拒、secret_store 缺席 fail-closed、脱敏 repr/扫描、零落盘明文 | reports/t06-t07.md 61 例 + T011 集成例 | L0/L1 |
| T04 native intent：纯函数 assess/compile/verify、明文不可能、冲突拒、projected≠loaded；T013 接真实 harness-api C2/C4（ConfigurationAdapter 真注册验证、planForSubmission 唯一提交闸门、受控链 compile→merge→plan→apply→verify，服务落 Unknown 不冒充 Confirmed） | reports/t04-adapters.md 63 例、t013-harness-wiring.md 55 例（链级 L2；**supported 未翻转，无 L3**） | L1/L2 |
| T08 前端：Settings section（六级文案/secretRef 只读缺席语义/独立批准动作）+ chat-api r3 输入区小面板（真实贡献注册-查询-撤销路径） | reports/t08-frontend.md，vitest 31 例+tsc+build exit 0 | L1（in-memory fake wire） |
| T09 Q4 侧：mcp.* 12 descriptors 经真实 ServerPluginHost 激活 roundtrip；迁移工具 scan/migrate/dry-run/查询等价逐项钉，legacy DB 字节冻结 | reports/t09-service.md 30 例、t09-migration.md 19 例（真实 Database/AssetRecords/McpAssetStore 合成样本） | L2（受控真宿主件） |
| T10-Pi 桥：受管扩展桥（loopback 一次性 token、Server 校验目录、双门转发、close 清理）+ 真 pi 0.86.1 CLI 离线隔离 HOME 探针：加载/登记/拒绝/清理格 **observed（L3 非生产闭包）**；tools/call 格 L2（需 provider 凭据，如实 unknown）；信任批准/正式装载面登记 G9 | reports/t10-pi-probe.md 29 例 + 真机 witness | L3(局部)/L2(调用) |
| T00-V00 ACP 入口探针：钉版 codex-acp 1.1.14（tgz sha/lock integrity 核对）与 claude-agent-acp 0.81.2 的 `session/new.mcpServers` 消费**实证**（注入面 CODEX_PATH / CLAUDE_CODE_EXECUTABLE、逐帧 witness、`[]` 负控、双会话不串、adapter 不代连、静默丢弃坑与 `-32602` 形状契约） | reports/t00-acp-probe.md（rc=0 双品牌） | L2（adapter 行为；真 CLI 装载未证不升格） |
| T10-整合链（服务层跨域，产品装配前最大可证链）：真 host dispatch→真 C4 ConfigurationService→真 managed client→loopback fake MCP→真 Q5 权限双门→close/drain/unknown/双会话/六态事实格，18 例全 witness 计数断言；暴露并最小修复 start_connection factory-fault 不落 refused 的真缺陷（变异审计有账） | reports/t10-integration.md | L2（真件组合链） |
| T012/T014：76 码封闭词表+compat 零重叠守卫（真实 import 对照）、NativePermissionPosture 标注面（posture≠授权） | reports/t012-t014.md 28 例 + 变异审计 | L0/L1 |

全线套件：`plugins/assets/mcp` **461 collected / 461 passed / 退出码 0**（终轮复跑，见下「验收时点」）。TS：`plugins/assets/mcp/frontend` vitest 31 passed、tsc/build exit 0。

## 二、阻塞（依赖他线，精确缺口）

1. **T10 全链验收（产品级 L3 格）**：需要 (a) C0 产品装配落地（integration-request 1/6/8：`default_plugins()` 挂 `McpAssetServerPlugin`；extensions.json 登记 frontend/status-chip——装配 owner 文件本线禁写）；(b) Pi 正式 runtime 装载入口与信任批准/版本裁定（G9 已列精确符号；本线已交付桥组件+真机非生产闭包 L3 局部格）；(c) C4 slice 差集（InvokeAction 被拒、BindSecret 静态 claims——t013 报告）。产品组装链未通前 T10 不勾。
2. **品牌真 CLI L3 装载格**：本机 `codex`/`claude` 二进制 PATH 与常见安装目录**实测零命中**（探针记录）；adapter 会话注入面已证，缺口在真实 CLI 对载荷的拨号装载——需 C0/用户提供固定 CLI 环境与运行授权。Claude `--strict-mcp-config` 缺席 → V04 额外原生发现面未闭合（t00-acp-probe §6）。
3. **Profile facet 注册（G5）**：profile-api 与 foundation 组合 import 红（`pacthold.resource_contracts` 旧路径，已实测并路由 Z1 r2）；T08 Profile 面、facet validate/compile 贡献、McpFacetDescriptor 薄适配等待。
3. **Q5 测试 lane**：`plugins/permissions/backend/tests` 收集 9 errors（同类路径漂移，已路由 Q5 r2）；Q4 适配层用真实 backend 类不受影响。
4. **compat 删除/迁移执行（G1 后半）**：`server_assets` 旧写入方退出与真实用户数据迁移属 C0（integration-request 4；本线交付迁移工具+字节互证+dry-run 计划面）。
5. **SDK 路线裁定（integration-request 10）**：树内 TS SDK 1.29.0 不在根锁可解析闭包（实测 require.resolve MODULE_NOT_FOUND、lock grep 0），本线以「限定替代」交付 stdio+HTTP 最小 client；C0 裁定官方 SDK 引入后可替换。
6. **宿主请求级 principal 注入（integration-request 7）**：wire/1 无认证 principal 面（实测 grep 零命中）；服务层 principal 显式入参+域内隔离已钉，wire 面为 caller-claimed。

## 三、未测（如实边界）

- L4 真实外部 MCP 服务/真实用户凭据/真实用户数据根迁移：本批未授权未运行。
- 真实 CLI 装载：**Pi 0.86.1 已实测**（加载/登记/拒绝/清理 observed；tools/call 需凭据未跑）；codex/claude CLI 本机不存在（探针零命中），其装载格 unknown；三品牌「重启恢复同一 native session」「原生额外 MCP 来源发现」（Claude strict 面）均未证。
- 前端渲染于真实 WorkbenchShell/electron smoke、真实 Server wire 往返：未跑（in-memory/loopback 替代，已登记）。
- probe/managed 的 SSE/服务端推流、断线自动重连：首版范围外（设计裁定）。
- HTTP live client 的 401-先于副作用假设：对端行为假设，已文档化非实测。
- 瞬态红观察：本会话出现过一次未留 ID 的 `plugins/assets/mcp` 单例红（合并压力下），后续 7 轮全量+3 轮 probe 复跑均 0 退出；两测试辅助竞态已修（`pid_alive`/`ProcessLookupError`）。

## 验收时点（终轮实测）

- `plugins/assets/mcp`：**508 collected / 508 passed，退出码 0**（终轮，含整合链；461→508 为 Pi 桥/ACP 探针/整合链三批增量）。
- 全链对照：`pytest apps/server` = 42F/1116P/10S/25E（exit 1）；per-ID diff vs foundation 消费基线（67 红）= **新增 0、消失 0**（passed 1092→1116 系上游 harness-api/permissions 测试并入）。继承红账见 `docs/known-issues.md`，无未解释新增。
- `apps/server/tests/test_asset_surface_refusals_147.py` 18 passed（legacy 对照面不新增）。
- 终树 HEAD：本文件所在 commit（`git log --oneline -1`），ready 分支 `codex/011-q4-ready` 指向它。

## 契约边界声明

发布=本线分支 `codex/011-q4-ready`；未合并 main、未 push。写入面仅 `plugins/assets/mcp/**` 与本 feature 文档；他线文件零改动（每批 git status 复核）。所有「完成」格不依赖 skip/xfail/假 stub：各批含变异审计与不对称探针（门拒→服务端零计数、守卫旁路必红）。
