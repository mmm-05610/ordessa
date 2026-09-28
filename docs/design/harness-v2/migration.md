# Migration and removal ledger

以下是已核对的模块级迁移裁定。实施 T00 必须按目标集成 SHA 展开为逐文件、调用者和持久化入口清单；差异只能补证据，不得悄悄改变归属。

| 现有位置/职责 | 目标 | 本批处理 |
| --- | --- | --- |
| Harness `native_materialization.py` 模型协议/供应商 renderer | Model-provider 的 harness_adapters | 迁纯函数与原 golden tests，调用者同批改；旧聚合品牌表删除 |
| 各品牌 `native.py` | 按函数分属 runtime 与业务 adapter | 启动/路径能力留 Harness；model/provider 字段映射归 Model-provider，不整文件盲搬 |
| `adapters/skill_observation.py` 与品牌 Skill 专属规则 | Skills 的 harness_adapters | 业务解析/解释外移，原生读取通路留受控 runtime action |
| `generic/profile_store/selector/provider/manager`、`resources/profile_codec.py` | 用户预存归 Profile；启动快照归 Harness | 首先分清两种 profile 含义；不把启动资源 schema 当用户 Profile，也不删后以旧名 facade 回接 |
| `importers/models.py`、qoder/native_config 中供应商解释 | Model-provider | 仅迁业务部分，导入来源说明/标识保留；不把 Qoder 导入识别冒充可运行品牌 |
| `plugin.py`/entrypoints 的旧治理注册 | Harness integration | 消费 pacthold.public + server-plugin-api，随平台迁移后的真实接口适配，无 core alias |
| `server_acp` | Harness integration/runtime | 保留通道与 relay 功能；替换 host internals import、旧 profiles.records 依赖与双重身份判断 |
| `harnesses/index.mjs` + Python 品牌聚合表 | 单一 runtime descriptor 生成/消费 | 保留 claude 等既有 alias 和 transport-only 差异；不允许额外注册必须改两张清单 |
| `runtime/access-entry.mjs` / access-transport | Harness transport | 复用 raw/control 分流、close、并发隔离，不恢复 worker-entry 旧链 |
| Claude 官方 0.81.2 包装、受控探针 | 原位置/运行 adapter | 保留 pin 与 probe；不复活 Go Claude，禁止 global providers/set |
| `generic/execution_provider.py`、原生 lifecycle | Harness runtime 或平台已外移旧域 | 只保留有真实消费者的运行适配，执行治理归 Pacthold；逐条列 active caller 后删除重复链 |
| frontend provider/profile stub glue | 对应业务插件 + 实际领域 API | 替换实现分支里的临时 Chat/Session 契约；不得把 stub 顺带并 main |

## 数据与兼容纪律

- `agent_box.plugins` 等既有发行 entry-point/磁盘标识不因目录搬迁自动改名。保持外部名称不等于保留第二实现；入口直接指向唯一新实现。
- 源码旧路径消费者全部迁移后删除旧模块，不留下 sys.modules shim/try ImportError fallback。
- 用户历史 Profile 是否存在、含义和版本必须通过显式指定的测试样本/元数据确认，不能扫描凭据或自动改 HOME。确有格式变化时输出 dry-run 迁移清单并获批，再执行生产数据迁移。
- 不对其他工作树的未提交文件 stash/reset/copy whole tree。业务实现分支只挑已复核模块及其依赖，保留 source SHA 与许可证；不能整分支覆盖新平台。
- 目录搬迁要一起更新 pyproject、npm workspace、测试路径、产品 manifest、构建锁与文档。锁由工具生成，不手改哈希。

## 删除门

AST/依赖扫描证明 core → business、Harness → model/skills 实现、业务 → host internals 为零；旧模块导入必须准确报入口自身 ModuleNotFoundError，不能容忍内部损坏。扫描器不得吞异常。

产品只有一套 runtime/configuration 注册路径，旧 Profile store 与新 Profile 不双写；同一配置文件只有一个写入所有者。所有退役项具备替代调用链或“无 active consumer”证据，不能靠删除测试达成零引用。

## 回滚

尚未合并时回滚实现分支检查点；不影响根 main。集成前在一次性数据根测试新旧版本不可兼容时的明确拒绝。用户数据若需要迁移，备份/恢复步骤单独验收；不能只 git revert 后让旧程序打开新格式。未知运行操作先 reconcile，不以清数据库强行结束。
