# Implementation plan（待实施）

## 包归属

```text
plugins/
├── permissions/
│   ├── api/                 # 轻量领域契约与类型；消费端只依赖 API
│   ├── backend/             # policy repository、ceiling、authorizer、approval facts、wire 贡献
│   ├── frontend/            # Settings/Profile 贡献与受限审批卡
│   └── adapters/            # pi/codex/claude 权限与审批投影
└── assets/
    └── sandbox/
        ├── api/             # native-sandbox facet/证据类型；不与 Pacthold SandboxV1 同名
        ├── backend/         # native 选项/版本管理与验证
        ├── frontend/        # Settings/Profile 贡献
        └── adapters/        # pi/codex/claude 原生隔离配置转换
```

这是业务域逻辑树；物理 npm/Python 包以已验收的平台导出与构建习惯定名，不预先设第二产品加载器。两域可分别安装；与 Profile 的 glue 应为可选 entry，不能让基础 Permissions/Sandbox 实体服务硬依赖 Profile。`products/server` 仅声明启用已有插件，品牌字段仍留各业务 adapters。

## 阶段与依赖

| 阶段 | 工作 | 准入/退出 |
| --- | --- | --- |
| T00 | 只读基线：集成 SHA、当前 Pi/Codex/Claude pins、ACP 完整请求流、Profile v2 与 Harness v2/Server 公共端口；冻结旧数据/红 ID | 发现 pre-effect 或 C2/C4 接缝缺失时记录精确缺口；只申请最小公共契约修改，不能私建后门 |
| A | Permissions 数据/规则/上限、旧审批迁移与适配；先后端受控拒绝 | deny/ask/allow、旧数据兼容与上限不可提升反例全绿 |
| B | Sandbox asset schema/品牌编译/实际覆盖核验 | 非支持/未知/平台不符与跨会话串扰反例全绿 |
| C | 两域经公开点装配到 Harness、Profile、Settings、Chat；ACP 审批同 owner 回路 | 受控 Pi/Codex/Claude 各有真实性证据，未实现格显式关闭 |
| D | 迁移旧生产入口、删除重复权威、产品装配、独立包与回归门禁 | 无双路 approve/无旧 last-match 管理上限；逐 ID 红账本无未解释增量 |

A、B 可以在不同 worktree 各只管本域；**C 的同一 native 配置字段归属和 ACP 控制接缝必须串行集成**，避免两个执行者同时修改 Harness/产品装配。`apps/server`/Pacthold 不接受业务规则；若必需的中性 pre-effect 服务注册点不存在，需平台会话加最小可复用接缝并用另一个非权限业务反例证明通用性。不能在插件里复制内核授权机制。

## 迁移、停用和回滚

旧 `server_approvals` 与事件序列、`approvals.decide` wire ID 保持；新版 Permissions 取得唯一所有权后，compat 的调用者改经公开域端口，删除旧处理器/重复路由。旧 Profile `permission_preset`/`permission_rules_json` 保留可读并版本化导入用户意图，不当管理员上限；不能等价的条目 `needsReview`，不得自动赋 allow。另一个原生 sandbox 名称/字段若与现有 Pacthold `SandboxV1` 同名，只改新插件 API 命名，不改既有持久化 ID。数据用户迁移需单列备份、幂等、逆向读取测试及授权门。

停用插件：无活跃依赖可卸载，UI 隐藏、数据保留。活跃审批/实例或未对账操作 busy；不可为了卸载把悬置的授权处理为 allow。回滚到旧版本只允许旧程序能理解的已验证数据；否则原数据快照+明确不可回滚声明，不靠隐式字段丢弃。
