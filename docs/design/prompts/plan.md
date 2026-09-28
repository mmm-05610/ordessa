# Implementation plan

## 布局与包边界

```text
plugins/assets/prompts/
├── pyproject.toml                       # ordessa-prompts，含 Python 领域 API/实现/glue
├── src/ordessa_prompts/
│   ├── api/                             # DTO/纯 schema/errors，不加载运行入口
│   ├── backend/                         # repository/service/import/export/snapshot
│   ├── profile_contribution/            # 可选注册入口
│   ├── harness_adapters/                # pi/codex/claude 纯适配与注册
│   └── plugin.py                        # Server 方法及端口注册
├── contracts/                           # 轻量 TS API、组件 key，纯导入
├── frontend/                            # settings 页面、Profile editor、平台组件接线
├── tests/                               # backend/adapter/contract/integration
└── frontend/tests/                      # UI、贡献、边界、构建
```

这是上一轮逻辑树的 Python src-layout 落地，不把每个目录变成独立包。Python 一个领域发行版，前端按平台 workspace 规范配置；contracts 可独立导入，不能依赖运行 entry 的副作用。只有实际构建需要时设轻量 npm API workspace，不向核心 packages 增加 Prompts 业务。

Server plugin id `ordessa.assets.prompts`；前端贡献 id 在本域命名空间内。未发布前查是否已有同名真实 ID，冲突须报告，不能覆盖其他插件。

## 依赖

- 后端 CRUD 依赖 server-plugin-api 公共词汇，不依赖 Profile/Harness 实现。
- Profile glue 声明 Profile 公共 API 依赖；Harness glue 声明 harness API 与 runtime service 依赖。按产品显式组合，缺可选 glue 不破坏独立内容库。
- frontend 用平台 UI、ui-components、Workbench Settings；只有 Profile editor 需要 Profile API。无 Chat 实现 import。
- 应用链只消费 Harness，资源/执行治理沿既有路径；不直接创建 Pacthold execution，不新建执行配置核心。

## 范围

允许：新增 Prompts 域、产品选择/构建锁、对应测试及文档；已有 Profile/Harness 契约内的消费接线。禁止：更改 Server/Desktop host/Pacthold/Workbench 生产实现、改用户项目指令、停止服务、创建真实模型调用。

如果既有提示片段代码在选定集成基线被发现，先列 owner/caller/data-ID 并迁唯一实现；不得假定 main 已有本插件，也不得迁移所有 server-compat 提示/记忆功能来扩大任务。

## 执行顺序

1. 冻结平台/Profile/Harness SHA 和三品牌 pin，核查接口/配置动作可达。
2. API/存储/授权/快照纯测试；独立内容管理页。
3. Profile 贡献与三品牌 adapter（已冻结 API 后可独立实施）。
4. 真实下一次提交链与三品牌受控装载证据。
5. 产品构建/隔离安装/跨包边界/全套差分及 UI 验收。

## 阻塞处理

平台/Harness 尚未交付时可完成不依赖运行端口的任务，但不得用 mock 代替最终验收。少数 persona/system-replacement 入口不可用按能力矩阵如实隐藏；三主品牌 instruction 必需链缺失则明确 BLOCKED 项，继续其他独立任务，不宣布整包完成。

接口能力不足向其所有者交付精确输入/输出/反例；不可自行跨包创造第二服务。正文存储、UI、引用都不需要扩核心；runtime action 若需补齐应属于既定 Harness 实施范围。

## 数据与升级

首版 schema 新建于插件私有数据目录，路径由已有产品数据根服务提供；SQLite transactions 与 schema version 受测，不改 Server 标记/core DB。已有用户 Markdown 仅经用户选择复制导入，原文件不动。无后台扫描、默认同步或全目录迁移。

升级测试用合成副本；回退版本不支持新 schema 时明确拒绝打开，不删库。产品 manifest 和 lock 由正常构建生成，不能手改哈希。根树保持 main，实现只在批准 worktree。
