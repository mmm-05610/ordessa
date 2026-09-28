# Harness mapping and application

## 1. 三种语义，不把名称当同义词

- instruction：在原生基础上补充内容；不替换默认系统行为或项目指令。
- persona：独立选取的角色/风格层；默认保留原生基础行为。Hermes 的基础 SOUL identity 与会话 personality 不是同一个东西，本版 persona 优先后者，不借 persona 名义覆盖 SOUL。
- system-replacement：显式替换原生基础系统指令，仅在确切支持时提供。替换范围不包括宿主强制安全规则或项目发现设置。

没有原生独立人格接口时，只有能证明“角色/风格附加层”语义、可移除且不改变消息角色的适配才可提供 persona，并在详情标明映射方式；不得自动降级成普通用户消息。无法证明则此项 unsupported，已有数据保留。

## 2. 原生机制候选（非当前支持承诺）

| 品牌 | 已读官方机制 | 本版首选路线 | 必须补证据 |
| --- | --- | --- | --- |
| Pi | APPEND_SYSTEM.md 追加；SYSTEM.md 替换；项目对应文件可能覆盖用户对应文件 | 私有运行根或 SDK 显式受限入口，不覆写项目 .pi 文件 | 固定 pin 的实际资源加载器、项目覆盖、reload/resume、reset 后默认 |
| Codex | developer_instructions 追加；model_instructions_file 替换；AGENTS 有独立发现机制 | 固定原生配置/线程入口，业务文本与 before 配置确定性组合 | 当前桥是否传递该字段、线程恢复是否重读、项目指令不受损 |
| Claude | SDK preset+append 追加，custom system prompt 替换；CLAUDE.md 是另一条项目上下文机制 | session-scoped SDK options，经现有官方 ACP adapter 暴露受限配置入口 | 锁定 adapter 是否暴露/更新/指纹含此选项；不能以 provider env 指纹探针代证 |
| Hermes | SOUL 基础身份、personality 会话覆盖 | 后续独立 adapter，不把它的 HOME 模型搬进平台 | 当前 Ordessa 运行接入/版本/动态入口，未验证前不启用 |
| OpenCode | `instructions` 字段 + AGENTS 兼容发现；层叠是合并非整文件替换（2026-09-28 八家扩展新增） | instructions 字段注入，不覆写项目 AGENTS | 相对路径/URL/继承规则；多来源层叠顺序；ACP 变更面未实测 |
| dsh | `agent-instructions`（文件候选/预算/根发现）；persona prefix/suffix（八家唯一原生 persona）；system-prompt 与 runtime context（同上新增） | persona 对接原生 prefix/suffix；instruction 走 agent-instructions | 候选发现顺序与预算；prefix/suffix 与本域合成规则的组合；runtime context 边界 |
| Qwen | QWEN.md、context.fileName/import/includeDirectories、规则文件（同上新增） | context 指向受管内容，不覆写项目 QWEN.md | import/includeDirectories 作用域；"memory"≠自动记忆；版本门槛 |
| Kilo | instructions、agent/default_agent 选择（同上新增） | instructions 字段注入 | kilo.jsonc 层叠；不再隐式读 OpenCode 目录；schema 深度 |

官方来源见 research-and-reuse.md。Pi/Codex/Claude instruction 为本批必须完成项；persona/system-replacement 各格必须完成可用/不支持/未知判定与反例。不为赶进度宣称全部支持。已证原生可用但当前 adapter 少接口：按 Harness 公共配置接缝提出最小 runtime action，并在 Harness 任务内实现；本插件不能绕进 Harness 私有类。

## 3. 合成规则

逻辑顺序为 system-replacement（如有）→persona（如有）→有序 instructions。该顺序表示 Ordessa 提供的内容组合，不是对原生所有隐藏提示/项目指令优先级的承诺。

adapter 声明 native slots 及合成规则版本。多文本共一个 slot 时按选择顺序用固定 `\n\n` 分隔，不自动添加“忽略上文”等措辞；保留正文原字节。名字/ID/修订保存在旁侧 manifest，不拼入提示正文。任何 wrapper 必须纳入合成规则、golden tests 与预览，不能有未显示的业务提示。

slot 只有一名 Prompts adapter 写入；一个选择列表重新合成一次，不对文件反复 append。原 before 内容若允许追加，保存不可变 baseline 并先于新增文本保留；baseline 与项目内容发现若不可准确分开则拒绝，不进行猜测性字符串删改。

## 4. 内容不是文件执行清单

首版正文不展开变量、frontmatter 指令、`@文件`、URL include 或 shell。Markdown 链接只是正文。原生会主动展开某种语法的入口不可直接接收未经处理的受管正文：优先用不展开的原生文本参数；否则采用已证语义保真的编码，不能保证就返回 NATIVE_SEMANTICS_UNSUPPORTED 并定位行号。

不跟随目录导入、不递归扫项目/HOME、不 fetch 正文里的 URL。此限制针对配置装载副作用，不承诺模型读到自然语言后不会请求工具；工具实际权限仍由权限系统管。

## 5. 应用、重置、验证

会话服务下一次提交冻结 Profile items 与正文 snapshot，调用 Harness plan/apply。正常选择/编辑仅保存期望值，不触发 reload，不在输出结束时自动应用。

验证分层：产物字节正确只是 materialized；固定原生加载入口确实消费/采用才可 confirmed。可以使用加载器观察、SDK query options 的受控接入、实际原生 fake endpoint 请求验证，不要求窥视闭源内部完整 system prompt。不以模型回答“我已遵守”证明配置生效。

重置必须清除本插件拥有的旧 persona/指令/替换目标并恢复合法 baseline；空文本可能有原生 fallback，不能用它猜 reset。不能安全更新当前会话时走 Harness 的重启-resume；无法保留原会话则拒绝且不新建空会话代替。

超时、应用成功但回执丢失等按 Harness unknown/reconcile 处理，不在 Prompts 再建应用 journal。Profile 绑定确认由 Profile 所有者完成。停用内容不会擦掉历史影响，此边界只在设置说明/诊断出现，不加 Chat 常驻状态标签。
