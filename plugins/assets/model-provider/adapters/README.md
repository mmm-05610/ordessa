# adapters — Pi / Codex / Claude Code 配置适配（facet `assets.model-provider`）

Evidence level: **E1**（本域受控测试；注册点/真桥 E2 属 C0 harness-api 接线，见
`specs/011-z3-model-provider/api-requests.md` REQ-Z3-1）。E1 不得报成 E2。

## 模块

| 文件 | 内容 |
| --- | --- |
| `types.py` | typed 判别面：Assessment / CompileIntent / BindSecret / MountContent / IntentSet / Refusal / Verdict（对齐 harness-v2 契约 C2/C3 目标稿） |
| `common.py` | 四值 canonical 协议词表、逐品牌 DIALECTS（golden，含 provenance）、字节稳定的 codex TOML 段渲染、版本门、注册冲突检查 |
| `pi.py` / `codex.py` / `claude.py` | 各品牌 assess/compile/verify + `registration_manifest()` |

## provenance

- DIALECTS / NATIVE_TARGET：转录自本树 `96fef2db47` 的
  `ordessa_harness/{pi,codex,claude}/native.py`（每值原始 citation 在 family 模块内）。
- `render_codex_provider_section`：与 `ordessa_harness.native_materialization` 同名函数字节对齐
  （golden 测试钉死）；production 侧品牌渲染按 C2 所有权转本域，harness 侧退役归 C0
  （integration-request.md）。
- 品牌语义：`docs/design/model-provider/research-and-reuse.md`（官方文档锚点）+
  `plugins/harness/packaging/claude/provider-*.mjs` 的受控证据模式。

## 边界（静态门在 tests/test_adapters_conformance.py）

适配器纯函数：不读 HOME、不触网、不 spawn、不写文件、secret 只携带 `ref://` 引用。
实际注册调用属 C0/harness-api；本包不 import 任何 harness 注册器。

## 验证

`.venv/bin/python -m pytest plugins/assets/model-provider/adapters -q` → 37 passed（先红：
实现前 1 collection error + 全量失败；两轮输出记录于线报告）。
