# 015 · plan

## 事实（写包时已核实）

- F1 C2/C4 在 main：`plugins/harness/src/ordessa_harness/contributions.py:20-21`
  （`harness.runtime-adapters` / `harness.configuration-adapters`，重叠 adapter_id 拒）；
  `.../application/configuration_service.py:150` `ConfigurationApplicationService.apply(plan_id,
  operation_key, submission_permit)`。
- F2 main 上 harness 贡献点只有上述两个；**instruction 内容无开放贡献 API**，
  `harnesses.toml` 的 slots 词汇为 provider/permission/instruction/mcp/skill/hooks——
  四组运行参数不在 slots 里（印证走 C2 参数而非 slot）。
- F3 八家压缩均有原生配置（文档级证据，`docs/design/harness-configuration/harnesses.md`）；
  原生长期记忆只有四家（Codex/Claude/Hermes/OpenCode）；Qwen 的"memory"是静态指令陷阱。
- F4 **OpenMemory 已转型**为跨 harness 会话迁移 CLI（TypeScript，MIT）；原记忆 MCP
  server 仓库 `mem0ai/mem0-mcp` 已归档。引擎改为 mem0 本体（2026-09-28 用户裁定）。
- F5 mem0 自托管 server（`mem0ai/mem0` `server/`，Apache-2.0，main 分支核实）：
  官方部署仅 docker compose——FastAPI server（:8888）+ `pgvector/pg17` Postgres（:8432，
  记忆/认证/向量一体，无替代后端）+ Next.js dashboard（:3000）；REST+OpenAPI `/docs`，
  程序访问 `X-API-Key`，`make bootstrap` 建管理员+首个 API key（只打印一次）。
- F6 mem0 server LLM 仅 bundled openai/anthropic/gemini（embedder 仅 openai/gemini）；
  `server/main.py` 无自定义 base_url 入口；`POST /configure`（admin）收任意 Dict 直传
  `update_config`，自定义端点是否生效**未实测**（P-B 的 E2 实测项）。
- F7 mem0 server 默认 `MEM0_TELEMETRY=true`（匿名 onboarding 事件）；置备必须显式关。
- F8 shell/重试参数约半数家有，且多与权限/管理员约束纠缠（Codex shell env 在权限行、
  Claude 环境/运维含管理员项）——管理员项不可作普通预设。
- F9 P-B 不依赖 mcp 域（REST 直连，不经 MCP）；依赖 model-provider（provider 解析）与
  prompts 域（instruction facet 合并规则，AR-4）。

## 做法要点

### P-A（纯配置叶子，仿 model-provider adapter 形制）

- `adapters/{brand}.py` ×8：三方法 assess/compile/verify + `registration_manifest()` +
  `common.py` 字节稳定渲染；conformance 门照抄
  `plugins/assets/model-provider/adapters/tests/test_adapters_conformance.py:80-103` 的形状
  （重叠注册拒、版本区间不相交拒）。只仿形制不 import 其代码。
- facet `assets.runtime-preferences` 四 item（compaction/memory/shell/retry）；值=
  参数对象+模型/后端引用。profile 编辑组件经 `ProfileContributions.forScope().addEditor()`。
- 逐键 applyMode 按 sources-and-gaps R3 核实（reload/重启/下次会话），未证实不写热更。

### P-B（mem0 自托管置备 + 管线）

- 置备：生成 .env（随机 POSTGRES_PASSWORD/ADMIN_API_KEY/JWT_SECRET、
  `MEM0_TELEMETRY=false`、端口走产品分配不硬编码、数据目录=data-root 仓外）；
  compose 子栈只起 server+postgres 两服务（不起 dashboard，产品经 REST 管理）；
  Docker/compose v2 前置检测，缺失=unsupported 诚实报错。
- LLM 接线：从 model-provider 解析 bundled 同名 provider（openai/anthropic/gemini）；
  自定义 OpenAI 兼容端点走 E2 假端点实测 `POST /configure` base_url，结果如实登记。
- 捕获：订阅会话轮次/结束事件（AR-3 实测 agent 域契约；缺则登记报回）；抽取调用
  默认关、显式授权才开；受控测试全走假端点。
- 注入：instruction 槽命名 facet `ordessa.memory`（AR-4 与 prompts 域指令 facet 的合并
  顺序/转义）；无原生记忆四家默认挂载，有原生四家默认不挂。
- 标注：设置页/诊断/记忆查看/THIRD-PARTY-NOTICES 四处。

## 未决（执行中登记，不假装已定）

- AR-3 事件面在 main 的真实形态；AR-4 prompts facet 合并规则的最终形状（EXT 在做）。
- `POST /configure` 自定义端点是否生效（E2 实测定）。
- 各家逐键版本门槛（执行者按 sources-and-gaps 完成标准逐键补证据）。
