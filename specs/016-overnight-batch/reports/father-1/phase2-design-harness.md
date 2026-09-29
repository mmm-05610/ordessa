# 阶段二设计包草案 · harness 域四家扩展(hermes / opencode / dsh / kilo)

状态:**设计草案,非实施授权**。证据口径:信任阶梯;四家格子引用
`docs/design/harness-configuration/harnesses.md`(2026-09-27 盘点)、本线 PE2
产出(`runtime/capability_declarations.json`、`application/native_evidence.py`)
与仓内注册表面。落地前置:§4 证据门。

## 0. 本线现状(PE2 夜批产出)

PE2 交付 C4 读侧 evidence 模型(`ordessa_harness_api.native_evidence` 五型 DTO、
`NativeEvidenceService` 三态判定、journal 只读投影,零新表)并显式登记:
`EVIDENCE_SUPPORTED_BRANDS = ("pi","codex","claude-code")`;
`EVIDENCE_UNSUPPORTED_BRANDS` = hermes/opencode/dsh/kilo,理由逐字
"no owner-side activation receipt surface in the brand adapter; 016 brand
ruling defers this brand to phase-two design"。四家的
`capability_declarations.json` 格均为 observe/start/finish/native_continuation/
stream(**均无 attach/permissions**)。qwen 已除名(8→7)。

## 1. 逐家原生面与投影设计

### 1.1 opencode(harnesses.md §5)

- 原生面:plugin 列表、TS/JS 插件、事件与自定义工具——**"扩展运行于进程权限下"**
  (§5 "原生插件/工具"行);server/share/远端组织默认存在(§5 "运营/界面"行)。
- evidence 设计:opencode 的插件事件面是**进程内回调**,不是"native owner 回执"
  语义——C4 口径要求 owner 侧为每个 operation 签发绑定 receipt + 独立 readback。
  设计:**不做 receipt 伪造**;若要接入,先裁"opencode 自定义工具事件能否承载
  operation 绑定的签发点"(L2 源码核 + L5 受控探针)。裁前保持 unsupported。
- 会话身份:server 多会话模型存在(§5),"多会话 server 级配置与单 session 的
  影响范围未实测"(§5 应用未决)→ `NativeSessionIdentityFacts` 投影暂不具备
  first-hand;待核后按 PE2 五型投影。

### 1.2 dsh(harnesses.md §6)

- 原生面:子代理 providers 含 **ACP、Claude、Codex、dsh-sdk、进程内 fork/spawn**
  (§6 "子代理"行);session log/OTel/persistence(§6 "运维"行);Cordis 装配
  (bundle patches→profile patch→home patch→CLI patches,ACP/headless 默认启动读)。
- evidence 设计:dsh 的 ACP provider 面意味着它可作为 **ACP 客户**而非 owner——
  它的"会话"是自己的 Cordis 组合,不天然存在"被 Ordessa 启动的 native owner
  receipt"。设计:评估 `dsh-sdk fork/spawn` 是否暴露 operation 级签发点(L2);
  无则 unsupported 维持,并把 dsh 定位为"经 ACP 接入的下游 harness"(归 connectors
  域语境),不在 evidence 域硬造。
- 会话身份:persistence/session log 是 L2 级在案目录——`launch_provenance` 格
  可先行(注册表+launch-descriptors 声明事实,PE2 已示范该投影不触发生命周期)。

### 1.3 kilo(harnesses.md §8)

- 原生面:plugin 列表、外部工具/事件——**"ABI、reload 与支持版本待核"**
  (§8 "原生插件"行,原文即缺口);隐私/运营行(share/retention/remote_control)。
- evidence 设计:同 opencode——事件面无 operation 绑定签发语义的 first-hand;
  待核 ABI(L2)后才可裁。`launch_provenance` 格同 dsh 可先行(注册表事实)。
- 会话身份:无 first-hand → 待核。

### 1.4 hermes(harnesses.md §4)

- 原生面:gateway/telemetry、persistent memory 与 memory provider、压缩
  auxiliary 模型、Python plugin manifest(hooks 注册)——官方文档多入口
  (CLI/gateway/Desktop 刷新行为不得混用,§4 明言)。
- evidence 设计:hermes 的 plugin hook 注册是进程内回调,同 opencode/kilo 无
  receipt 语义;**gateway 模式与 CLI 模式的会话身份不同源**,投影前必须先裁
  "Ordessa 接的是哪个 hermes 形态"(CLI or gateway——设计裁决点,登记不默认)。
  裁前 unsupported 维持。

## 2. 共同设计约束

1. PE2 已立纪律直接继承:缺席=诚实 None,绝不合成 bundle;complete 需要
   receipt + 独立 readback 且与确认一致;四家格的 unsupported 登记必须保留
   逐字理由(PE2 已做),升级为 supported 必须先有 L2/L5 钉源。
2. PE2 审阅保留项(证据强度:readback 独立性判定基于 evidence_ref 不等)对
   四家同样适用——若四家接入,readback 独立性判定需随协议一并强化(转 core/C4)。
3. brand adapter 只产事实,不产裁决;与 permissions 域设计包同红线。

## 3. 派单建议(草案)

| 包 | 内容 | 写入面建议 | 依赖 |
| --- | --- | --- | --- |
| P2-PE2-A | `launch_provenance` 格扩面(注册表声明事实投影,零生命周期)——**范围修正(审阅)**:现注册表只对三品牌有声明事实,四家格在品牌接入裁定前维持 unsupported;本包先做的是"三品牌格按 PE2 五型补齐 + 四家投影通道预埋",四家真投影以各自 launch-descriptors 登记为前提 | `plugins/harness/**` | 品牌接入裁定;四家各自声明事实登记 |
| P2-PE2-B | opencode/kilo/dsh 的 operation 签发点裁决(L2 源码核+L5 探针),裁后才立 receipt 投影 | 同上 | §1 各"待核"项闭合 |
| P2-PE2-C | hermes 形态裁决(CLI vs gateway)后同 B | 同上 | 同上 |

## 4. 证据门

同 permissions 域设计包 §4;另加:任何把四家格从 unsupported 翻 supported 的
动作,必须同时更新 `capability_declarations.json`、品牌家族表与
`EVIDENCE_*_BRANDS` 注册表(PE2 同支同树纪律),并附 E2 受控探针记录。
