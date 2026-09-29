# phase2-design-skills · Skills 域 × hermes/opencode/dsh/kilo 四家可派单方案包草案

状态:草案(016 夜批 overnight-2 阶段二产出;未实施)。依据:CMP-skills 甄别
(q1 域内无缺口,三品牌 adapter 已验)、skills 域能力表
(son-cmp-skills `plugins/assets/skills/src/ordessa_skills/harness_adapters/
capabilities.py` + research/brand-matrix.md)、harnesses.md §Skill 行各家差异。

## 0. 共同前提

1. **skills 三品牌(pi/codex/claude)adapter 已验**(q1 T08 G10–G13 实跑绿),
   四家方案包是**纯增量**,不触碰既有三家。
2. ** Skills 的 vendor-doc 反例已入册**(classification.md §四.1:同为 Skill
   字段不兼容——OpenCode 只认指定 frontmatter、Qwen 有路径激活/Hook 生命周期;
   §四.4 hooks 失败不阻断)。四家各格必须带同强度反例。
3. **qwen 除名**:Skills 的 Qwen 行(HarnessAdapters v1 可移植层只支持部分能力、
   commands/agents/hooks 目录被忽略——harnesses.md:179)全部跳过,不立项。
4. 注册通路 `harness.configuration-adapters`(AR-2,实测可用)四家直接复用。

## 1. 各家判定格与候选路线(自 harnesses.md Skill 行)

| 家 | 原生 Skill 面(在库证据级) | 立项前必须补的证据(L2 钉版) |
| --- | --- | --- |
| hermes | slot 已有(toml:215);Skill 字段/格式无在库证据 | SKILL.md 格式与 frontmatter 词表;用户/模型调用差异;hooks/附件面 |
| opencode | slot 已有(toml:163);只识别指定 frontmatter(classification §四.1 一手反例,官网源) | frontmatter 必需/可选键全表;目录发现根;版本门槛 |
| dsh | 无 skill slot(toml:270);harnesses.md:173 的 Skill 行是官方机制候选,非注册事实 | paths 激活与斜杠调用是否同状态(分类学已警告不是);其 hooks 与 EXT 域 dsh 格共用侦察产物 |
| kilo | 无 skill slot(toml:357);Skill 面无在库证据 | 官方仓库 skills 目录/格式;kilo.jsonc 相对面 |

## 2. 可派单任务分解(每家一个子包,建议支名 `codex/plugin-skills-<brand>`)

- **T0 侦察(先行)**:同 EXT/PX T0 口径(L2 钉版双记录,官方仓库 main HEAD+
  release tag 分记);产出 `research/<brand>-skills-matrix.md`;判定并入
  brand-matrix.md(新 §7「四家扩展」)。**证据闸门=§3 DoD:升 supported 仅 L2(钉版源码);L5 仅证管道。L2 缺位时
  落格按统一口径(见下),不为凑 supported 归档。**
- **T1 registry slot(harnesses.toml 实况,两档)**:opencode:163 与
  hermes:215 的 slots **已含** `skill`,仅缺 skill_target 声明;dsh:270 与
  kilo:357 **连 skill slot 都没有**(仅 provider/instruction,与 EXT 判定格
  一致)——前两家补 target,后两家先补 slot 声明再补 target(跨域 AR,归
  harness;与 EXT/PX 的 target 前置同批授权)。
- **T2 adapter**:按 skills `SkillsConfigurationAdapter` 形制
  (descriptor/assess/compile/verify + payload schema + name_rules);
  pin 从 T0 的钉版取;`SKILL_ENTRY` 按 T0 证据定(ACP 是否可进未知则不加格)。
- **T3 能力表扩格**:skills capabilities.py 的 BRAND_STATEMENTS 增四行
  (现 synthesized unknown 语义);discovery/reload/reset/loaded_evidence 等
  轴沿用现有 AXES,缺证据即 unknown。
- **T4 测试**:conformance(复用 skills 测试 doubles + G10–G13 门形制);
  G12 名字冲突反例每家一条(原生 namespacing unknown → 冲突一律拒绝,同三家口径)。

## 3. 门与 DoD

- evidence ceiling 纪律沿用:placement-only,装载证据缺格即 projected;
  `supported` 必须引 L2(钉版源码);L5 仅证管道。
- 写入面=plugins/assets/skills/**(+T1 另授权 harness 面);report 附
  复用(三品牌 adapter 形制/能力表/冲突规则)/自建(各家 frontmatter 映射)清单。
- qwen:除名不立项。

## 4. 排序建议

T1 与 EXT/PX 的 registry target 前置**合并为一个 harness 侧小包**(slots/target
声明一次做齐 hooks+instruction+skill),避免三次跨域授权;四家 T0 并行;
opencode 反例已在库,成本最低,建议首派。


## 5. 落格口径统一(四域一致,审阅轮 4)

- `unsupported`:有**一手证据**(L2 钉版源码或 L5 受控观测)证明该面不存在/
  不可用——归档时必须附该证据;无证据**不得**落 unsupported。
- `unknown`:无一手证据(只有 vendor-doc/索引级线索或全无)——保持 unknown,
  留待后续侦察升格或降格。
- `supported`:仅 L2;L5 只证 adapter 管道连通。

> T1 打包口径(四域统一,审阅轮 5 收口):hooks/instruction/skill 的
> registry target 声明**合并为一个 harness 侧小包**一次做齐、一次授权,
> 各域方案包的 T1 引用该包产出,不再各自表述。
