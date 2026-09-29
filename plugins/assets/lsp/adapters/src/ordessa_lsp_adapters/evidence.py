"""逐格证据账（016 LSP-3/LSP-6 的事实底；全部可回指）。

纪律：这里只放能回指到**仓内固定事实**（source-index.json 的条目 id、
harnesses.md 的节/行、harnesses.toml 的 pin）或**钉定官方源**（pi 研究提交）
的证据；训练记忆与第三方转述（L6）不进本表。检索执行日期 2026-09-28
（zcode 代打会话），pi 源以研究 pin 固定，不用主分支。source-index.json
各条目自带 fetchedAt 与 SHA-256，报告按条目 id 回指，本文件不复述哈希
（避免转写失真）。

与 plan.md F6 的两处出入（如实登记，不粉饰）：
1. F6 "pi :130（LSP/formatter）" —— 现行 harnesses.md :130 是 **OpenCode**
   的 LSP 行；pi 节在 harnesses.md 的全部历史版本中都没有 LSP 行（git 取证），
   且 pi 官方钉定提交的全部证据面（见 ``BRAND_EVIDENCE["pi"]``）确认 pi 无
   原生 LSP 配置面。LSP-3 "只实施 pi" 的对象按证据如实落为：pi adapter =
   零 claims + unsupported 评估 + 证据指针。
2. F6 "dsh 无原生 → unsupported" —— source-index.json dsh 条目有 17 个
   ``@deepseek-ai/dsh-lsp-stdio`` 键（command/args/env/servers/
   extensionToLanguage/...），harnesses.md :152 亦记 lsp-stdio。dsh 格不是
   unsupported，而是"有原生面、按品牌裁定本批不实施、转阶段二设计"。
"""
from __future__ import annotations

__all__ = [
    "LSP_RECON_DATE",
    "PI_RESEARCH_PIN",
    "PHASE2_BRANDS",
    "REMOVED_BRANDS",
    "BRAND_EVIDENCE",
]

#: 逐格证据的统一检索执行日（本仓 016 夜批）。
LSP_RECON_DATE = "2026-09-28"

#: pi 官方源研究提交（harnesses.md / source-index.json 同 pin）。
PI_RESEARCH_PIN = "2b0a123de98318c2ff8069661721ce0c3794c34e"

#: 本批不实施、转阶段二设计的品牌（spec.md 品牌优先级节）。
PHASE2_BRANDS = ("hermes", "opencode", "dsh", "kilo")

#: 用户裁定除名的品牌（qwen 全线移除；`.lsp.json` 行跳过并登记）。
REMOVED_BRANDS = ("qwen",)

#: 逐格证据。status 三态口径与 tasks.md 一致；evidence_ref 只用条目 id 与
#: 文件:行 回指，不转写哈希。键数为本会话对 source-index.json 的实测计数。
BRAND_EVIDENCE: dict[str, dict[str, str]] = {
    "pi": {
        "status": "unsupported",
        "reason": (
            "pi 在研究 pin 2b0a123de983 上无原生 LSP 配置面：settings.md 全量"
            "参考 0 个 lsp/formatter 键；packages/coding-agent/docs 目录无 "
            "lsp/formatter 文档；configuration.md agent 目录只有 settings/"
            "keybindings/models/auth/instructions/extensions/skills/prompts/"
            "themes；extensions.md 无 LSP 注册 API；monorepo workspaces 无 "
            "LSP 包；source-index.json pi 条目 68 键 0 命中。若未来出现原生"
            "面或已证扩展 LSP API，单点扩本 adapter，不在他处改。"),
        "evidence_ref": (
            f"github.com/earendil-works/pi/tree/{PI_RESEARCH_PIN}"
            "/packages/coding-agent/docs + source-index.json 条目 pi"),
    },
    "codex": {
        "status": "unsupported",
        "reason": (
            "codex config-reference 437 键 0 个 lsp/formatter 命中；"
            "harnesses.md codex 节无 LSP 行。"),
        "evidence_ref": (
            "learn.chatgpt.com/docs/config-file/config-reference + "
            "source-index.json 条目 codex + harnesses.md §1"),
    },
    "claude-code": {
        "status": "unsupported",
        "reason": (
            "claude settings-reference 234 键 + env-vars 371 键 0 个 "
            "lsp/formatter 命中；harnesses.md claude 节无 LSP 行。"),
        "evidence_ref": (
            "code.claude.com/docs/en/settings-reference + env-vars + "
            "source-index.json 条目 claude / claude-env + harnesses.md §2"),
    },
    "hermes": {
        "status": "phase2-deferred",
        "reason": (
            "harnesses.md :110 将 LSP 列入扩展服务/显示行（配置主体可盘点）；"
            "source-index.json hermes 54 键 0 命中（证据不足，待核）。按品牌"
            "优先级裁定本批不实施，转阶段二设计。"),
        "evidence_ref": "harnesses.md §4 :110 + source-index.json 条目 hermes",
    },
    "opencode": {
        "status": "phase2-deferred",
        "reason": (
            "有原生 LSP 面：官方 config schema lsp/formatter/permission.lsp；"
            "harnesses.md :130。按品牌优先级裁定本批不实施，转阶段二设计。"),
        "evidence_ref": (
            "opencode.ai/config.json + source-index.json 条目 opencode + "
            "harnesses.md §5 :130"),
    },
    "dsh": {
        "status": "phase2-deferred",
        "reason": (
            "有原生 LSP 面：source-index.json dsh 17 个 @deepseek-ai/"
            "dsh-lsp-stdio 键（command/args/env/servers/extensionToLanguage/"
            "initializationOptions/killGraceMs/maxDocumentBytes/…）；"
            "harnesses.md :152。plan F6 'dsh 无原生' 与证据不符，已登记修正；"
            "按品牌优先级裁定本批不实施，转阶段二设计。"),
        "evidence_ref": (
            "source-index.json 条目 dsh + harnesses.md §6 :152"),
    },
    "kilo": {
        "status": "phase2-deferred",
        "reason": (
            "有原生 LSP 面：官方 config schema lsp/formatter/permission.lsp；"
            "harnesses.md :199。按品牌优先级裁定本批不实施，转阶段二设计。"),
        "evidence_ref": (
            "app.kilo.ai/config.json + source-index.json 条目 kilo + "
            "harnesses.md §8 :199"),
    },
    "qwen": {
        "status": "brand-removed",
        "reason": (
            "qwen 已除名（用户裁定 2026-09-28，spec.md 品牌优先级节）：一切"
            "任务中的 qwen 行跳过不做并登记。其原生 `.lsp.json` 面"
            "（harnesses.md :178）不再实施；harnesses.toml 的 qwen pin 摘除"
            "归 PE2-8，非本包写入面。"),
        "evidence_ref": "specs/016-overnight-batch/spec.md 品牌优先级节 §2",
    },
}
