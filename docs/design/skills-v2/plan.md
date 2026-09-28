# Technical plan

## 目标目录

```text
plugins/assets/skills/
├── pyproject.toml                     # 单一领域发行版；旧数据标识保留
├── src/ordessa_skills/
│   ├── api/                           # 纯类型/错误/身份；无实现加载
│   ├── formats/agent_skills/          # 从现有实现迁入
│   ├── library/                       # store、records、import、catalog
│   ├── assignments/                   # 用户全局/项目规则、解析、来源解释
│   ├── native_discovery/              # 受限只读观察，不扫未授权 HOME
│   ├── profile_contribution/          # 三态 + 固定版引用
│   ├── harness_adapters/              # pi/codex/claude：纯品牌差异
│   └── plugin.py                      # Server method/port/contribution
├── contracts/                         # 纯 TS DTO/组件 key
├── frontend/                          # Settings、Profile editor、Chat 菜单贡献
└── tests/、frontend/tests/
```

这是业务内模块目录，非每个目录都要独立包。内容库自身可装卸，Profile/Harness/Chat glue 分别按可选贡献注册。生产实体只认一份 SkillsService；保留现有 Skill 资产 ID 与数据版式。Assets 是插件族目录，不新增共享 AssetsService。

## 依赖方向

Skills 管内容和选择规则，Workspace 提供已授权项目身份，Profile 管 Profile 与会话覆盖，Harness 负责真正装载，Chat 只展示/调用当前会话已确认的可用项。项目分配页放 Skills 的 Settings 中，用项目选择器消费 Workspace API；首版不需改 Workbench 项目树或增宿主注册点。

仅更新 `plugins/assets/skills`、必要的 Profile/Chat/Harness 公开 glue 消费、产品装配与构建锁。不得将 Skill 业务逻辑塞入 Pacthold/Server/Workbench；核心缺公开入口时报告接口缺口，不越界私改宿主。

## 原有 Assets-Skill 迁移

现有参考树一个 `ordessa_assets` 包承载 Skill 与兼容 kind。逐符号迁移格式、store、import、catalog、真实 Skill service 到新域；保留 `skill/<assetId>/<revision>`、treeDigest 和已存在 `server_assets`/`server_profile_assets` 的字节含义。旧表其他 kind 由迁移账指定旧业务所有者，不能由 Skills 清空。

数据变更先在合成数据根及已脱敏旧样本上 dry-run、校验正反向映射；若需要修改真实用户数据，另给备份/恢复和用户确认。生产路径迁完删除旧实现和 shim，不能同时注册旧 AssetsService 与新 SkillsService。配置投影从旧 `HarnessDelivery` 移交 Harness application，旧 ledger 只保留可被审计的历史事实，不作为新的 loaded 权威。

## 实施顺序

1. 冻结平台、Profile、Harness、Chat 的集成 SHA/公开接口及 Pi/Codex/Claude 固定版本；冻结现有功能、数据/失败 ID 基线。
2. 迁 Skill 业务核心与存储，包名/外部标识映射。清点非 Skill 旧消费者。
3. 新增范围分配与确定性解析，连 Workspace 与 Profile，冻结现有固定版语义。
4. 迁品牌适配，接 Harness 受管投影/真实装载证据；运行版本不符时拒绝能力。
5. 注册 Settings、Profile、Chat；贯通下一次输入的产品应用链。
6. 删除旧重复路径；干净装包、受控三品牌验证、全套件及数据回滚验收。

冻结 API 后，范围解析与三品牌适配、UI 可分工并行；不能共写产品装配或核心 registry。小测试失败自行修复复跑；强制修改核心契约/触碰生产用户数据/真实模型调用才需新决定。实现任务未全部完成不得报告完成或推 main。

## 需冻结的真实接缝

- Harness v2 custom configuration point、能力声明、受管资源句柄和“loaded”观察接口。
- Profile v2 facet/会话覆盖 public API；旧 Profile 绑定如何映射到新 schema。
- Chat `/`、`+` 的贡献接口及 ACP 原生 Skill 显式调用路由。缺调用路由不妨碍浏览贡献，但 US6 的“调用”不可假绿。
- Workspace 已授权 projectId 和根；projectId 不因项目重命名而漂移。

这些是实施输入门，非允许执行者自行发明另一套平台。所有接口在 T00 与已验收 SHA 对照，记录精确符号/版本；无法落到公开接口则报具体缺口与最小变更。
