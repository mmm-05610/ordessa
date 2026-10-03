# plugins/assets/lsp — LSP 资产域（016 夜批 LSP 包）

五家原生 LSP 配置投影域（server 定义/语言映射/formatter/可用性诚实检查）。
**本批的诚实结论：没有任何一家拥有可写的原生 LSP 配置面**——详见
`specs/016-overnight-batch/reports/LSP-report.md` 的逐格表与证据。

| 包 | 职责 |
| --- | --- |
| `api/`（ordessa-lsp-api） | 定义模型（server/formatter 定义、选择与作用域、引用制）+ 字节稳定规范转录 |
| `adapters/`（ordessa-lsp-adapters） | facet `assets.lsp` 挂真 C2 点、可执行探测、投影决策流水线、逐格证据账 |

品牌面（spec.md 品牌优先级裁定）：本批实施面 pi/codex/claude-code 三家
descriptor（全部为带证据的 unsupported 格）；hermes/opencode/dsh/kilo 转阶段二
设计；qwen 已除名。

## Test

```
PYTHONPATH=plugins/assets/lsp/api/src:plugins/assets/lsp/adapters/src:plugins/assets/lsp/adapters/tests \
  <repo>/.venv/bin/python -m pytest plugins/assets/lsp -q
```
