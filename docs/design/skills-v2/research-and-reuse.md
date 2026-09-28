# 官方事实与模块级复用

核查时间：2026-09-28。官方机制不自动等于 Ordessa 当前固定版本已经具备。第三方文档没有授权拷贝源码，新增外部依赖/源码复制需另列版本、许可及 NOTICE。

## 官方机制

| 来源 | 核查到的事实 | 本设计的约束 |
| --- | --- | --- |
| [Agent Skills 规范](https://agentskills.io/specification) | 可移植文件夹和 SKILL.md 元数据格式 | 作为基础包校验；品牌扩展另核 |
| [Pi 官方 Skills](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/skills.md) | 用户/项目发现、元数据先于正文、`/reload`、显式 `/skill:name`、同名警告 | 投放/发现/加载/调用分层；冲突前置拒绝 |
| [Claude Code 官方 Skills](https://code.claude.com/docs/en/skills) | 企业/个人/项目/子目录/插件有不同装载规则；显式与自动调用 | 不直接用原生目录层级实现 Ordessa 范围覆盖 |
| [Codex 官方 Skills](https://learn.chatgpt.com/docs/build-skills) | 项目/用户目录、渐进披露、显式/隐式入口 | 实际桥/ACP 能力必须在固定版本探测 |

主参考是上述官方机制、已存在本仓实现与 [Harness 配置盘点](../harness-configuration/README.md)，不采用 agent-config-inventory 作为能力权威。

## 已有实现的逐模块裁定

参考 worktree `plugin-assets-skills-impl @ 752f148b1b`，未合并、不视为最终集成基线。

| 模块 | 来源文件/测试 | 处理 |
| --- | --- | --- |
| Agent Skills 格式、树遍历与权限边界 | `formats/agent_skills/frontmatter.py`、`tree.py`、`validator.py`；test_frontmatter_spec/test_tree_bounds | **直接迁**到 Skills 域，保留边界测试；只为目标版本验证增量改动 |
| 不可变修订仓 | `server/store.py`；test_store_atomic/test_records_pinning | 直接迁算法和 `skill/<assetId>/<revision>` 布局；保留 treeDigest 字节规则，迁出时不重建 Skill 仓 |
| 分块导入 | `server/import_transfer.py`；test_import_session | 复用 begin/chunk/preview/commit 校验及漂移反例；有来源新增 Git 时扩独立 fetch 层，不改核心传输安全规则 |
| 目录/版本/元数据 | `server/records.py`、`catalog.py`；test_catalog_snapshot | Skill 行与 ID 保留；新增 global/project assignment 表及 CAS；历史其他 kind 的行不能被本插件删除或误认成 Skill |
| Profile 绑定 facet | `profile_contribution/binding_facet.py` | 保留固定修订事实，迁为 Profile v2 三态贡献；`ProfileRegistrationPort` 旧方法不能和新 facet 并行长期存在 |
| 投影/证据 | `harness_delivery/delivery.py`、`server/projection.py`；test_delivery/test_projection_evidence | 只迁受管树摘要校验与层级概念；把实际写入交 Harness，修正摘要匹配就记 loaded 的假证据，删第二应用器 |
| 能力注册表 | `harness_delivery/capabilities.py`（当前空） | 只参考“没有证据就不声称”的规则；接 Harness adapter 正式能力目录，不维持第二份静态品牌表 |
| 桌面列表/预览 | `desktop/src/view.tsx`、`model.ts`、测试 | 保留具体 UI 内容组件，替换已迁平台注册与范围视图；通用控件消费 `@ordessa/ui`，不移植其他桌面 store |
| 旧 AssetsService 与 wire | `server/service.py`、相关规格 | Skill 管理部分留一个服务；通用 Assets 门面、mcp/command/plugin 旧能力不归 Skills，仍按迁移账保全现有消费者 |

“复用”要求保真 diff、来源 SHA、测试与许可证记录。没有公共 API 的相邻插件私有文件不直接 import；API 缺口先向所有者提交精确需求。**新增核心代码主要是范围规则解析和原生适配**，不重复造内容库或导入协议。
