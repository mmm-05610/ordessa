# Implementation Plan：先审核，后绑定平台起点

## 1. 目标包格局

```text
plugins/profile/
├── api/                         # 前端轻量 Token/贡献类型，无自动启用
├── src/ordessa_profile/          # 保留已有 Python 包路径
│   ├── profiles / storage / repository
│   ├── facets / resolution / policy
│   ├── sessions / application_journal
│   └── plugin                   # 真正宿主贡献，不是空注册
├── frontend/
│   ├── management/              # Harness→Profile 两级导航/编辑器
│   ├── settings/                # 配置面启用与覆盖规则
│   ├── editors/                 # schema fallback/贡献装载
│   └── service/                 # 公开 wire 的轻量客户端
├── integrations/chat/           # 可选入口，简单两级选择器/下次提交应用
└── tests/                       # 存储、注册、适配、UI、受控全链

plugins/<能力域>/integrations/profile/  # facet + 可选 editor/glue
plugins/harness/...                     # 实际应用和恢复，不归 Profile
products/...                            # 显式组合
```

这是逻辑布局，不能为了目录整齐重命名现有 dist/extension/data ID。前后端同业务域；glue 不是一包一个业务重写。纯 API 可被未启用实现的消费者导入。

## 2. 复用优先顺序

以 [reuse-map.md](reuse-map.md) 逐模块裁决为执行清单，研究文档不是授权整包搬运。取材不可用的回退已给定，不由执行者随意换产品模型。

1. 当前 Profile 后端存储/版本/覆盖逻辑与反例先做保真迁移，不丢历史。
2. Hermes 能力 checklist/dirty edits 与创建流程，只在许可证与完整源码核实后提取，不带 SDK/store/原生 home。
3. Roo schema 唯一性/配置与模式分开的校验思路，可提取小型校验与测试模式，不搬完整 ProviderSettingsManager。
4. Profile 注册/解析/两级导航是 Ordessa 特有薄实现，诚实标自主实现；不要从上游硬凑成一个耦合大模块。
5. UI 基础控件使用已审 C8；不再造表单/树/弹窗底座，不要求平台知道 Profile。

许可证未证实的源码只可参考，不因“用户要求复用”跳过许可。每个直接移植符号记录来源 SHA/路径、目标、修改和 license。完全参考模式不冒充复制复用。

## 3. 阶段

- P0：用户审核新增决策；绑定 A/B/C 平台检查点，读真实 API。盘点现有 profile/model-provider/skills 三树未集成内容；输出字段/ID/测试迁移表和依赖图，不先全量 merge。
- P1：冻结轻量 facet/policy/session-target/application receipt 契约、正反类型 fixture；用受控第三 facet 证明扩展性。既有 API 版本化适配，不静默破坏旧提供者。
- P2：后端领域实现与迁移；policy/数据解析/journal、真实宿主注册、HTTP/wire 公开服务。不得写 apps/server/Pacthold 的品牌/业务分支。
- P3：Harness 运行接缝（单独包写者）接受 intent，真实 fence/apply/reconcile/恢复证明；只做已存在品牌，逐字段能力不夸大。若依赖平台中性接口缺失，先给最小需求，不能把债务塞核心。
- P4：Profile 前端管理器/机制设置，实装零facet/两facet/缺Provider/离线/并发编辑；Profile Chat glue 单独消费已有贡献点，不修改 Chat 内部。
- P5：model-provider/Skill 等提供者接入及组合验证；验证“新增第三facet只改提供者+必要Harness能力实现”。缺失提供者不强装、不 placeholder；首版必须两个真实领域 glue 加一个受控未知领域验证，不要求一晚实现所有 MCP/Memory/Sandbox 业务。
- P6：浏览器与受控运行验收，配置回读、A/B 会话隔离、崩溃恢复、scope卸载；如需真实模型另请求范围与费用授权。合并按单独审批，不改根分支。

后端 P2 与前端 P4 可在 P1 后并行；P3 与 P2 契约冻结后独立包实现。API/产品装配/锁文件单写者；不是让三个代理同时改同一 Profile store。当前用户只授权设计，未创建本批 worktree。

## 4. 可执行性门

未有以下事实，不发布无人值守“全部实现”任务：完整 SessionRef、已有 runtime 的发送互斥接缝、Harness 应用契约实际签名、profile schema 迁移方式、C7/C8 所需组件 API、范围外改动授权。设计给出语义，P0/P1 负责绑定实际类型，不让执行者临场改产品含义。

复用源码请求限流是研究缺口，不伪造“已审完整源码”。其余领域设计可推进；需要复制的文件许可缺失则停止该复制，记录候选而非用未验证代码。

## 5. 交付

改动面、源→目标与许可账、typed API 实例、存储迁移干跑、原/新测试 ID、反例红绿、组合装配与真实浏览器截图、受控 apply receipt/journal、资源清理、真实品牌能力/未验证矩阵。不能以假 adapter 或 DB green 声称 Pi/Codex/Claude 已全面支持。

## 6. Spec Kit 追踪与写入边界

| 故事 | 实施任务 | 主要文件面 | 完成证据 |
| --- | --- | --- | --- |
| US1 机制设置/贡献设置 | PV03/05/08 | profile api、policy、frontend/settings；提供者自己的 glue | G03/G04/G19 |
| US2 管理器 | PV04/05/09 | profile 存储与 frontend/management | G02/G05/G17/G18 |
| US3 配置面 | PV03/06 | profile facets/editors；各域 integrations/profile | G01/G13–G16 |
| US4 切换 | PV07/10 | profile sessions/journal/chat glue；Harness 公开配置接缝、既有会话所有者准入 | G06–G12/G20 |

宿主、Pacthold、Workbench、通用 ui 包默认只读。缺中性能力须单独提出最小契约变更，不把业务搬入核心。Profile 不可自行修改其他正在实施的树。产品 manifest/依赖锁只有整合步骤更新且工具生成；领域写者不同时改根锁。跨包接口先确定后适配，不要求所有实施者共同编辑一个大文件。

独立可完成的存储/表单/注册单元遇到上游未集成可继续；无法证明的运行能力不得用 fake 替代后勾选真实验收。普通构建/类型/夹具缺陷应在授权文件面自行修正并回归，无需每个小错误都停下来；新的产品语义或扩大核心改动才需裁定。
