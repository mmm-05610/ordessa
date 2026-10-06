# 固定输入权限来源与核心测试边界（PARTIAL）

前置提交：a5524f05a74d0e3ee26a58ce11c08da3c5958afb。初始 tracked clean，只有未跟踪 `.env`，不读取、不入库。用户明确裁定“采用，统一使用服务器配置”。

## 写权与修改

三名 gpt-6-luna 执行源代码、测试及独立审查，主会话负责指导、读审、串行测试、文档和 Git。

- core_impl：仅 inputs.py/public.py，部署时绑定原 InvocationIssuer；不同实例在 claim/query 前拒绝，初次未配置不能通过方法参数晚注入。reserve 仍可无 issuer 登记事实；不新增权威或持久账。交叉审查发现原 claim 在请求级权限预检前读操作，追加共享既有 environment/principal/reserve invoke 预检；Node write ACL 仍在原 intent 导出目标后执行。
- wire_impl：仅新增 test_input_issuer_binding.py（9 个执行项）和四个原 fixture 的构造/冷恢复绑定；原断言保留，无 wire/CLI 修改。覆盖不同 authority、相同 authority 不同 issuer 对象、公共装配重组、未配置不能晚注入、unknown 不重发、三个请求级拒绝零读取。
- core_review：将 SQLite 跨组件测试从核心 tests/environment 移至 tests/integration/environment，保留原 11 用例和 46 assert，只调整 SIGKILL 子进程源码路径；新增 2 项静态位置/保留反例及独立 CI 步骤，未改核心方向扫描器。输入源码及测试由跨作者只读复核。

核心不导入具体 Harness 或 SQLite 后端；部署提供同一可信签发来源，原 Harness verifier 继续使用原契约。没有输入 writer、结果回写或新的材料/访问协议。

## 命令与过程账

解释器为本实施树上层 `.venv-ordessa-py312/bin/python`。以下测试串行执行；作者冻结后才运行，失败后只释放对应文件作者修正再冻结。

核心/跨组件命令：

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests tests/integration/environment -q --tb=short
```

首次 273P/1F，exit1，7.86s：新保留守卫用系统 Python 3.14 的 ast.dump 摘要与项目 Python 3.12 比较而误报。原 11 迁移测试均通过，核心原三方向红消失。作者从只读 HEAD 的迁移前源提取基线，改为版本无关规范化，仅忽略空 type_params，非空仍参与，按源位置排序断言；静态核对 Python 3.12/3.14 同摘要。不从修改后测试盲生成基线。复跑 **274P/0F，exit0，7.46s**：核心 261、迁移集成 11、定位守卫 2，无 skip。原 suite 272（269P/3F）中的 11 移至独立集成入口，因此计数减少不代表删测。

输入组合命令：

```bash
PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:packages/backend/harness-transport/src:plugins/harness/records/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_input_issuer_binding.py products/agent-tools/tests/integration/test_managed_input_reservations.py docs/implementation/agent-tools/evidence/agent-unit-model/test_public_input_composition.py docs/implementation/agent-tools/evidence/agent-unit-model/test_sessionless_input.py docs/implementation/agent-tools/evidence/agent-unit-model/test_first_input_publication.py docs/implementation/agent-tools/evidence/agent-unit-model/test_first_input_journal_publication.py -q --tb=short
```

首次收集 exit2，1E，0.45s：新测试错误地从 environment-api 导入 InvocationAuthorityRefused，改用原 pacthold.agents.invocation 错误类，不扩大 API。第二次 132P/1F，exit1，10.35s：新 unbound claim 夹具按 draft_id 存 capture，而原 port 按 capture_id 查；只改夹具 key，保留拒绝/零作用断言。最终 **133P/0F，exit0，10.04s**（新9＋原124）。

产品全套命令：

```bash
PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:packages/backend/harness-transport/src:plugins/harness/records/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests -q --tb=short
```

最终 **788P/0F，exit0，217.32s**，句柄4875已terminal。本轮重新实跑，无skip；与133项组合存在重叠，不相加当独立场景数。

## 证据范围与缺口

输入新增为临时真实 SQLite＋受控权限/owner 的 C 级契约证据，原迁移测试包括自有 Python/SQLite 子进程 SIGKILL 恢复（已通过），不是原生 Harness P 或模型 M。本轮新增原生 P0/M0。核心 runner 自报 GREEN_NO_SKIPS 仍同时列出 worker/sidecar/ACP 包等资源 ABSENT，不能据此宣称相关产品可用；资源缺席范围保留。

完整资源/SecretRef 授权材料路由、访问租约签发/撤权/实际 writer fence、生产输入 writer 与双来源回执、结果投影、CLI/Skill 及发行隔离仍 PARTIAL。全 optional 未发送时恢复配置基准的另提案尚待裁定，不把本次裁定扩展到该分支。

跨作者静态终审无当前切片具体阻断：零作用断言同时检查持久 step、权限/状态/owner/native 调用，不只看 issuer 私有集合；请求级拒权也 spy 确认零 read_operation。保留守卫纳入所有语义字段，非空泛型参数不忽略。限制：该守卫当前 JSON 编码不支持 future complex/Ellipsis 字面叶值；原 11 测试不含这些，今后加入需显式维护编码，不静默绕过保留检查。

无用户服务/数据/凭据/全局配置操作、第三方安装、模型调用、push 或主树合并。严格五工单校验 exit0 仅为材料检查；费用 unknown，子代理 tokens 以平台账为准。
