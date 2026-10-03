# ordessa-lsp-api

LSP 资产域的定义模型（016 LSP-2）。三个概念：

* **`LspServerDefinition`** — 一台语言服务器：名称、可执行引用（`command`，
  字符串，本体绝不入仓）、参数、语言映射（`languages`）。引用制：域内只保存
  "去哪找"（可执行名），不保存"是什么"（二进制）。
* **`FormatterDefinition`** — 同形的格式化器定义。
* **`LspSelection`** — 启用与作用域：一次选择 = 若干定义引用 + 作用域
  （`session` 或 `profile`）。作用域是数据模型的一部分，不靠调用约定。

`canonical_json_bytes` 给出**字节稳定**的规范转录（排序键、紧凑分隔符、
UTF-8、无斜杠转义）：同一份选择/决策记录无论何时序列化都得到逐字节相同的
输出——这是 LSP-5 golden 转录测试的基础。

## Test

```
PYTHONPATH=plugins/assets/lsp/api/src \
  <repo>/.venv/bin/python -m pytest plugins/assets/lsp/api -q
```
