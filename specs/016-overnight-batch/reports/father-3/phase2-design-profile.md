# phase2-design-profile · Profile 域四家（hermes/opencode/dsh/kilo）扩展设计草案

016 夜批 overnight-3 · 阶段二产物（只文档不改代码）。依据：spec.md 品牌优先级
节、son-cmp-profile 包（z1 17 项甄别：profile v2 已交付 facet v2 机制与
harness 端口）、docs/design/harness-configuration/{harnesses.md,
profile-implications.md}、configuration-placement.md。**草案，不是实施授权。**

## 1. 目标

Profile v2 的机制面（facet descriptor/schema/compile/reset/generation 门禁、
journal、fence、第三方 facet 全链 proof）已在 z1 交付且品牌无关；四家扩展
= 每家一个 **facet 提供者 + 配置字段的记录模板行**（profile-implications.md
字段表：capabilityId/nativeBinding/precedence/applyMode/verification/
failure 等），使 Chat 的 Harness→Profile 两级选择器（PV-10 已交付）对四家
可用。**不重造 profile 机制，只增提供者与字段账。**

## 2. 四家证据格（配置入口/生效语义）

| 品牌 | pin | 配置入口（harnesses.md） | 设计要点 |
| --- | --- | --- | --- |
| hermes | 2.0 | `HERMES_HOME`+config.yaml；SOUL.md/personality 分层（:95/:100）；"官网与固定二进制的最小版本映射待完成"（:114） | facet 提供者读 `config.yaml` 键族；**分层纪律**：SOUL=身份基础、personality=会话覆盖，不得合并（:100）；生效路径（reload?）待核→applyMode 逐键登记 |
| opencode | 2.0 | opencode.json/JSONC 用户/项目/.opencode/远端组织默认/系统层；**层叠是合并不是替换**（:118）；TUI 配置独立 | 提供者声明 precedence=layered-merge；`OPENCODE_CONFIG_DIR` 不屏蔽其他来源（:118）→额外扫描来源行必填；ACP 暴露的变更面未实测（:136）→verification=配置文件摘要级，不冒充 applied |
| dsh | 0.1.5-rc.1 | Cordis 装配：bundle patches→profile patch→home patch→CLI patches，目标行 config 整体替换；ACP/headless 默认启动读取，HMR 取决于装配（:142） | 提供者以"原生 profile"为一等对象但**不可等同 Ordessa 预设**（:142）；写入语义=generation 替换（:142 目标行整体替换），生效时点未证→**applyMode=待核**（证得后再按 model-provider 重启事务口径登记）；config dump 有副作用风险（:163）→verification 禁用 dump 路径 |
| kilo | 7.7.2 | `~/.config/kilo/kilo.jsonc`、项目 kilo.jsonc/.kilo；TUI 独立配置；**官方要求改后重启**（:206/:189） | 提供者 applyMode=restart；重启恢复语义先证（沿 model-provider 重启事务：resume 同一 native 会话身份，失败进 Unknown）；旧文件名兼容限于 Kilo 目录、OpenCode 目录非隐式来源（:189）→precedence 表按此钉 |

## 3. 形制与纪律

每家提供者 = profile facet 贡献（z1 的 facet 提供者接口）+ 字段账行
（profile-implications 模板全列，profileEligibility 逐键裁定：可保存/只引用/
管理层/运行状态/未确定）。红线沿用 z1 已证语义：unset≠default、会话临时改
不反写全局、失败不弃旧有效状态、provider 卸载隐藏 UI 保留数据、十反例
（profile-implications §必须钉住的反例）逐条映射为测试。

## 4. 测试门

1. 每家字段账 golden（字节稳定）；2. 双会话隔离反例（不同 Profile 不互染、
不改用户全局文件——反例 1/2）；3. 应用失败保留旧态（反例 3）；4. 重启类
（kilo/dsh）会话身份核验（反例 7）；5. provider 缺席类型化拒绝（反例 10）；
6. 全部字段行带 source（官方 URL+日期+pin），`待核` 如实标。

## 5. 派工边界与待核

写入面：`plugins/profile/**` + 报告。前置侦察：hermes 生效路径与最小版本
映射（官网+固定二进制）；opencode ACP 变更面实测边界；dsh HMR 语义与装配
的对应。根锁脱同步（z1 遗留）需 C0 先解，否则三包 tsc 门不可复现。
