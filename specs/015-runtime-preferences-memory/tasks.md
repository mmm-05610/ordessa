# 015 · tasks

勾选=已完成且证据在 report.md。任何一格"不支持/未知"都必须带证据或说明，不因完不成而改判。

## P-A runtime-preferences（`plugins/assets/runtime-preferences`，基线=main）

- [ ] RA-1 域骨架：包结构/pyproject/manifest；facet `assets.runtime-preferences` 注册进
      C2 `harness.configuration-adapters`；与既有 facet（如 model-provider 的）不撞；
      重叠注册拒的 conformance 用例绿。
- [ ] RA-2 品牌骨架 `adapters/{brand}.py` ×8（pi/codex/claude/hermes/opencode/dsh/qwen/kilo）：
      assess/compile/verify 三方法 + `registration_manifest()` + `common.py` 字节稳定渲染；
      门形照 `plugins/assets/model-provider/adapters/tests/test_adapters_conformance.py:80-103`
      （重叠注册拒、版本区间不相交拒），只仿形制不 import。
- [ ] RA-3 逐家逐组编译表：八家 × 四组（compaction/memory/shell/retry）逐格三态结论
      （可用+官方证据 / 不支持+证据 / 未知）；请求级参数（reasoning effort、service tier、
      请求 retry/stream timeout）不收（归 model-provider）。
- [ ] RA-4 管理员约束排除：与权限/管理员纠缠的键（Codex shell env 权限行、Claude 环境/
      运维管理员项）标记 admin-only 不可预设，出现在 profile 编辑面时禁用并说明。
- [ ] RA-5 profile facet 四 item（compaction/memory/shell/retry）：默认值+整项覆盖语义；
      `ProfileContributions.forScope().addEditor()` 编辑组件；memory item 是纯类型参数
      （开关/预算/抽取模型引用），不含服务置备。
- [ ] RA-6 C4 应用链：逐键 applyMode（reload/重启/下次会话/未知）按官方证据核实，
      `ConfigurationApplicationService.apply` 走通一条端到端样例（含失败反例：unsupported
      键返回明确失败而非静默）。
- [ ] RA-7 隔离与反例测试：两会话不同四组参数互不影响；覆盖清理语义（选新 profile
      清覆盖）；golden 转录（字节稳定）。
- [ ] RA-8 report.md：逐格结论表 + 证据链接 + 未决项；known-issues 需要登记的如实登记。

## P-B memory（`plugins/assets/memory`，基线=main+merge 两支，见 dispatch）

- [ ] MB-1 域骨架：包结构/manifest；facet `assets.memory`（开关/预算/抽取模型引用/
      绑定品牌集）注册进 C2；profile 记忆绑定预设 item。
- [ ] MB-2 置备器：检测 Docker/compose v2（缺失=unsupported 诚实报错）；生成 .env
      （随机 POSTGRES_PASSWORD/ADMIN_API_KEY/JWT_SECRET、`MEM0_TELEMETRY=false`、
      端口从产品配置分配、数据目录=data-root 仓外）；compose 子栈只起 server+postgres
      （不起 dashboard）；mem0 版本 pin 并记录 SHA。
- [ ] MB-3 生命周期：启动/停止/探活（REST `/docs`）/升级（先备份再迁）/卸载保留数据；
      密钥不落仓、不进 Profile（引用制）。
- [ ] MB-4 LLM 接线：从 model-provider 解析 bundled 同名 provider（openai/anthropic/
      gemini）写入 .env；无 bundled 同名 provider=明确 unsupported；E2 假端点实测
      `POST /configure` 传 base_url 是否生效（可用须附调用证据，不可用登记 unsupported）。
- [ ] MB-5 捕获管线：订阅会话轮次/结束事件（AR-3；契约缺失则登记报回，不越界改 agent 域）；
      抽取调用默认关、显式授权才开（授权状态可诊断）；受控测试假 OpenAI 兼容端点，
      断言请求形状+失败反例（端点 500→记忆缺席不阻断会话）。
- [ ] MB-6 注入管线：instruction 槽命名 facet `ordessa.memory` 产出记忆上下文块
      （AR-4 合并顺序/转义与 prompts 域对齐；挂点缺失则登记报回）；无原生记忆四家
      （pi/dsh/qwen/kilo）默认挂载，有原生四家默认不挂（配置可改，但标注"与原生记忆并存
      可能重复"）。
- [ ] MB-7 第三方标注：设置页/诊断/记忆查看界面/THIRD-PARTY-NOTICES 四处：
      "记忆引擎 mem0（Apache-2.0）· 本地自托管（Docker）· 遥测已关闭"。
- [ ] MB-8 边界测试：数据目录在 data-root；两 profile 记忆命名空间隔离（user_id 分域）；
      服务停止/断网=记忆缺席、会话照常（缺席≠错误，日志可查）；无凭据入库。
- [ ] MB-9 report.md：实测记录（含 POST /configure 结论）、Docker 前置、bundled 限制、
      known-issues 登记。

## 完成定义

两包各自 report.md 齐全、任务全勾或如实标注未决原因；不要求对方包完成；组合验证
（两包+model-provider+prompts 并合后的端到端）属 integration-request，不在单包内做。
