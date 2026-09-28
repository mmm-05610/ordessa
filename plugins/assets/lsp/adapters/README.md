# ordessa-lsp-adapters

LSP 资产域的品牌侧（016 LSP-1/3/4）。三件事，全部仿 model-provider /
sandbox adapters 形制（只仿不 import）：

1. **facet `assets.lsp` 挂真 C2 点**。`LspAdaptersServerPlugin` 通过真实的
   `harness.configuration-adapters`（v1）贡献三个品牌 descriptor
   （`assets.lsp.pi` / `assets.lsp.codex` / `assets.lsp.claude-code`）。
   `native_versions` 从仓内 `harnesses.toml` 实测（file-relative，测试与
   运行同源），`adapter_versions` 是本发行物自己的 0.1.0。
2. **诚实逐格**（LSP-3）。三家 payload schema 都是闭合空对象——本批**没有任何
   品牌拥有可写的原生 LSP 配置字段**，descriptor 零 claims：
   * pi：官方钉定提交 `2b0a123de983`（settings.md 全量参考 0 个 LSP/format
     键、docs 目录无 lsp/formatter 文档、configuration.md agent 目录无 LSP
     文件、extensions.md 无 LSP API、monorepo workspaces 无 LSP 包、
     source-index.json pi 68 键 0 命中）——plan F6 "pi :130" 为行号漂移，
     该行实为 OpenCode 的 LSP 行。pi 格 = unsupported（证据在 `evidence.py`）。
   * codex：config-reference 437 键 0 命中；harnesses.md codex 节无 LSP 行。
   * claude-code：settings-reference 234 + env-vars 371 键 0 命中。
   * hermes/opencode/kilo：按品牌优先级裁定**本批不实施**，投影入口对这四家
     （含 qwen）返回类型化拒绝；其中 dsh/opencode/kilo 有原生 LSP 面证据
     （source-index dsh 17 键 lsp-stdio、opencode/kilo schema lsp+formatter），
     转阶段二设计；**qwen 已除名**（用户裁定 2026-09-28，`.lsp.json` 行跳过）。
3. **可用性诚实检查**（LSP-4）。`probe.resolve_executable` 用注入式 PATH
   查找（默认 `shutil.which`，不 spawn）回答可执行在场性；缺席 = 该格
   `absent-executable` 并带原因，不产假配置。

`project.project_selection` 把 定义模型校验 → 探测 → 品牌评估 → 决策记录
串成一条流水线，决策记录经 `ordessa_lsp_api.canonical_json_bytes` 得到字节
稳定转录（LSP-5 golden 的对象）。

## Test

```
PYTHONPATH=plugins/assets/lsp/api/src:plugins/assets/lsp/adapters/src \
  <repo>/.venv/bin/python -m pytest plugins/assets/lsp/adapters -q
```
