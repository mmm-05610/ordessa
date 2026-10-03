# 001 T001-07 — 套件发现表与不可变源码清单

日期：2026-10-03。HEAD：`ebe712c7966df0c25196cf3744a743107c002804`（清单内 head 字段同值）。

## 不可变源码清单

- 工具：`manifest-tool.py`（本目录，git-tracked）。对 `git ls-files` 全量 3347 个文件输出
  path/category/note/mode/type/link/sha256；秘密与运行数据模式命中即 FAIL；symlink 逃逸仓库根
  即 FAIL。
- `source-manifest-a.json` 与间隔重算的 `source-manifest-b.json` 逐字节一致（794279 B；
  摘要 source 1350 / test 928 / doc 841 / assembly 213 / asset-binary 9 / other 6；
  violations=[]，symlink=0）。分类细节见 T001-01-03-report.md。
- 前后重算一致 ⇒ 冻结时点无并发编辑；后续每单提交前可重跑比对检测漂移。

## 发现表（真实命令，非假想）

| 发现面 | 命令 | 结果 |
| --- | --- | --- |
| JS 聚合 | `npm test -- --list` | 41 suites（3 build + 30 workspace + 4 node-test + 1 rig + 7 electron + typecheck…全清单见下） |
| Python 收集 | `.venv/bin/python -m pytest <dir> --collect-only -q` | pacthold 218；harness 846；apps/server 1264；runtime-compat 163；server-compat 9；tests/integration/acp_orchestration 59 |
| Go 包 | `go list ./...`（GOROOT=/home/maoqh/ordessa-builds/go1.24.13） | 10 packages：cmd/acp、internal/{acp,bridge,codex,config,observability,pi}、pkg/{codexacp,piacp}、test/integration（3 个无测试文件） |
| 独立 ACP rig | `tests/integration/acp-connector`（自带 package-lock） | 10 文件 / 81 tests（`npx vitest run` 计数） |
| 安装子进程 suite | harness pytest 内 `pip install` fixture（external_adapter）；electron 各腿依赖 /opt/ordessa 打包运行时；claude 打包闭包 `plugins/harness/packaging/claude/node_modules` | 环境敏感项已在 T001-05 记录 |

### npm 聚合 41 suites 清单（--list 原样）

typecheck；build:examples；build:foundations；build:app；workspace:apps/desktop；
workspace:packages/desktop-platform/{connections,extension-host,native-bridge,server-bridge,ui,ui-components}；
workspace:packages/workbench；workspace:plugins/agent/{connections,sessions}；
workspace:plugins/assets/mcp/frontend；workspace:plugins/assets/model-provider/{chat-contribution,desktop}；
workspace:plugins/assets/sandbox/frontend；workspace:plugins/assets/skills/desktop；
workspace:plugins/assets/subagents/{settings,ui}；workspace:plugins/chat/{api,frontend}；
workspace:plugins/connectors/{acp,ordessa}；workspace:plugins/permissions/frontend；
workspace:plugins/profile/{api,frontend,integrations/chat}；workspace:products/desktop；
node-test:products/desktop；node-test:plugins/harness/packaging；node-test:plugins/harness/tests/access；
rig:tests/integration/acp-connector；electron:test:{electron,extensions,agent-ui,agent-shell,ui-service,ui-foundations,ui-preview}。

## 环境前置（发现表可复现前提）

- 根 `npm ci`（package-lock 冻结）→ 25 bins、electron/dist 就位。首次安装曾静默失败
  （管道掩盖 exit；node_modules 半装、无 .bin）——重装后恢复；**教训：npm 命令后必须显式核对
  exit code，不接 `| tail`**。
- `tests/integration/acp-connector` 需自带 `npm ci`（独立 lock，pins @agentclientprotocol/sdk 1.5.0）。
- `plugins/harness/packaging/claude` 需自带 `npm ci`（claude provider-session 套件此前 ERR_MODULE_NOT_FOUND）。
- Python：`python3.12 -m venv .venv` + `pip install -r apps/server/lockfiles/server-linux-py312.txt`
  + 18 个 in-tree editable 包 + **setuptools**（py3.12 venv 不自带；
  `test_native_verifier_deployment` 的 sdist 构建腿需要，装入后与台账一致）。
- Go：钉版 1.24.13 不在 PATH，用 `/home/maoqh/ordessa-builds/go1.24.13/bin`。
