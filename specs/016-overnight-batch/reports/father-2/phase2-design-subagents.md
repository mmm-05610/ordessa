# phase2-design-subagents · 原生子代理 × hermes/opencode/dsh/kilo 四家可派单方案包草案

状态:草案(016 夜批 overnight-2 阶段二产出;未实施)。依据:CMP-subagents 甄别
(q3 三品牌:claude/codex 已验、pi 条件 adapter)、q3 capability-matrix.md、
harnesses.md §子代理行各家差异、classification.md §四 反例。

## 0. 共同前提

1. **q3 的域内核已完备**(T03–T05 纯定义/分配/迁移实跑绿,862 passed);四家
   方案包只做 adapter 面,复用域内 DefinitionStore/Assignment/resolution 全套。
2. **子代理的语义陷阱已在册**(harnesses.md:60):Claude 插件内 subagent 的
   hooks/mcpServers/permissionMode 被忽略,不能当文件型 agent 同等能力——
   四家任何"插件内子代理"面必须做同款"被忽略字段"反例。
3. **Pi 条件 adapter 是范本**(T08:仅在 Harness 已登记受审扩展且真实控制端口
   存在时编译;否则 unsupported,不装示例扩展)——四家中接入面不清的
   (hermes)按此形制立项。
4. **qwen 除名**(q3 本就只有三品牌,无 qwen 行;维持除名)。

## 1. 各家判定格与候选路线(自 harnesses.md 子代理行)

| 家 | 原生子代理面(在库证据级) | 立项前必须补的证据(L2 钉版) |
| --- | --- | --- |
| hermes | 子代理面无在库证据;角色/会话概念存在(HM §personality 相邻行) | 官方仓库子代理定义格式/发现根/隔离面;与 SOUL/personality 的边界 |
| opencode | 无在库证据(此前稿误引 codex 的 agents.<name>.* 键族,已剔——该键族属 codex 配置参考,opencode 需自查其官方仓) | 官方仓库 agents/subagents 面;发现优先级、实例隔离、调用入口 |
| dsh | 子代理面无在库证据 | 官方仓库 agents/subagents 面;若有,定义格式与版本门槛 |
| kilo | agent/default_agent 选择有线索(HM:22 相邻,EXT/PX 已预置) | 定义文件格式、default_agent 语义、隔离与撤销 |

## 2. 可派单任务分解(每家一个子包,建议支名 `codex/plugin-subagents-<brand>`)

- **T0 侦察(先行)**:同 EXT/PX/skills T0 口径(L2 钉版双记录);产出
  `research/<brand>-subagents-matrix.md`;判定并入 q3 capability-matrix.md
  (新「四家扩展」节)。**证据闸门:升 supported 仅 L2;L2 缺位按 §5 统一落格口径。hermes 接入面
  未明,推荐按 Pi 条件形制立项(先登记 unsupported+审查清单;该登记本身需
  T0 的一手证据,且 T0 产出物清单必须附「控制端口/受审扩展不存在」的 L5 缺位
  观测记录,使口径可核查)。**
- **T1 registry/ACP 面**:四家 harnesses.toml 现无 subagents 相关 slot/target
  (与 skills 不同,子代理走 ACP 会话面而非文件投影居多)——T0 需回答
  「该家子代理是配置声明还是会话能力」;会话能力类(如 ACP initialize 播发
  `subagents:{}` 能力,q3 capability-matrix C-1 行先例)走 RuntimeAdapter 面
  而非 ConfigurationAdapter,**立项时先定通道再定形制**。
- **T2 adapter**:ConfigurationAdapter(配置声明类)按 q3 claude/codex 形制
  (固定版本 frontmatter/TOML、发现、隔离、reset、核验、拒不支持字段);
  RuntimeAdapter(会话能力类)按 ordessa_harness_api RuntimeAdapter 协议
  (describe_installation/describe_targets/...),两形制不混用。
- **T3 测试**:复用 q3 测试形制(固定版本解析/发现优先级/隔离/reset/拒不支持
  字段各一条);"插件内子代理被忽略字段"反例每家必做(前提 2)。
- **T4 能力表**:q3 capability-matrix 增四家行,逐格 supported/unsupported/
  unknown + 证据等级(L1/L2/L3 口径沿用 q3 T14)。

## 3. 门与 DoD

- Pi 条件形制的红灯纪律:控制端口/受审扩展缺位 → unsupported,不装示例扩展。
- 真实装载证据四家一律先缺:按 q3 T14 口径(其 L1/L2/L3 是证据强度分级,
  与 information-recon-priority 信任阶梯撞名,引用时注明),「三品牌通过」不因
  四家加入而改口;四家独立记录到位于哪一级、真实装载未测。
- 写入面=plugins/assets/subagents/**;report 附复用(q3 域内核+adapter 形制)/
  自建(各家格式映射)清单。
- qwen:除名不立项。

## 4. 排序建议

T0 四家并行;kilo(default_agent 线索)与 dsh(T0 大概率落 unknown,归档成本最低)先行
(dsh 旧句「落空即 unsupported」已废,以 §5 口径为准);opencode 因无在库证据,侦察产物定去留;hermes 建议直接按 Pi 条件形制立项(接入面未明);dsh 若 T0 落空即
若 T0 无一手证据则按 §5 落 unknown,有 L2/L5 一手反证才可落 unsupported。
  若 opencode 走 ACP 会话能力类,先与 harness 域对齐
RuntimeAdapter 通道再派 T2。


## 5. 落格口径统一(四域一致,审阅轮 4)

- `unsupported`:有**一手证据**(L2 钉版源码或 L5 受控观测)证明该面不存在/
  不可用——归档时必须附该证据;无证据**不得**落 unsupported。
- `unknown`:无一手证据(只有 vendor-doc/索引级线索或全无)——保持 unknown,
  留待后续侦察升格或降格。
- `supported`:仅 L2;L5 只证 adapter 管道连通。

> T1 打包口径(四域统一,审阅轮 5/6 收口):hooks/instruction/skill 的
> registry target 声明合并为一个 harness 侧小包;子代理域的 T1 **不止引用
> 该包**——本域需先在 T0 产出「通道裁决」(配置声明类→ConfigurationAdapter /
> 会话能力类→RuntimeAdapter),该裁决是 T0 的显式产出物,T2 依其选形制,
> 不另立第二套 registry 表述。
