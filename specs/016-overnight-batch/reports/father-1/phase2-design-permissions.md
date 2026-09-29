# 阶段二设计包草案 · permissions 域四家扩展(hermes / opencode / dsh / kilo)

状态:**设计草案,非实施授权**(016 品牌优先级裁定:四家不实施,转阶段二)。
证据口径:`docs/design/information-recon-priority.md` 信任阶梯;本文四家格子全部
引用 `docs/design/harness-configuration/harnesses.md`(2026-09-27 官方资料盘点,
行号可查)与本线 PE1 产出(son-pe1-permissions 树),无 L6 记忆性断言。
落地前置:每格"待钉源"项必须先按 §4 证据门补 L2/L3 钉,才可派单实施。

## 0. 本线现状(PE1 夜批产出,四家在此线全部为未实施格)

PE1 交付了品牌中立事实面:`permissions.authority.query@1`(授予事实查询)+ 三品牌
(pi/codex/claude)assess/compile/verify adapter(`plugins/permissions/adapters`)。
四家品牌在 adapter 矩阵与 authority 面均无投影格——本文逐家给出可派单草案。

## 1. 逐家原生面与投影设计

### 1.1 opencode(harnesses.md §5)

- 原生权限面(L3,官方 Schema+文档):`permission` 按工具/命令/路径规则
  allow/ask/deny(harnesses.md §5 "权限"行,含 `external_directory`);
  Agent 定义可带 `permission` 键(§5 "Agent" 行)。官方 Schema
  (opencode.ai/config.json)为字段级证据。
- 投影设计(机制 E 强制策略):**候选直投影**——opencode 的 allow/ask/deny
  三值形状与 Ordessa RuleAction(allow/ask/deny)一致,若 §4 证据门闭合后逐格
  语义核对通过(尤其 ask 在 ACP 通路的实际行为),则按
  `TypedRule(tool, action, target=TargetMatcher(pattern))` 直投影;核对不通过
  处逐格降为 unsupported。`external_directory` 不投影(那是 Ordessa workspace
  域事实,登记跨域引用)。
- authority 面贡献:opencode 无"审批账本"概念(harnesses.md 无此行)→
  `AuthoritySourceKind` 无新增;opencode 规则投影为 policy_rule 事实的来源标注。
- 待钉源:目标版本 Schema 的 permission 子树 SHA;ask 语义在 ACP 通路是否可达
  (L5 探针,E2 假端点)。

### 1.2 dsh(harnesses.md §6)

- 原生权限面(L2,官方 master `477b4f4205…` config-catalog):
  `permission-presets`(sandbox+approval 组合)、`sandbox-policy`、
  `sandbox-local runner`、本地/沙箱 fs/bash 工具分工(§6 "权限/隔离"行)。
- 投影设计:dsh 的 approval 是 Cordis 装配树里的 preset,**整行替换语义**
  (§6 反例 6:目标行 config 整体替换,禁通用 JSON 深合并)→ 投影单位必须是
  "整个 preset 行",不做字段级 SetField;approval 部分映射 Ordessa
  ApprovalScope(once/session),sandbox 部分归 sandbox 域(本包不越界,
  登记报回)。
- authority 面贡献:dsh 无独立审批账本;投影后的事实来源标 `policy_rule`。
- 待钉源:目标发行版的 runtime schema(§6 明言"逐包用对应 runtime schema
  筛除仅运行时注入字段");preset 行的请求级生效方式(HMR 与否,§6 未核)。

### 1.3 kilo(harnesses.md §8)

- 原生权限面(L3,官方 Schema app.kilo.ai/config.json + settings 文档):
  `permission` 对内置/MCP 工具规则、`external_directory`(§8 "权限"行)。
- 投影设计:与 opencode 同构的 allow/ask/deny 逐格直投影;MCP 工具规则
  (`mcp*` 工具键)需工具词表映射(Ordessa TOOL_KEYS 是否收录 MCP 工具名
  ——登记为设计裁决点,不默认收)。
- authority 面贡献:同 opencode,无账本概念 → policy_rule 来源标注。
- 待钉源:目标 CLI 版本 schema(§8:"字段存在仅作字段级证据,不足以证明
  runtime/ACP 覆盖";官方要求改配置后重启→生效方式=restart,投影 reconfiguration
  必须如实 restart-resume)。

### 1.4 hermes(harnesses.md §4)

- 原生权限面:**盘点无独立权限规则行**(§4 表无"权限"格)——tools/toolsets
  启用与"内容限制/扫描不等于权限控制"被显式区分(§4 "项目指令"行注)。
- 投影设计:**无投影格,登记 honest unsupported**,理由"官方资料无权限规则面;
  toolset 启用是工具暴露(机制 D/工具域),不是授权事实"。唯一可挂接点:
  Python plugin 的 hook 注册(§4 "Hooks/插件"行)——若未来需要 pre-effect
  拦截,走 EXT 域 hook 投影,不在 permissions 域造平行机制。
- 待钉源:无(unsupported 格自身即结论;若官方新增权限面,按 L2/L3 重新入册)。

## 2. 共同设计约束(四家通用)

1. 复用红线:全部走既有 `permissions.authority.query@1` 事实面与
   `Authorizer.evaluate` 裁决面;不新增第二裁决引擎、第二存储(adapter 只产
   assess/compile/verify,同三品牌形制)。
2. 不把"同名模式当等价"(classification.md §四):opencode/kilo 的 deny 语义、
   dsh 的 preset 行替换、各家 scope 层级逐家核对后才写投影。
3. 生效方式显式:每格标注 session-local/reload/restart-resume/未知;不得从
   "可改文件"猜热更新(classification.md §三)。

## 3. 派单建议(草案)

| 包 | 内容 | 写入面建议 | 依赖 |
| --- | --- | --- | --- |
| P2-PE1-A | opencode + kilo 规则投影(同构格,一并做) | `plugins/permissions/adapters/**` | 各自目标版本 schema 钉源(§1 待钉源) |
| P2-PE1-B | dsh preset 行投影(整行语义) | 同上 | 目标发行版 runtime schema;C4 merge 的整行替换单位裁定 |
| P2-PE1-C | hermes unsupported 登记落册(adapter 矩阵注记) | 同上 | 无 |

## 4. 证据门(派单前必须闭合)

每格实施前提交:官方 Schema/源码的固定 commit+SHA-256(L2)或官方文档抓取
记录(L3,带日期),与本表逐格对照;"看起来支持"不入册。runtime/ACP 覆盖
存疑格跑 E2 受控探针(假端点),不出网络实测。
