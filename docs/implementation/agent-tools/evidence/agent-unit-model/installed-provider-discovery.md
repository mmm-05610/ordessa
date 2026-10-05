# AU003 独立提供者发行／AU005 已安装 CLI 真实 HTTP 发现

工作基线 `36de74fd3277a7762644959173066ded2831f55d`。保留此前未提交四文件及两次发行回执，主会话是唯一源码、测试、Git与账本写者。Skill reviewer只读复核，未执行测试/Git；Codex另只读盘点下一旧Model入口。未改冷代次提案或核心。

## 变更及边界

六个自有包从新鲜源码副本构建 wheel，以 no-index/no-deps 安装到新 venv；三家分别在 `python -I` 中经唯一 Environment/CoreRegistry 激活。Server、旧大 Harness、产品、SDK、Server Plugin API 均缺席；可选 wrapper 可 import/construct，调用 descriptor 缺 API 明确拒绝。另证明未选两家没有导入。

发行脚本要求显式新证据路径，拒绝覆盖；当前 HEAD/dirty paths、六 wheel 摘要、逐命令退出码和临时清理均有记录。失败或 timeout 也写独立失败回执，timeout 不伪造 exit0。旧成功资产不覆盖；故障仍可复查。

新客户端测试构建并安装独立 CLI wheel，证明其 venv 没有核心、服务、三家提供者或 SDK；仅调用实际自有子进程 Uvicorn/Server 的公开 wire。服务显式选择三家独立 wrapper，默认 provider 不支持 start，子进程禁止 native subprocess spawn。验证 list、逐家 describe、完整环境/owner 身份、错误 Bearer、外环境引用、缺 authority 不宣告准备/配置、断连拒绝，关闭自有服务。原 helper 默认 Profile 路径保留。

这是受控 Registry C、真实隔离 Server/CLI 进程与安装证据；不是三家真实 native Harness P 或模型 M。无用户服务、凭据、全局配置、登录、第三方安装或更新。`productReady=false`、`coldRecoveryVerified=false`、模型调用0；providerRegistryObserved 不等于 runtimeVerified。

## 串行命令及结果

解释器 `PY=/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`，下列 `$PY` 指此绝对路径。提供者源码环境：
`PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:packages/backend/harness-transport/src`。

| 命令/场景 | 退出码/计数 | 说明 |
| --- | --- | --- |
| `$PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration/test_installed_provider_service.py -q` 初稿 | 1 / 1F / 4.36s | foreign参数既有CLI发前拒2，误期待3；修测试预期不放宽源码 |
| 上项加 `test_profile_service.py` 首组合 | 1 / 5P1F / 12.87s | offline evidence原值unobserved，误期待无值；修精确预期 |
| 两文件修正后组合 | 0 / 6P / 12.89s | 首完整正反例 |
| 产品integration＋三家tests跨包同进程首尝试 | 2 / collection 3errors / 0.47s | 同名test_client/test_provider模块冲突；未删cache/skip，改各包独立pytest进程 |
| `$PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration -q` | 1 / 311P1F / 16.98s | 唯一红 `test_three_independent_server_owners_share_registry_and_restart_identity`，原严格cold目标保留 |
| `$PY -m pytest plugins/harness/codex/tests -q` | 0 / 166P / 2.12s | 上述源码环境，各包独立进程串行 |
| `$PY -m pytest plugins/harness/pi/tests -q` | 0 / 213P / 3.18s | 同上 |
| `$PY -m pytest plugins/harness/claude-code/tests -q` | 0 / 162P / 12.70s | 同上；不是native任务 |
| `$PY -m pytest packages/backend/harness-transport/tests/test_acceptance_evidence.py -q` 初次 | 0 / 3P / 0.49s | 原broken fixture是损坏TOML，只证明坏包拒绝 |
| 同门末端复跑 | 0 / 3P / 0.44s | fixture改真实换行＋要求缺backend错误；现为真实no-index own package backend缺席失败，另覆盖timeout、已有回执拒绝 |
| 两HTTP文件末端复跑（上述源码环境） | 0 / 6P / 12.81s | 安装调用均timeout60；真实HTTP发现及原Profile回归 |

实际发行命令：
`$PY packages/backend/harness-transport/tests/acceptance_install.py --evidence docs/implementation/agent-tools/evidence/agent-unit-model/<新文件名>`。

- `au003-provider-server-bindings-install-36de74.json`：第一次12条全exit0；版本尚未加入失败回执包装。重复调用预期exit1、原SHA不变。
- `au003-provider-server-bindings-install-final-36de74.json`：包装改动将内嵌probe多缩进一层，10条中第10条exit1，IndentationError；外层exit1，status=failed、临时清理true。保留失败，不覆盖。
- `au003-provider-server-bindings-install-verified-36de74.json`：修textwrap.dedent后新鲜构建/安装/三探针12条全exit0，外层exit0，六wheel摘要、清理true。重复调用预期exit1/FileExistsError，证据字节及SHA256 `00bf034b4a3f11aca70f24725f85fab8cd4ed38a860a7a2bd45b718858b7fc0b` 不变；验证包装exit0。AST检查probe语法及fixture真实换行exit0。

新增 installed 测试1＋故障门3；快照不累加成测试总数。全Core/Server本轮未重跑；继承Core三红、旧ServerPi红仍在既有记录。新的cold红已在known-issues登记，临时既有root拒绝不是持久代次修复。

## 剩余范围

生产Directory/Invocation/材料/SecretRef/capture/receipt/Session owner、各家真实通道接线、完整生命周期、旧Model/sidecar装配、connect/applyProfile/stop/release/tasks/results、三Skill真实Agent评估及完整A18纵向仍未完成。冷持久generation分配/可信fresh seed待用户裁定，不实现未决协议；其他切片继续推进。原生资源ABSENT，不算绿；M0、费用unknown；AU003/AU005及总goal仍PARTIAL。
