# Technical plan

## 目标目录与依赖

```text
plugins/assets/command-templates/
├── pyproject.toml                    # 一个独立后端领域发行版
├── src/ordessa_command_templates/
│   ├── api/                          # DTO、schema、typed errors
│   ├── library/                      # 修订、CAS、归档、导入/预览
│   ├── expansion/                    # 封闭语法 parser/renderer、golden vectors
│   ├── assignments/                  # 全局/项目解析及来源
│   ├── profile_contribution/         # 可选三态 facet
│   ├── harness_adapters/             # 可选 Pi/Claude/Codex native 投影
│   └── plugin.py                     # Server 公共方法/端口注册
├── contracts/                        # 前端领域 DTO/轻量 API
├── frontend/                         # Settings、Profile、Chat glue
├── tests/
└── frontend/tests/
```

这些是域内模块，不是每行一个发行版。纯库/服务不强依赖 Profile/Chat/Harness；可选 glue 按产品选择和宿主公共 scope 装载。前端只依赖平台与本域 contracts，Chat glue 依赖 Chat 公开贡献 API；Chat 不 import 模板插件。后端插件借 Server 公开注册 API 提供服务；Pacthold 不知道 templateId。产品装配只选择插件及 build lock，不写品牌分支。

## 实施批次

0. 冻结集成 SHA、测试红账本、真实 API（Server 贡献、Workspace project、Profile facet、Chat `addInputSource`、Harness C2）；固定 Pi/Codex/Claude native+adapter pin。main 目前缺完整 Chat 输入契约，记前置任务而非自造第二 registry。
1. 做纯后端库：不可变版本、权限/CAS、受限导入、封闭参数 parser/renderer、解析与冲突。先以无 Profile/Harness/Chat 运行。
2. 对接 Profile/Workspace 和前端 Settings；Profile 仅引用固定 revision，项目身份由 Workspace 授权；UI 草稿/错误边界实测。
3. 对接 Chat `/`/`+` 当前目标查询、参数预览、插入现有草稿和测试；缺最小动作类型由 Chat 所有者补，而非模板插件改 Chat 内部。
4. 可选品牌 native adapters 按矩阵逐格实现/标不支持；不能为宣称完整而在 Claude 双投影或 Codex 依赖 deprecated 路径。
5. 产品显式装配与版本化锁、受控三品牌用户消息端到端、边界/红账本/键盘验收、独立审阅。

冻结 API 后，纯库、前端组件、品牌评估可由不同实现者并行；它们**不能共写**产品装配、公共契约或同一测试。各模块小失败就地修复并重跑；若公共注册点缺失，精确报接口缺口和最小反例，继续无关任务，最终不可假绿。

## 迁移、回滚与禁区

当前通用 `plugins/commands` 不持久模板，无数据迁移。用户现有 Pi/Claude/Codex 文件只有明确导入才复制进本域，不改源文件。旧 compat 若另有资产 kind 不能清表或复制两份服务；先列真实所有者。产品关闭新插件应回到旧 Chat 行为且不丢原始用户草稿/模板私有数据。schema 回退不可安全读新版时拒绝；备份/恢复合成样本并校验摘要。

禁止改 apps/server、packages/pacthold、Workbench/desktop host 生产业务；若公开接口缺失则由接口所有者独立最小变更。禁止任意 shell/URL include、偷读 HOME、真模型调用、双 ACP client、旧逻辑 shim。根树保持 main，实施在独立 worktree，未经授权不 push/merge/改用户数据。

## 开工门

集成平台/Profile/Harness/Chat 的已验收 SHA 和真实类型必须在 implementation-baseline.md 逐项固定；若 `addInputSource` 尚未发布，先排 Chat 契约项。固定品牌矩阵用受控 probe 区分 supported/unsupported/unknown；L3 能力不能仅凭设计或官网宣称。打包前把每条 FR 的正反例与 G 门对齐。
