# phase2-design-extensions · hooks/原生插件/自定义工具 × hermes/opencode/dsh/kilo 四家可派单方案包草案

状态:草案(016 夜批 overnight-2 阶段二产出;未实施)。依据:EXT 线能力表
(son-ext-extensions `plugins/assets/extensions/src/ordessa_extensions/capabilities.py`,
逐格证据+反例已预置)、harnesses.toml slot 事实、classification.md 反例、
information-recon-priority.md 信任阶梯。

## 0. 共同前提(四家通用,出自 EXT 线实测)

1. **registry 无 hooks slot**:四家在 harnesses.toml 的 slots 均无 `hooks`
   (opencode:163、hermes:215、dsh:270、kilo:357)——任何一家立项的第一步都是
   harness 侧 registry 增设 hooks slot 声明(归 harness 域,经统一的 registry target 小包 AR 报回,不偷改)。
2. **EXT 机制 D 批准链四家共用**:强制批准+来源哈希+版本 pin+注入面清单
   (HIGH 拒载/MEDIUM 入批准记录),已在 EXT 线实现并有 101 项测试——四家方案
   直接复用,不重造。
3. **EXT-6 阻断语义红线**:四家任何 hook 面都必须 observational-only;
   `semantics` 词表只容 "observational"。
4. **qwen 教训**:一切 qwen 行跳过并登记除名(用户裁定),不因四家扩展回潮。

## 1. 各家判定格(自 EXT 能力表,逐格证据见该表)

| 家 | native_slot 现状 | 原生机制(在库证据级) | 立项前必须补的证据(L2 钉版源码) |
| --- | --- | --- | --- |
| hermes | 无 slot | gateway hooks 目录是独立装载机制,不受 plugins.enabled 统管(harnesses.md:105) | gateway hooks 目录的清单格式/事件名/失败语义;是否与 Claude 兼容层同名同义 |
| opencode | 无 slot | 插件体系存在;hooks 面无在库证据 | 官方插件 manifest 是否含 hooks;事件词表;失败是否阻断 |
| dsh | 无 slot(仅 provider/instruction) | 无 hooks 证据 | 官方仓库 hooks/生命周期面;若无一手证据,按 §5 落 unknown(L2/L5 一手反证
  才可 unsupported) |
| kilo | 无 slot(仅 provider/instruction) | 无 hooks 证据 | 同上 |

## 2. 可派单任务分解(每家一个子包,建议支名 `codex/plugin-extensions-<brand>`)

- **T0 侦察(先行,单独交付)**:按信任阶梯锁钉版——官方仓库 main HEAD 与最近
  release tag 分别记录;按「配置入口→扩展面→通道→license→安全面」顺序读官方
  材料,逐条记 URL/日期/commit;产出 `research/<brand>-hooks-matrix.md`,
  判定表并入 docs/design/harness-configuration/harnesses.md。**侦察完按 §5
  统一落格口径判:仅 L2 一手证据可落 unsupported/supported,否则 unknown。**
- **T1 registry slot(跨域 AR)**:harnesses.toml 增 `<brand>` hooks slot+
  target 声明(格式与 codex/claude 的 hooks_target/hooks_key 对齐);同步
  registry/schema 解析;测试与 PE2 同规格。**写入面=harness 域,须单独授权
  (或并入 PE2 支)。**
- **T2 adapter**:按 EXT `HooksConfigurationAdapter` 形制实现
  descriptor/assess/verify;compile 双闸(runtime target 供给+钉版值 schema)
  与 EXT 同款;声明 claims 时与既有 adapter 冲突面过一遍 handler 冲突 authority。
- **T3 能力表扩格**:EXT capabilities.py 现存四家 `unsupported/phase2-design`
  预置格,按 §5 口径属「待重判」——T0 后先落 unknown,再依 T0 的一手证据改判
  (预置格系 EXT 线在无四家证据时的保守占位,不豁免于新口径)。升 supported 的证据闸门与
  §3 一致:仅 L2(钉版源码)可证品牌原生语义;L5(受控观测/假端点)只能证
  adapter 管道连通,不得据此升格品牌能力(与「不推定 Claude 同义」同一红线)。
- **T4 测试**:conformance(复用 EXT doubles 形制)+评估反例
  (分类学 §四.4:同 hook 失败不一定阻断——每家独立反例,不推定 Claude 同义)。

## 3. 门与 DoD

- 能力表逐格 supported 必须引 L2(钉版源码);L3 官网单独不够升格;L5 假端点
  观测仅证管道、不升品牌格。(术语注意:q3 线的 L1/L2/L3「证据强度分级」是
  另一套词汇,与本信任阶梯撞名——引用时注明哪套。)
- 一切 hook 投影天花板=projected,直到该品牌装载入口有在库一手证据。
- report 附「复用(EXT 批准链/adapter 形制/测试 doubles)/自建(该家特有面)」
  清单;写入面=plugins/assets/extensions/**(+T1 时另行授权 harness 面)。
- qwen:不做,除名照登记。

## 4. 依赖与排序建议

T0 四家可并行侦察 → 逐家过闸:预期 opencode/kilo 需看官方仓库,hermes 需核对
gateway 与 Claude 兼容层差异,;dsh 大概率落 unknown(无证据不落 unsupported,见 §5)。T1 是四家共同前置,
建议一次授权一次做完(同支同树)。


## 5. 落格口径统一(四域一致,审阅轮 4)

- `unsupported`:有**一手证据**(L2 钉版源码或 L5 受控观测)证明该面不存在/
  不可用——归档时必须附该证据;无证据**不得**落 unsupported。
- `unknown`:无一手证据(只有 vendor-doc/索引级线索或全无)——保持 unknown,
  留待后续侦察升格或降格。
- `supported`:仅 L2;L5 只证 adapter 管道连通。

> T1 打包口径(四域统一,审阅轮 5 收口):hooks/instruction/skill 的
> registry target 声明**合并为一个 harness 侧小包**一次做齐、一次授权,
> 各域方案包的 T1 引用该包产出,不再各自表述。
