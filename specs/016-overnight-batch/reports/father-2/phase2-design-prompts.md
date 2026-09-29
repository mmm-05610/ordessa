# phase2-design-prompts · 三语义投影 × hermes/opencode/dsh/kilo 四家可派单方案包草案

状态:草案(016 夜批 overnight-2 阶段二产出;未实施)。依据:PX 线能力表
(son-px-prompts `plugins/assets/prompts/src/ordessa_prompts/harness_adapters/
capabilities.py`,四家 instruction/persona/systemReplacement 预置 unknown 格+
反例)、docs/design/prompts/harness-adapters.md §2 预置四行、AR-6 实测。

## 0. 共同前提

1. **AR-6 是四家共同前置**:registry 目前连三品牌也没有 instruction target
   声明(registry/schema.py:64 无字段、harnesses.toml 零条)。四家立项前,
   harness 侧需先把 instruction target 声明机制建起来(建议随 PE/PX 线的
   registry 改造一并做),否则四家 adapter 与三品牌一样只能停在
   「定义就绪、投影待通」。
2. **三语义不混称**(HM §1):instruction 追加/persona 独立层/systemReplacement
   显式替换;合成顺序固定 replacement→persona→有序 instructions(HM §3),
   多文本固定 `\n\n` 分隔——四家任何原生机制必须映射到这三格,不得造第四格。
3. **PX 能力表已预置四家 unknown 格+反例**(dsh persona 的组合顺序/移除恢复
   baseline、opencode 合并非替换等),方案包直接继承,不重写。
4. qwen 行(QWEN.md/context.fileName/import/includeDirectories)已除名,不立项。

## 1. 各家判定格与候选路线(自 HM §2 + PX 能力表)

| 家 | instruction | persona | systemReplacement | 立项前必须补的证据(L2 钉版) |
| --- | --- | --- | --- | --- |
| hermes | unknown(SOUL 身份≠项目指令) | unknown(personality 会话覆盖,vendor-doc) | unknown(no in-repo evidence) | personality 覆盖的读写入口/生命周期;SOUL 与会话层的隔离证明;当前 Ordessa 运行接入版本 |
| opencode | unknown(`instructions` 字段+AGENTS 兼容发现,合并非替换) | unknown | unknown(层叠=合并,与替换语义相抵触) | 相对路径/URL/继承规则;多来源层叠顺序;ACP 变更面 |
| dsh | unknown(`agent-instructions` 文件候选/预算/根发现) | unknown(persona prefix/suffix——「八家唯一原生 persona」语出 harnesses.md:20 盘点表(文档级,非本稿新证),立项前需 L2 复核) | unknown(system-prompt/runtime context) | 候选发现顺序与预算语义;prefix/suffix 与合成规则的组合;runtime context 边界 |
| kilo | unknown(`instructions`、agent/default_agent) | unknown | unknown | kilo.jsonc 用户/项目层叠;不再隐式读 OpenCode 目录;schema 深度 |

## 2. 可派单任务分解(每家一个子包,建议支名 `codex/plugin-prompts-<brand>`)

- **T0 侦察(先行)**:同 EXT T0 口径(L2 钉版双记录);产出
  `research/<brand>-prompts-matrix.md`;判定并入 harness-adapters.md §2 表
  (该表已预置四行,补「必须补证据」列的答案)。**证据闸门:升 supported 仅 L2;L2 缺位按 §5 统一落格口径
  (unknown 或有据 unsupported),不为凑结论归档。**
- **T1 registry instruction target(跨域 AR,与三品牌共享)**:见前提 1;
  dsh 需额外声明 persona prefix/suffix 的接缝(若侦察证实可声明)。
- **T2 adapter**:按 PX `PromptsConfigurationAdapter` 形制;payload 的固定
  synthesis 顺序字段沿用;**dsh persona 单独立独立反例**(EXT-03 遗留):
  组合后顺序断言 + 移除恢复 baseline 断言,不可与 instruction 反例合并。
- **T3 能力表扩格**:四家行按 T0 证据改判;`unsupported` 格必须引一手反例
  (如 opencode 替换语义与合并事实相抵触)。
- **T4 测试**:conformance(复用 PX doubles 形制)+ 每家语义反例
  (HM §1 的"不得自动降级成普通用户消息"每家验一次)。

## 3. 门与 DoD

  - 同 EXT:逐格 supported 需 L2(钉版源码);L5 仅证管道;投影天花板=projected;单 adapter 写入;
  baseline 先于新增保留,baseline 与项目发现不可分则拒绝(HM §3)。
- 隐式 include 拒绝:payload schema 的 synthesis/separator 枚举即闸
  (PX 已实现),四家沿用。
- report 附复用/自建清单;写入面=plugins/assets/prompts/**(+T1 另授权)。
- qwen:除名不立项;G09–G12 扩八家的矩阵在 T0+T2 完成后一次收口。

## 4. 排序建议

T1(registry instruction target)是三品牌+四家共同前置,建议独立小包先行;
四家 T0 可并行;dsh 是四家中唯一有原生 persona 的,方案包价值最高,建议
hermes(接入未明)之外优先。


## 5. 落格口径统一(四域一致,审阅轮 4)

- `unsupported`:有**一手证据**(L2 钉版源码或 L5 受控观测)证明该面不存在/
  不可用——归档时必须附该证据;无证据**不得**落 unsupported。
- `unknown`:无一手证据(只有 vendor-doc/索引级线索或全无)——保持 unknown,
  留待后续侦察升格或降格。
- `supported`:仅 L2;L5 只证 adapter 管道连通。

> T1 打包口径(四域统一,审阅轮 5 收口):hooks/instruction/skill 的
> registry target 声明**合并为一个 harness 侧小包**一次做齐、一次授权,
> 各域方案包的 T1 引用该包产出,不再各自表述。
