# phase2-design-chat · Chat 域四家（hermes/opencode/dsh/kilo）扩展设计草案

016 夜批 overnight-3 · 阶段二产物（只文档不改代码）。依据：spec.md 品牌优先级
节、son-cmp-chat 包（z2 26 项甄别：Chat v2 组件面/输入面已交付且品牌无关）、
docs/design/harness-configuration/harnesses.md 四家行、chat-zcode-reuse 契约
（ChatComponentKey/六槽位上下文）。证据级别名依 information-recon-priority.md
§一（L3＝官方文档带抓取日期；L5＝一手受控观测/E2 级）。**草案，不是实施授权。**

## 1. 目标

Chat v2 的组件与输入面（display/composer/panel/审批/项目弹窗，z2 已交付并
复验 50 vitest 绿）本身品牌无关；四家扩展 = **每家的会话接入事实面**：
Chat 面板消费的会话目标（sessionRef/runtimeGeneration）、Harness 选择入口
（Chat→Profile 两级选择器，z1 PV-10 已交付组件）、附件/审批/命令目录的
能力旗标，按各家真实通道（ACP/CLI/gateway）逐家钉死——能什么就显示什么，
不能的诚实缺席。

## 2. 四家证据格（会话接入通道与限制）

| 品牌 | pin | 通道事实（harnesses.md） | 设计要点 |
| --- | --- | --- | --- |
| hermes | 2.0 | CLI/gateway/Desktop 多入口，**刷新行为不得混用**（:95）；gateway 部署与会话输入能力需分范围（:110） | capability 表按入口三维（cli/gateway/desktop）分列；Chat 面板只暴露已证入口的会话目标；gateway 未证→面板该行缺席（不造输入通道） |
| opencode | 2.0 | server 级配置与单 session 影响范围、**ACP 暴露的变更面未实测**（:136）；"不能仅因有 HTTP server 就断言按会话隔离" | sessionRef 映射需实测取证后才能接；未证前 Chat 对 opencode 只给只读状态行（display 面），输入/选择器降级缺席 |
| dsh | 0.1.5-rc.1 | ACP/headless 默认装配启动读取；子代理 provider 含 ACP/Claude/Codex/进程内 fork（:142/:155） | ACP 通道存在已证（:142）；**sessionRef 映射待实测**——未证前同 opencode 只读降级，不默认复用现有 ACP bridge 语义；runtimeGeneration 语义与 Cordis 装配世代对齐，未证不接 |
| kilo | 7.7.2 | 官方 CLI 文档要求配置修改后重启；重启后恢复能力未实测（:206） | 输入面可用性=重启事务证据后置；未证前同 opencode 降级只读 |

## 3. 形制与纪律

每家一个 **chat capability 声明面**（数据，非代码分支：六槽位上下文里按
capabilityId 登记 input/attach/approval/commandCatalog/sessionTarget 的
三态+证据指针）——复用 z2 的 contract.ts 六槽位与"缺席来源隐藏、disabled
原因透传"语义（V06 已证），UI 零新分支。审批面：唯一操作面+resolved 退出
+choices-only 来源（FC-0029）语义四家通用，通道证据缺失=审批行缺席。
反例沿用 z2 已证组：陈旧插入拒绝、取消零后端调用、晚到结果拒绝、断连不造
终态（X03/X05）。

## 4. 测试门

1. 每家 capability 表 golden（三态+证据指针，字节稳定）；
2. 缺席通道的 UI 降级反例（隐藏/禁用透传原因，不造空态功能）；
3. 双会话隔离（会话 A 晚到结果不触 B——X03 复用）；
4. 审批 resolved 不展示成工具成功（X05 复用）；
5. 全部行带 source（官方 URL+日期+pin；ACP 能力与 TUI 能力不得互推——
   harness-configuration README 精确性边界条款）。

## 5. 派工边界与待核

写入面：`plugins/chat/**`、`plugins/agent/**` + 报告。前置侦察：opencode
ACP 变更面实测、hermes gateway 会话输入取证、dsh 装配世代与 runtimeGeneration
对齐、kilo 重启恢复实测——四项都是 L5 受控观测（E2 级，假端点/隔离 HOME），
零真实模型。产品装配登记归 C0（CMP-chat report V08 / integration-request §1）；
**注意** lsp 域登记产品装配归 INT/AR（son-lsp report §5.1）——两域装配 owner
登记不一致，待裁统一，派单前不得互推。
