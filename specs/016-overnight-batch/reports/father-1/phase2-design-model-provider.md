# 阶段二设计包草案 · model-provider 域四家扩展(hermes / opencode / dsh / kilo)

状态:**设计草案,非实施授权**。证据口径:信任阶梯;四家格子引用
`docs/design/harness-configuration/harnesses.md`(2026-09-27 盘点,行号可查)、
本线 MPX 产出(`plugins/assets/model-provider/adapters` 的 requestParams 投影面)
与 014 裁定(plan.md F12)。落地前置:§4 证据门。

## 0. 本线现状(MPX 夜批产出)

MPX 把四类请求级参数(推理强度/预算/超时/请求级 retry)经**既有三品牌**
(pi/codex/claude-code)adapter 投影:codex `model_reasoning_effort`(词表钉
remote.py)、pi `maxTokens`(models.json 黄金对象)/settings.json retry 块
(声明+签发闸门),其余格诚实拒绝带钉源理由。payload `model-provider.choice.v1`
新增可选 `requestParams` 闭形对象。四家品牌在 `DIALECTS`/`NATIVE_TARGET` 中
无格——逐家设计如下。

## 1. 逐家原生面与投影设计

### 1.1 hermes(harnesses.md §4)

- 原生面(L3,官方 configuration 文档):主 provider/model、fallback、
  **reasoning/text verbosity**、auxiliary 各任务模型(压缩/视觉等辅助模型
  不是主模型别名)(§4 "模型"行);HERMES_HOME/config.yaml 入口。
- 投影设计(机制 A 类型化参数;**以下均为候选形状,同构结论在 §4 证据门闭合前
  不成立**——同名/相似键位不等于语义等价):
  - provider/model 选择:主 provider + fallback 链呈"选择关系"形状,
    **候选**映射到既有选择投影(config.yaml 的 provider 段;注册面新增格,
    不动既有三品牌);fallback 触发语义在待钉源清单,闭合前不写投影;
  - reasoning verbosity:**候选**对位 MPX `requestParams.reasoningEffort` 键位,
    但 Ordessa 词表与 hermes 取值域都未钉,先按"逐家语义核对"流程走,不得因
    名称相似直连;
  - auxiliary 任务模型:三品牌没有的形状(fallback 之外的第二维)——候选为
    `brandFields.auxiliaryModels` 开放键起步,词表钉后升类型键;**不新建 facet**。
- 生效方式:config.yaml 读取时机未核(§4 多入口差异)→ 先按 restart-resume
  最保守声明,核后降级。
- 待钉源:config.yaml provider 段 Schema(固定版本)、verbosity 取值域、
  fallback 触发语义。

### 1.2 opencode(harnesses.md §5)

- 原生面(L2/L3,官方 Schema opencode.ai/config.json):`provider`、`model`
  (provider/model 维度)、`small_model`、enabled/disabled providers(§5 "模型"
  行);provider 内 options/模型变体按 schema。
- 投影设计:与三品牌同构度最高的一家——`model` = 既有 session model 语义,
  `small_model` = 辅助模型键(MPX auxiliary 键位同款),`enabled/disabled
  providers` = 目录事实(登记为 choices 目录投影,不是写键)。层叠是合并
  (§5 明言"合并,不是整文件替换")→ C4 merge 语义需按 opencode 合并规则
  核一遍(与 dsh 整行替换相反,逐格注明)。
- 待钉源:目标版本 schema 的 provider 子树;`small_model` 请求级/会话级归属
  (F12 划界:辅助模型的"选择"归本域,"运行状态"不归)。

### 1.3 dsh(harnesses.md §6)

- 原生面(L2,官方 master `477b4f4205…` config-catalog):`agent-default-model`;
  `llm-pi-ai` provider/model/**compat/header/retry**(§6 "模型"行);
  DeepSeek account/API-key;replay。
- 投影设计:**整行替换语义**(§6 反例 6)→ provider 定义必须按 patch 行整写,
  与 codex 的 `model_providers.<id>` 黄金节同思路但合并语义相反;`retry` 在
  provider 定义内——这与 MPX 请求级 retry 家族对齐,但归属是 provider 定义
  (连接级)而非请求级,登记**不双收**:连接级 retry 随 provider 定义投影,
  请求级 retry 维持 MPX 语义。`header` 键涉及凭据形态→只接受 secret 引用
  (BindSecret),值绝不入 facet。
- 待钉源:目标发行版 `llm-pi-ai` runtime schema(筛除 Volatile/运行时注入,
  §6 明言);`agent-default-model` 与 session model 的覆盖边界。

### 1.4 kilo(harnesses.md §8)

- 原生面(L3,官方 Schema app.kilo.ai/config.json):`provider/model`、
  `small_model`、启用/禁用 providers(§8 "模型"行);官方要求改配置后重启
  (§8 应用注)。
- 投影设计:与 opencode 几乎同构(model/small_model/目录开关)→ 与
  P2-MPX-A 合并派单;`small_model` 键位与 opencode 统一为 auxiliary 键;
  生效方式=restart(官方明言)→ reconfiguration 如实 restart-resume。
- 待钉源:目标 CLI schema(kilo schema"字段存在≠runtime 覆盖",§8 明言)。

## 2. 共同设计约束

1. 复用红线:全部经既有 facet `assets.model-provider` 的
   assess/compile/verify 形制与 C2 `harness.configuration-adapters` 注册点;
   **不立新包、不立新 facet**(016 MPX 红线);新品牌只是
   `DIALECTS`/`NATIVE_TARGET`/`SUPPORTED_VERSION_RANGES`/descriptor 的
   新格 + 各自 adapter 模块。
2. F12 划界:请求级四族键继续走 `requestParams`;四家的 provider 定义内
   retry/超时属**连接级**,随 provider 定义投影,不与 requestParams 双收。
3. 凭据纪律:一切 header/apiKey 键只收 secret 引用(`BindSecret`),值不进
   facet(既有哨兵测试沿用)。
4. 与 runtime-preferences(015-A)划界同 MPX:辅助模型的**选择**归本域,
   运行状态不归。

## 3. 派单建议(草案)

| 包 | 内容 | 写入面建议 | 依赖 |
| --- | --- | --- | --- |
| P2-MPX-A | opencode + kilo(同构对:schema 驱动的 model/small_model/目录开关投影) | `plugins/assets/model-provider/adapters/**` | §1 待钉源(目标版本 schema) |
| P2-MPX-B | hermes(config.yaml 选择关系+auxiliary 键起步) | 同上 | config.yaml Schema 钉;生效方式核实 |
| P2-MPX-C | dsh(整行替换语义的 provider 定义;连接级 retry 不双收) | 同上 | 目标发行版 runtime schema;C4 整行替换单位裁定(与 permissions 域 P2-PE1-B 同一裁定点) |

## 4. 证据门

同前两份设计包:每格 L2 固定 commit+SHA 或 L3 官方文档抓取记录(带日期),
运行时/ACP 覆盖存疑格走 E2 受控探针;`SUPPORTED_VERSION_RANGES` 四家新格
必须有 t00-freeze 式钉版记录(011-z3 形制)后才可派单。
