# Implementation plan

## 包与依赖方向

```text
plugins/assets/subagents/
├── api/                       轻量 DefinitionRef/DTO/schema；不依赖实现
├── backend/
│   ├── store/                 定义修订、来源、CAS、归档
│   ├── assignments/           默认/项目/Profile 引用解析
│   ├── service/               鉴权、预览、迁移、wire 描述符
│   └── adapters/
│       ├── claude/            该品牌配置适配器
│       ├── codex/
│       └── pi/                只对 Harness 已注册可信扩展入口提供定义
└── desktop/
    ├── settings/              内容库/默认分配
    ├── profile/               Profile facet/editor glue
    └── chat/                  可选受控调用/管理入口 glue
```

该树是目标逻辑模块，不强制每个目录都成为独立发行版。`backend/store` 对 Profile/Chat/Harness 不建立实现依赖；glue 可独立启停，避免“没有 Profile 时无法管理定义”。业务插件声明自己拥有的 wire/Settings/Profile/Chat/配置 adapter 贡献；`products/server` 与桌面产品只按公开清单启用，原则上不改宿主内核。通用注册/资源/生命周期继续用平台实际公开 API；缺接口先按 T00 提缺口，绝不在本域重建一个注册中心。

品牌配置适配器消费 Harness 轻量 API，不能 import 其 impl；Harness runtime 持有目标路径与动作执行权限。目标仍经现有 Server→Harness→ACP owner；此包不建 ACP 客户端、不缓存原生秘密。Pi 运行扩展若成立由 Harness 明确拥有，不塞入本目录的数据包。Pacthold 不知子代理定义字段；Server 只负责通用鉴权/注册/传输，业务 `run_subagent` 不进通用 Host。

## 阶段依赖

1. **冻结事实**：平台/Profile/Harness 最终 SHA，三品牌 pin、实际定义/调用入口、旧数据、注册红账本。没有这个矩阵，不能称“已支持”。
2. **独立内容服务**：不可变版本、来源与格式限制、CAS、数据迁移 dry-run、用户/项目授权；可独立测试，不等品牌支持完成。
3. **分配/Profile/前端**：默认/项目/Profile 决策、确定性解析、设置与编辑器、可选 Chat 浏览；跨包只消费公开契约。
4. **品牌装载与运行**：Claude/Codex 受控原生配置；Pi 若接受 extension-backed 路线，先在 Harness 审核固定扩展执行入口，再接定义 adapter。每品牌按“保存→分配→投放→原生加载→受控调用→移除/恢复”逐级证明。
5. **产品迁移与交付**：只启用唯一实现；旧 Profile 派工代码另由其原所有者清理，不因本插件上线而删除仍有用户的授权边/历史。干净安装、逐 ID 回归、恢复和独立审阅后请求合并。

## 数据与兼容

先导出 `server_assets`/旧 Profile 相关记录的 kind/ID/引用表，再确定有没有可迁纯定义。遇混合“定义+派工授权”记录，应拆字段并保留原授权 owner；无法证明可逆就不要自动迁。旧 wire 方法 ID 与磁盘格式不擅改，任何用户数据写入须备份/回滚步骤和授权。一次替换必须保证不存在两个同名定义服务/入口，否则产品激活拒绝而非 last-wins。

## 风险与有界阻塞

- **B1**：平台/Harness/Profile 最终接口未冻结。T00 用真实导出填接口表；不阻止内容服务纯逻辑与设计细化，阻止生产集成宣称完成。
- **B2**：Claude/Codex 当前 ACP 入口可能不提供装载/显式调用控制。给 Harness 具体目标 DTO 与探针，沿其已有控制所有者补最小接口；若同会话恢复不可证则该格 unsupported，不改用普通 prompt。
- **B3**：Pi 无内建定义机制。要支持须经独立 Harness executable-extension 安全审查、pin、许可、隔离、取消/恢复、工具权限验证；未交付前 Pi 格标 unsupported/unknown。它不阻塞 Claude/Codex 的独立模块，但阻塞“三品牌全绿”声称。
- **B4**：模型/工具/MCP/Skill 的真实引用服务可能未同时交付。可以先实现不含相关引用的定义与 UI；包含引用的定义应用前拒绝，不向 native 写一份残缺文件。

不可用一律记录明确局部原因、继续不受影响模块；不可通过新增 `apps/server` 业务分支、旧 shim、跳过门禁或“表单可保存”充当落地。整体交付报告按实际完成能力逐格列结果，不以无人值守周期结束当完成。
