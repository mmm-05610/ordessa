"""The eight-brands × four-groups run-level preference catalog.

**This module is the single source of truth** for RA-3 (per-cell three-state
conclusions), RA-4 (admin-only exclusions) and RA-6 (per-key apply modes).
Every native key carries a first-hand citation; cells without a pinnable
native surface say so — never guessed, never upgraded silently.

Evidence sources (all document-level, fixed snapshots):

- ``INV``  = docs/design/harness-configuration/harnesses.md (2026-09-27
  inventory; section numbers below), backed by source-index.json entries
  (official URL + retrieval timestamp + SHA-256 per entry).
- ``OC-DOC`` = opencode.ai/docs/config/ official config page, retrieved
  2026-09-28 (point upgrade over the schema-only index).
- ``QW-DOC`` = QwenLM/qwen-code settings.md @ 302e7d88ef366991295e41dd9b158a13ab29cd74,
  retrieved 2026-09-28 (point upgrade; see the F3-conflict note below).

Cell status vocabulary: ``available`` (documented native entry, keys named),
``unsupported`` (negative verdict WITH evidence), ``unknown`` (not
established either way at this evidence level — includes boundary exclusions
where noted). Apply-mode vocabulary: ``reload`` / ``restart`` /
``next-session`` / ``unknown``; a key without an official statement of its
dynamic-application behavior is ``unknown`` (R3 discipline: no hot-reload is
ever written without evidence).

Model-provider boundary (spec §4 ruling 3): request-level parameters —
reasoning effort, service tier, per-request retry/stream timeout, provider
endpoint options — belong to the model-provider domain and are NOT compiled
here even when a native key visibly exists (codex's
``model_providers.<id>.request_max_retries`` et al.).
"""
from __future__ import annotations

from dataclasses import dataclass


STATUS_AVAILABLE = "available"
STATUS_UNSUPPORTED = "unsupported"
STATUS_UNKNOWN = "unknown"

APPLY_RELOAD = "reload"
APPLY_RESTART = "restart"
APPLY_NEXT_SESSION = "next-session"
APPLY_UNKNOWN = "unknown"

GROUPS = ("compaction", "memory", "shell", "retry")
BRANDS = ("pi", "codex", "claude-code", "hermes", "opencode", "dsh", "qwen", "kilo")

#: Canonical parameter vocabulary per group (facet item schema v1). A brand
#: adapter maps only the params it can express faithfully at this evidence
#: level; every other canonical param compiles to a typed refusal.
CANONICAL_PARAMS: dict[str, tuple[str, ...]] = {
    "compaction": ("enabled", "mode", "thresholdPercent", "thresholdTokens",
                   "reserveTokens", "keepRecentTokens", "summaryModelRef"),
    # AR-5 contract (P-B consumes this exact key set as a facet contract):
    # switch / budget / extraction-model reference. Purely typed parameters —
    # provisioning, endpoints and credentials are structurally absent.
    "memory": ("enabled", "budgetTokens", "extractionModelRef"),
    "shell": ("enabled", "shellPath", "commandPrefix", "backend", "persistent",
              "timeoutMs", "envRefs"),
    "retry": ("enabled", "maxRetries", "baseDelayMs", "maxDelayMs",
              "streamIdleTimeoutMs", "transport", "proxyRef"),
}


@dataclass(frozen=True)
class NativeKey:
    """One documented native key (or key family). ``path`` is the structured
    location inside the brand's instance configuration target; ``canonical``
    names the canonical parameter it expresses, or ``None`` when the key is
    recorded as evidence but deliberately not compiled (experimental,
    admin-entangled, or shape-unmapped at this evidence level)."""

    path: tuple[str, ...]
    canonical: str | None
    apply_mode: str
    evidence: str
    admin_only: bool = False
    note: str = ""


@dataclass(frozen=True)
class GroupCell:
    """One brand × group verdict: the three-state conclusion plus the named
    keys behind it. ``target`` is the instance configuration target the
    harness issues (handle id); ``None`` means the native write target is
    not pinnable at this evidence level (compile refuses honestly)."""

    brand: str
    group: str
    status: str
    target: str | None
    codec: str | None  # 'json' | 'toml' | 'yaml' (structured field-write codecs)
    keys: tuple[NativeKey, ...]
    conclusion: str


def _cell(brand: str, group: str, status: str, target: str | None, codec: str | None,
          keys: tuple[NativeKey, ...], conclusion: str) -> GroupCell:
    return GroupCell(brand, group, status, target, codec, keys, conclusion)


# ---------------------------------------------------------------------------
# pi — target: user settings (agent dir), evidence: pi settings.md @ 2b0a123d
# (68 identifiers, source-index.json "pi"); INV §3.
# ---------------------------------------------------------------------------

PI_COMPACTION = _cell(
    "pi", "compaction", STATUS_AVAILABLE, "pi.settings.json", "json",
    (
        NativeKey(("compaction", "enabled"), "enabled", APPLY_UNKNOWN,
                  "pi settings.md @ 2b0a123d, compaction.enabled (source-index.json:pi)"),
        NativeKey(("compaction", "reserveTokens"), "reserveTokens", APPLY_UNKNOWN,
                  "pi settings.md @ 2b0a123d, compaction.reserveTokens (source-index.json:pi)"),
        NativeKey(("compaction", "keepRecentTokens"), "keepRecentTokens", APPLY_UNKNOWN,
                  "pi settings.md @ 2b0a123d, compaction.keepRecentTokens (source-index.json:pi)"),
        NativeKey(("compaction", "modelOverrides"), None, APPLY_UNKNOWN,
                  "pi settings.md @ 2b0a123d, compaction.modelOverrides (source-index.json:pi)",
                  note="summaryModelRef not mapped: modelOverrides value shape unpinned at document level"),
    ),
    "可用：settings.json 压缩族四键（enabled/reserveTokens/keepRecentTokens/modelOverrides）。"
    "branchSummary 属会话分支摘要而非压缩策略，未收录。生效方式官方未声明→逐键 unknown。",
)

PI_MEMORY = _cell(
    "pi", "memory", STATUS_UNSUPPORTED, "pi.settings.json", "json",
    (
        NativeKey(("sessionDir",), None, APPLY_UNKNOWN,
                  "pi settings.md @ 2b0a123d, sessionDir (source-index.json:pi)",
                  note="session storage location is run state, not long-term memory"),
    ),
    "不支持：settings 索引（68 键）无记忆族；INV §2/§3——Pi 无原生长期记忆，"
    "sessionDir 是会话存储位置（运行状态），不是记忆后端。",
)

PI_SHELL = _cell(
    "pi", "shell", STATUS_AVAILABLE, "pi.settings.json", "json",
    (
        NativeKey(("shellPath",), "shellPath", APPLY_UNKNOWN,
                  "pi settings.md @ 2b0a123d, shellPath (source-index.json:pi)"),
        NativeKey(("shellCommandPrefix",), "commandPrefix", APPLY_UNKNOWN,
                  "pi settings.md @ 2b0a123d, shellCommandPrefix (source-index.json:pi)"),
    ),
    "可用（受限）：shellPath/shellCommandPrefix 两键。扩展运行于进程权限下（INV §3），"
    "不提供隔离语义；envRefs 无文档键→不映射。",
)

PI_RETRY = _cell(
    "pi", "retry", STATUS_AVAILABLE, "pi.settings.json", "json",
    (
        NativeKey(("retry", "enabled"), "enabled", APPLY_UNKNOWN,
                  "pi settings.md @ 2b0a123d, retry.enabled (source-index.json:pi)"),
        NativeKey(("retry", "maxRetries"), "maxRetries", APPLY_UNKNOWN,
                  "pi settings.md @ 2b0a123d, retry.maxRetries (source-index.json:pi)"),
        NativeKey(("retry", "baseDelayMs"), "baseDelayMs", APPLY_UNKNOWN,
                  "pi settings.md @ 2b0a123d, retry.baseDelayMs (source-index.json:pi)"),
        NativeKey(("retry", "provider"), None, APPLY_UNKNOWN,
                  "pi settings.md @ 2b0a123d, retry.provider.* (source-index.json:pi)",
                  note="provider-scoped timeout/retry family: recorded, not compiled (value shapes unpinned)"),
        NativeKey(("httpProxy",), None, APPLY_UNKNOWN,
                  "pi settings.md @ 2b0a123d, httpProxy (source-index.json:pi)",
                  note="proxyRef not mapped: URL-vs-reference shape unpinned"),
        NativeKey(("transport",), None, APPLY_UNKNOWN,
                  "pi settings.md @ 2b0a123d, transport (source-index.json:pi)",
                  note="allowed values unpinned at document level"),
        NativeKey(("httpIdleTimeoutMs",), None, APPLY_UNKNOWN,
                  "pi settings.md @ 2b0a123d, httpIdleTimeoutMs (source-index.json:pi)"),
        NativeKey(("websocketConnectTimeoutMs",), None, APPLY_UNKNOWN,
                  "pi settings.md @ 2b0a123d, websocketConnectTimeoutMs (source-index.json:pi)"),
    ),
    "可用：顶层 retry.*（enabled/maxRetries/baseDelayMs）+ HTTP/WS 传输与 httpProxy。"
    "INV §3 可靠性行。编译面首期只收 enabled/maxRetries/baseDelayMs；传输/proxy 键值形状未定→记录不编译。",
)

# ---------------------------------------------------------------------------
# codex — target: CODEX_HOME/config.toml, evidence: config-reference (437 ids,
# source-index.json "codex"); INV §1. Profile-format break documented at
# 0.134.0 (INV §1) — format facts, not our keys' version gates.
# ---------------------------------------------------------------------------

CODEX_COMPACTION = _cell(
    "codex", "compaction", STATUS_AVAILABLE, "codex.config.toml", "toml",
    (
        NativeKey(("model_auto_compact_token_limit",), "thresholdTokens", APPLY_UNKNOWN,
                  "codex config-reference, model_auto_compact_token_limit (source-index.json:codex)"),
        NativeKey(("model_auto_compact_token_limit_scope",), None, APPLY_UNKNOWN,
                  "codex config-reference, model_auto_compact_token_limit_scope (source-index.json:codex)",
                  note="scope value vocabulary unpinned; written only with a documented value"),
        NativeKey(("compact_prompt",), None, APPLY_UNKNOWN,
                  "codex config-reference, compact_prompt (source-index.json:codex)",
                  note="prompt content, not a parameter — never preset"),
        NativeKey(("features", "context_management", "experimental_mode"), None, APPLY_UNKNOWN,
                  "codex config-reference, features.context_management.experimental_mode (source-index.json:codex)",
                  note="experimental key: recorded, not compiled"),
    ),
    "可用：model_auto_compact_token_limit(+_scope)。首期编译 thresholdTokens→token limit；"
    "enabled/mode/percent 类 canonical 参数无对应键→拒绝。experimental 键记录不编译。",
)

CODEX_MEMORY = _cell(
    "codex", "memory", STATUS_AVAILABLE, "codex.config.toml", "toml",
    (
        NativeKey(("features", "memories"), None, APPLY_UNKNOWN,
                  "codex config-reference, features.memories (source-index.json:codex)",
                  note="feature gate: recorded; canonical 'enabled' maps to memories.generate_memories (extraction switch)"),
        NativeKey(("memories", "generate_memories"), "enabled", APPLY_UNKNOWN,
                  "codex config-reference, memories.generate_memories (source-index.json:codex)"),
        NativeKey(("memories", "use_memories"), None, APPLY_UNKNOWN,
                  "codex config-reference, memories.use_memories (source-index.json:codex)",
                  note="use-side switch is a separate key; one canonical switch cannot faithfully drive both"),
        NativeKey(("memories", "extract_model"), "extractionModelRef", APPLY_UNKNOWN,
                  "codex config-reference, memories.extract_model (source-index.json:codex)"),
        NativeKey(("memories", "consolidation_model"), None, APPLY_UNKNOWN,
                  "codex config-reference, memories.consolidation_model (source-index.json:codex)",
                  note="no canonical consolidation param in v1"),
        NativeKey(("memories", "max_raw_memories_for_consolidation"), None, APPLY_UNKNOWN,
                  "codex config-reference (source-index.json:codex)",
                  note="item-count budget, not a token budget — budgetTokens does not map"),
        NativeKey(("memories", "max_unused_days"), None, APPLY_UNKNOWN,
                  "codex config-reference (source-index.json:codex)", note="retention budget, not token budget"),
        NativeKey(("memories", "disable_on_external_context"), None, APPLY_UNKNOWN,
                  "codex config-reference (source-index.json:codex)"),
    ),
    "可用：memories.* 生成/使用/抽取模型/整合/预算族齐全（INV §1 记忆/上下文行）。"
    "编译面：enabled→memories.generate_memories、extractionModelRef→memories.extract_model；"
    "budgetTokens 不映射（原生预算为条目/天数而非 token，形状不忠实）。",
)

CODEX_SHELL = _cell(
    "codex", "shell", STATUS_AVAILABLE, "codex.config.toml", "toml",
    (
        NativeKey(("features", "shell_tool"), "enabled", APPLY_UNKNOWN,
                  "codex config-reference, features.shell_tool (source-index.json:codex)"),
        NativeKey(("features", "shell_snapshot"), None, APPLY_UNKNOWN,
                  "codex config-reference, features.shell_snapshot (source-index.json:codex)",
                  note="no canonical param in v1"),
        NativeKey(("allow_login_shell",), None, APPLY_UNKNOWN,
                  "codex config-reference, allow_login_shell (source-index.json:codex)",
                  note="no canonical param in v1"),
        NativeKey(("background_terminal_max_timeout",), "timeoutMs", APPLY_UNKNOWN,
                  "codex config-reference, background_terminal_max_timeout (source-index.json:codex)"),
        NativeKey(("shell_environment_policy",), None, APPLY_UNKNOWN,
                  "INV §1 权限/隔离行 + harnesses.md shell env 行（管理员 allowed/required 项不是普通预设）",
                  admin_only=True,
                  note="F8：Codex shell env 在权限行——shell_environment_policy.* 全族 admin-only，"
                       "不出现在 claims，编辑面禁用"),
        NativeKey(("sandbox_mode",), None, APPLY_UNKNOWN,
                  "INV §1 权限/隔离行", admin_only=True,
                  note="隔离族=权限域，本域不收"),
    ),
    "可用（含 admin 排除）：features.shell_tool/background_terminal_max_timeout 可预设；"
    "shell_environment_policy.*（F8 权限行纠缠）与 sandbox_*（隔离=权限域）标 admin-only 不可预设。",
)

CODEX_RETRY = _cell(
    "codex", "retry", STATUS_UNSUPPORTED, "codex.config.toml", "toml",
    (
        NativeKey(("model_providers", "<id>", "request_max_retries"), None, APPLY_UNKNOWN,
                  "codex config-reference, model_providers.<id>.request_max_retries (source-index.json:codex)",
                  note="provider subtree = model-provider domain (spec §4 ruling 3)"),
        NativeKey(("model_providers", "<id>", "stream_max_retries"), None, APPLY_UNKNOWN,
                  "codex config-reference (source-index.json:codex)",
                  note="provider subtree = model-provider domain"),
        NativeKey(("model_providers", "<id>", "stream_idle_timeout_ms"), None, APPLY_UNKNOWN,
                  "codex config-reference (source-index.json:codex)",
                  note="provider subtree = model-provider domain"),
    ),
    "不支持（本域边界）：唯一重试/流超时键全部位于 model_providers.<id>.* 供应商子树"
    "（请求级/provider 级），按 spec §4 裁定 3 归 model-provider；codex 无顶层重试策略键。",
)

# ---------------------------------------------------------------------------
# claude-code — target: settings.json, evidence: settings-reference (234) +
# env-vars (371), source-index.json "claude"/"claude-env"; INV §2.
# ---------------------------------------------------------------------------

CLAUDE_COMPACTION = _cell(
    "claude-code", "compaction", STATUS_AVAILABLE, "claude.settings.json", "json",
    (
        NativeKey(("autoCompactEnabled",), "enabled", APPLY_UNKNOWN,
                  "claude settings-reference, autoCompactEnabled (source-index.json:claude)"),
        NativeKey(("autoCompactWindow",), None, APPLY_UNKNOWN,
                  "claude settings-reference, autoCompactWindow (source-index.json:claude)",
                  note="value semantics (window vs threshold) unpinned — recorded, not compiled"),
        NativeKey((), None, APPLY_UNKNOWN,
                  "claude env-vars, DISABLE_AUTO_COMPACT / DISABLE_COMPACT / CLAUDE_AUTOCOMPACT_PCT_OVERRIDE "
                  "(source-index.json:claude-env)",
                  admin_only=True,
                  note="env-object entries: F8（Claude 环境/运维含管理员项）——env 对象不预设"),
    ),
    "可用：autoCompactEnabled/autoCompactWindow。编译面只收 enabled→autoCompactEnabled；"
    "env 侧压缩开关（DISABLE_AUTO_COMPACT 等）在 env 对象内，按 F8 记 admin-only。",
)

CLAUDE_MEMORY = _cell(
    "claude-code", "memory", STATUS_AVAILABLE, "claude.settings.json", "json",
    (
        NativeKey(("autoMemoryEnabled",), "enabled", APPLY_UNKNOWN,
                  "claude settings-reference, autoMemoryEnabled (source-index.json:claude)"),
        NativeKey(("autoMemoryDirectory",), None, APPLY_UNKNOWN,
                  "claude settings-reference, autoMemoryDirectory (source-index.json:claude)",
                  note="a filesystem path, not a typed v1 param — never preset"),
        NativeKey((), None, APPLY_UNKNOWN,
                  "claude env-vars, CLAUDE_CODE_DISABLE_AUTO_MEMORY (source-index.json:claude-env)",
                  admin_only=True, note="env-object entry: F8"),
    ),
    "可用：autoMemoryEnabled（开关）。autoMemoryDirectory 是路径键不预设；"
    "生成的记忆正文不可随预设覆盖（INV §2）。",
)

CLAUDE_SHELL = _cell(
    "claude-code", "shell", STATUS_AVAILABLE, "claude.settings.json", "json",
    (
        NativeKey(("defaultShell",), "shellPath", APPLY_UNKNOWN,
                  "claude settings-reference, defaultShell (source-index.json:claude)"),
        NativeKey(("disableSkillShellExecution",), None, APPLY_UNKNOWN,
                  "claude settings-reference (source-index.json:claude)",
                  note="skill-tool permission shape — permission domain, not compiled"),
        NativeKey(("env",), None, APPLY_UNKNOWN,
                  "INV §2 环境/运维行：env/shell/worktree/遥测 helper 等含全局/机器/组织项；"
                  "F8 管理员项不可作普通预设",
                  admin_only=True,
                  note="整个 env 对象 admin 纠缠（且 model-provider 域在该文件持有 env claim）——"
                       "CLAUDE_CODE_SHELL 等环境条目不预设"),
    ),
    "可用（含 admin 排除）：defaultShell 可预设；env 对象（CLAUDE_CODE_SHELL、BASH_*_TIMEOUT_MS 等）"
    "按 F8 admin-only 不预设，编辑面禁用并说明。",
)

CLAUDE_RETRY = _cell(
    "claude-code", "retry", STATUS_UNKNOWN, "claude.settings.json", "json",
    (
        NativeKey((), None, APPLY_UNKNOWN,
                  "claude env-vars, CLAUDE_CODE_RETRY_WATCHDOG (source-index.json:claude-env)",
                  note="single env entry, semantics not pinned in this round"),
        NativeKey((), None, APPLY_UNKNOWN,
                  "claude env-vars, API_TIMEOUT_MS / CLAUDE_CODE_CONNECT_TIMEOUT_MS (source-index.json:claude-env)",
                  admin_only=True,
                  note="request-level API timeout = model-provider domain (spec §4 ruling 3)"),
    ),
    "未知：settings 索引（234 键）无 retry/传输族；env 侧仅有 CLAUDE_CODE_RETRY_WATCHDOG"
    "（语义未核）；API 超时/重试类 env 为请求级→归 model-provider。逐键升级需固定源码。",
)

# ---------------------------------------------------------------------------
# hermes — target: HERMES_HOME/config.yaml, evidence: configuration.md @
# 6f7a7991 (54 identifiers, source-index.json "hermes") + INV §4 semantic
# table (YAML fields were not auto-extracted — per-key upgrade required).
# ---------------------------------------------------------------------------

HERMES_COMPACTION = _cell(
    "hermes", "compaction", STATUS_AVAILABLE, "hermes.config.yaml", "yaml",
    (
        NativeKey(("auxiliary", "compression", "provider"), None, APPLY_UNKNOWN,
                  "hermes configuration.md @ 6f7a7991, auxiliary.compression.provider (source-index.json:hermes)",
                  note="documented anchor; ref-shape mapping to summaryModelRef unpinned — not compiled"),
        NativeKey((), None, APPLY_UNKNOWN,
                  "INV §4 压缩行：compression 策略、auxiliary.compression 模型、context engine",
                  note="strategy key paths live in YAML examples not auto-extracted this round"),
    ),
    "可用（文档级）：compression 策略 + auxiliary.compression 模型 + context engine（INV §4 语义表，"
    "锚点 auxiliary.compression.provider）。YAML 键路径未自动提取→编译面本域暂无忠实映射，逐键升级。",
)

HERMES_MEMORY = _cell(
    "hermes", "memory", STATUS_AVAILABLE, "hermes.config.yaml", "yaml",
    (
        NativeKey((), None, APPLY_UNKNOWN,
                  "INV §4 记忆行：persistent memory 与 memory provider、启用/预算",
                  note="memory backend has a dedicated loader (INV §4 plugins note)"),
    ),
    "可用（文档级）：persistent memory + memory provider 启用/预算（INV §4 语义表）。"
    "键路径未自动提取→编译面暂无忠实映射，逐键升级。",
)

HERMES_SHELL = _cell(
    "hermes", "shell", STATUS_AVAILABLE, "hermes.config.yaml", "yaml",
    (
        NativeKey((), None, APPLY_UNKNOWN,
                  "hermes configuration.md @ 6f7a7991, TERMINAL_* family: TERMINAL_SSH_PORT/KEY/PERSISTENT, "
                  "TERMINAL_DOCKER_*（IMAGE/NETWORK/VOLUMES/PERSIST_ACROSS_PROCESSES 等）, TERMINAL_TIMEOUT, "
                  "TERMINAL_CONTAINER_* (source-index.json:hermes)",
                  note="backend/persistent canonical params map conceptually; config.yaml key paths for "
                       "terminal backend not auto-extracted — not compiled; deployment credentials stay out"),
    ),
    "可用（文档级）：terminal backend（local/SSH/容器）+ 持久 shell（INV §4 执行环境行；TERMINAL_* 锚点）。"
    "部署凭据不混入（README §1 边界）；config.yaml 键路径未定→编译面暂无忠实映射。",
)

HERMES_RETRY = _cell(
    "hermes", "retry", STATUS_UNKNOWN, "hermes.config.yaml", "yaml",
    (
        NativeKey((), None, APPLY_UNKNOWN,
                  "source-index.json:hermes — no retry/transport family in 54 identifiers; "
                  "INV §4 无重试族（fallback 属模型选择）"),
    ),
    "未知：固定提交索引（54 键）与语义表均无 retry/传输族；fallback 是模型选择而非重试策略。"
    "Hermes 覆盖深度有限（sources-and-gaps R9），不轻易下负向断言。",
)

# ---------------------------------------------------------------------------
# opencode — target: opencode.json (user tier), evidence: config schema
# (84 ids, source-index.json "opencode") + official config docs page
# (retrieved 2026-09-28). INV §5.
# ---------------------------------------------------------------------------

OPENCODE_COMPACTION = _cell(
    "opencode", "compaction", STATUS_AVAILABLE, "opencode.opencode.json", "json",
    (
        NativeKey(("compaction", "auto"), "enabled", APPLY_UNKNOWN,
                  "opencode config docs (2026-09-28): compaction.auto — automatically compact when "
                  "context fills; schema keys source-index.json:opencode"),
        NativeKey(("compaction", "reserved"), "reserveTokens", APPLY_UNKNOWN,
                  "opencode config docs (2026-09-28): compaction.reserved — token buffer kept before compacting"),
        NativeKey(("compaction", "preserve_recent_tokens"), "keepRecentTokens", APPLY_UNKNOWN,
                  "opencode config schema, compaction.preserve_recent_tokens (source-index.json:opencode)"),
        NativeKey(("compaction", "prune"), None, APPLY_UNKNOWN,
                  "opencode config docs (2026-09-28): compaction.prune — remove old tool outputs",
                  note="boolean prune switch; canonical 'mode' is a string — not faithful, not compiled"),
        NativeKey(("compaction", "tail_turns"), None, APPLY_UNKNOWN,
                  "opencode config schema, compaction.tail_turns (source-index.json:opencode)",
                  note="no canonical param in v1"),
        NativeKey(("agent", "compaction"), None, APPLY_UNKNOWN,
                  "opencode config schema, agent.compaction (source-index.json:opencode)",
                  note="per-agent override surface — separate lane, not compiled"),
    ),
    "可用：compaction.auto/reserved/preserve_recent_tokens/prune/tail_turns（官方 config 文档 "
    "2026-09-28 + schema 索引）。编译面：enabled→compaction.auto、reserveTokens→compaction.reserved、"
    "keepRecentTokens→compaction.preserve_recent_tokens。",
)

OPENCODE_MEMORY = _cell(
    "opencode", "memory", STATUS_UNKNOWN, "opencode.opencode.json", "json",
    (
        NativeKey((), None, APPLY_UNKNOWN,
                  "opencode config schema (84 ids, source-index.json:opencode) 与官方 config 文档"
                  "（2026-09-28）均无 memory 配置族；spec F3/README §2 列 OpenCode 有原生 memory loader"),
    ),
    "未知：spec F3 断言 OpenCode 具原生长期记忆（memory loader），但固定 schema 索引（84 键）与当前"
    "官方 config 文档均无对应配置键——loader 若为内置无键功能则本域无键可写；需固定源码核定入口。"
    "不下支持/不支持断言。",
)

OPENCODE_SHELL = _cell(
    "opencode", "shell", STATUS_AVAILABLE, "opencode.opencode.json", "json",
    (
        NativeKey(("shell",), "shellPath", APPLY_UNKNOWN,
                  "opencode config docs (2026-09-28): shell — the shell used for the interactive "
                  "terminal and agent tool calls"),
    ),
    "可用（受限）：单键 shell（交互终端与 agent 工具调用所用 shell）。envRefs/backend 无文档键→不映射。",
)

OPENCODE_RETRY = _cell(
    "opencode", "retry", STATUS_UNKNOWN, "opencode.opencode.json", "json",
    (
        NativeKey((), None, APPLY_UNKNOWN,
                  "source-index.json:opencode — no retry family in 84 schema ids; official config docs "
                  "(2026-09-28) list provider options timeout/headerTimeout/chunkTimeout",
                  admin_only=True,
                  note="provider timeout options are request-level = model-provider domain"),
    ),
    "未知：schema 索引与官方 config 文档均无重试族；provider options 的 timeout/chunkTimeout 属"
    "请求级→归 model-provider。另注：/etc/opencode 管理层设置可覆盖一切（managed tier），普通预设不碰。",
)

# ---------------------------------------------------------------------------
# dsh — native config is a Cordis per-package plugin tree (bundle patches →
# profile patch → home patch → CLI patches; INV §6). No single documented
# write target is pinnable at document level ⇒ target None, compile refuses.
# Evidence: config-catalog.md @ 477b4f42 (728 ids, source-index.json "dsh").
# ---------------------------------------------------------------------------

DSH_COMPACTION = _cell(
    "dsh", "compaction", STATUS_AVAILABLE, None, None,
    (
        NativeKey((), None, APPLY_UNKNOWN,
                  "dsh config-catalog.md @ 477b4f42: compaction-basic / tool-result-pruner / spill 包 "
                  "(source-index.json:dsh); INV §6 上下文行",
                  note="Cordis per-package assembly: no single documented file target — not compiled"),
    ),
    "可用（文档级）：compaction-basic、tool-result-pruner、spill、session-reference（INV §6）。"
    "配置为 Cordis 插件树装配、目标行整体替换，文档级无法钉出单一写入目标→编译面诚实拒绝，逐键升级需固定源码。",
)

DSH_MEMORY = _cell(
    "dsh", "memory", STATUS_UNSUPPORTED, None, None,
    (
        NativeKey((), None, APPLY_UNKNOWN,
                  "dsh config-catalog.md @ 477b4f42 (728 ids, source-index.json:dsh) — 无记忆族包；INV §6"),
    ),
    "不支持：固定提交 config 目录（728 标识符）与 INV §6 语义表均无记忆族。",
)

DSH_SHELL = _cell(
    "dsh", "shell", STATUS_AVAILABLE, None, None,
    (
        NativeKey((), None, APPLY_UNKNOWN,
                  "dsh config-catalog.md @ 477b4f42: shell-env、persistent bash、SSH、terminal 包 "
                  "(source-index.json:dsh); INV §6 执行环境行",
                  note="Cordis per-package assembly: no single documented file target — not compiled"),
    ),
    "可用（文档级）：shell-env、persistent bash、SSH、terminal、PTC Node/Python（INV §6）。"
    "同 dsh/compaction：文档级无单一写入目标→编译面诚实拒绝。",
)

DSH_RETRY = _cell(
    "dsh", "retry", STATUS_AVAILABLE, None, None,
    (
        NativeKey((), None, APPLY_UNKNOWN,
                  "dsh config-catalog.md @ 477b4f42: llm-pi-ai provider retry 包 (source-index.json:dsh); "
                  "INV §6 模型行",
                  note="provider-scoped retry in the llm package: recorded; request-level boundary to be "
                       "checked at upgrade; no single documented file target — not compiled"),
    ),
    "可用（文档级）：llm retry（INV §6 模型行 llm-pi-ai retry）。逐键升级时须先核 provider 级 vs "
    "请求级边界；文档级无单一写入目标→编译面诚实拒绝。",
)

# ---------------------------------------------------------------------------
# qwen — target: user settings.json, evidence: settings.md @ 302e7d88
# (252 ids, source-index.json "qwen") + settings doc content retrieved
# 2026-09-28. INV §7.
#
# F3-CONFLICT NOTE (registered, not re-adjudicated): spec F3 rules Qwen's
# "memory" is a static-instruction trap; the fixed-commit settings doc
# additionally documents memory.enableManagedAutoMemory (background memory
# extraction, default on) and related memory.* keys. The cell verdict below
# follows the official evidence and carries the conflict for re-adjudication
# (it bears on P-B's default-mount decision for qwen).
# ---------------------------------------------------------------------------

QWEN_COMPACTION = _cell(
    "qwen", "compaction", STATUS_AVAILABLE, "qwen.settings.json", "json",
    (
        NativeKey(("context", "autoCompactThreshold"), "thresholdPercent", APPLY_UNKNOWN,
                  "qwen settings.md @ 302e7d88: context.autoCompactThreshold (fraction of context window; "
                  "default 0.85) — percent stored /100",
                  note="value conversion documented in the settings doc"),
        NativeKey(("compactionModel",), None, APPLY_UNKNOWN,
                  "qwen settings.md @ 302e7d88: compactionModel",
                  note="takes a model NAME; summaryModelRef is a provider/model reference — mapping requires "
                       "model-provider resolution, deferred (not compiled at document level)"),
        NativeKey(("model", "chatCompression", "maxRecentFilesToRetain"), None, APPLY_UNKNOWN,
                  "qwen settings.md @ 302e7d88 (source-index.json:qwen)", note="no canonical param in v1"),
        NativeKey(("ui", "compactMode"), None, APPLY_UNKNOWN,
                  "qwen settings.md @ 302e7d88 (source-index.json:qwen)",
                  note="TUI display mode — interface, not a compression parameter"),
    ),
    "可用：context.autoCompactThreshold（阈值，0-1 小数）、compactionModel、model.chatCompression.*"
    "（官方 settings 文档 @ 固定提交）。编译面：thresholdPercent→context.autoCompactThreshold（/100）；"
    "compactionModel 需模型引用解析→暂不编译。",
)

QWEN_MEMORY = _cell(
    "qwen", "memory", STATUS_AVAILABLE, "qwen.settings.json", "json",
    (
        NativeKey(("memory", "enableManagedAutoMemory"), "enabled", APPLY_UNKNOWN,
                  "qwen settings.md @ 302e7d88: memory.enableManagedAutoMemory — background extraction of "
                  "memories from conversations (default true)",
                  note="F3 CONFLICT: spec rules qwen memory = static-instruction trap; the fixed-commit doc "
                       "documents a managed auto-memory feature. Registered for re-adjudication; bears on "
                       "P-B default mounting for qwen."),
        NativeKey(("memory", "enableManagedAutoDream"), None, APPLY_UNKNOWN,
                  "qwen settings.md @ 302e7d88: memory.enableManagedAutoDream — automatic consolidation",
                  note="no canonical consolidation param in v1"),
        NativeKey(("memory", "enableTeamMemory"), None, APPLY_UNKNOWN,
                  "qwen settings.md @ 302e7d88 (source-index.json:qwen)",
                  note="team/shared memory surface — out of v1 vocabulary"),
        NativeKey((), None, APPLY_UNKNOWN,
                  "qwen settings doc @ 302e7d88: context files (QWEN.md) are 'also referred to as memory' — "
                  "the static-instruction trap proper (spec F3 basis)"),
    ),
    "可用（文档级，与 spec F3 裁定冲突→已登记待复裁）：memory.enableManagedAutoMemory（后台记忆抽取，"
    "默认开）。QWEN.md 的“memory”称谓=静态指令陷阱（F3 依据）与该键族并存，两者不是同一机制。"
    "编译面：enabled→memory.enableManagedAutoMemory。",
)

QWEN_SHELL = _cell(
    "qwen", "shell", STATUS_AVAILABLE, "qwen.settings.json", "json",
    (
        NativeKey(("tools", "shell", "defaultTimeoutMs"), "timeoutMs", APPLY_UNKNOWN,
                  "qwen settings.md @ 302e7d88: tools.shell.defaultTimeoutMs"),
        NativeKey(("tools", "shell", "enableInteractiveShell"), None, APPLY_UNKNOWN,
                  "qwen settings.md @ 302e7d88 (source-index.json:qwen)", note="no canonical param in v1"),
        NativeKey(("tools", "executionSandbox"), None, APPLY_RESTART,
                  "qwen settings.md @ 302e7d88: tools.executionSandbox — changing it requires restart; "
                  "operator-level (INV §7: 不能被项目设置覆盖)",
                  admin_only=True, note="operator-level isolation: admin-only, disabled in the editor"),
        NativeKey((), None, APPLY_UNKNOWN,
                  "qwen settings doc @ 302e7d88: loader 受影响的 env 拒收清单与沙箱决策变量（QWEN_SANDBOX*）",
                  admin_only=True, note="environment/sandbox decision variables: admin-only"),
    ),
    "可用（含 admin 排除）：tools.shell.* 可预设（首期编译 timeoutMs→tools.shell.defaultTimeoutMs）；"
    "tools.executionSandbox 为操作员级（官方明文需重启）→admin-only 不预设；QWEN_SANDBOX* 环境变量不预设。",
)

QWEN_RETRY = _cell(
    "qwen", "retry", STATUS_UNKNOWN, "qwen.settings.json", "json",
    (
        NativeKey((), None, APPLY_UNKNOWN,
                  "qwen settings.md @ 302e7d88 (source-index.json:qwen): QWEN_CODE_UNATTENDED_RETRY env — "
                  "unattended persistent-retry mode",
                  note="an env-var entry the canonical retry vocabulary cannot faithfully express"),
        NativeKey((), None, APPLY_UNKNOWN,
                  "qwen settings.md @ 302e7d88: model.generationConfig timeout/maxRetries",
                  admin_only=True,
                  note="request-level generation config = model-provider domain (spec §4 ruling 3)"),
    ),
    "未知：无 settings 层重试策略键；QWEN_CODE_UNATTENDED_RETRY 是 env 开关（canonical 词表不覆盖 env 注入）；"
    "generationConfig 内 timeout/maxRetries 为请求级→归 model-provider。",
)

# ---------------------------------------------------------------------------
# kilo — target: ~/.config/kilo/kilo.jsonc (JSONC treated as JSON: comments in
# a managed file are not preserved by structured writes — registered
# limitation), evidence: config schema (106 ids, source-index.json "kilo",
# same compaction/shell shape as opencode) + INV §8 (restart documented).
# ---------------------------------------------------------------------------

KILO_COMPACTION = _cell(
    "kilo", "compaction", STATUS_AVAILABLE, "kilo.kilo.jsonc", "json",
    (
        NativeKey(("compaction", "auto"), "enabled", APPLY_RESTART,
                  "kilo config schema, compaction.auto (source-index.json:kilo); INV §8: 官方 CLI 文档要求"
                  "修改配置文件后重启"),
        NativeKey(("compaction", "reserved"), "reserveTokens", APPLY_RESTART,
                  "kilo config schema, compaction.reserved (source-index.json:kilo); INV §8"),
        NativeKey(("compaction", "preserve_recent_tokens"), "keepRecentTokens", APPLY_RESTART,
                  "kilo config schema, compaction.preserve_recent_tokens (source-index.json:kilo); INV §8"),
        NativeKey(("compaction", "prune"), None, APPLY_RESTART,
                  "kilo config schema, compaction.prune (source-index.json:kilo)",
                  note="boolean prune switch — not faithful to canonical 'mode', not compiled"),
        NativeKey(("compaction", "tail_turns"), None, APPLY_RESTART,
                  "kilo config schema, compaction.tail_turns (source-index.json:kilo)",
                  note="no canonical param in v1"),
        NativeKey(("agent", "compaction"), None, APPLY_RESTART,
                  "kilo config schema, agent.compaction (source-index.json:kilo)",
                  note="per-agent override surface — not compiled"),
    ),
    "可用：compaction.*（schema 与 opencode 同形，source-index.json:kilo）。applyMode=restart"
    "（INV §8：官方 CLI 文档要求修改配置文件后重启——八家中少数有明文生效方式的键）。"
    "注：kilo.jsonc 为 JSONC，结构化写不保留注释（已登记限制）。",
)

KILO_MEMORY = _cell(
    "kilo", "memory", STATUS_UNSUPPORTED, "kilo.kilo.jsonc", "json",
    (
        NativeKey((), None, APPLY_RESTART,
                  "kilo config schema (106 ids, source-index.json:kilo) — 无 memory 族；INV §8（snapshot 为历史，非记忆）"),
    ),
    "不支持：固定 schema 索引（106 键）无记忆族；snapshot/历史不进入预设（INV §8）。",
)

KILO_SHELL = _cell(
    "kilo", "shell", STATUS_AVAILABLE, "kilo.kilo.jsonc", "json",
    (
        NativeKey(("shell",), "shellPath", APPLY_RESTART,
                  "kilo config schema, shell (source-index.json:kilo); INV §8 restart"),
    ),
    "可用（受限）：单键 shell（同 opencode 形）。applyMode=restart（INV §8）。",
)

KILO_RETRY = _cell(
    "kilo", "retry", STATUS_UNKNOWN, "kilo.kilo.jsonc", "json",
    (
        NativeKey((), None, APPLY_RESTART,
                  "kilo config schema (106 ids, source-index.json:kilo) — 无 retry 族"),
    ),
    "未知：schema 索引无重试族；INV §8 未列。逐键升级需固定源码。",
)


#: All 32 cells, keyed (brand, group). Invariants pinned by tests: every
#: brand×group present exactly once; compiled keys (canonical is not None)
#: exist only in ``available`` cells; admin-only keys never compile.
CELLS: dict[tuple[str, str], GroupCell] = {
    (cell.brand, cell.group): cell
    for cell in (
        PI_COMPACTION, PI_MEMORY, PI_SHELL, PI_RETRY,
        CODEX_COMPACTION, CODEX_MEMORY, CODEX_SHELL, CODEX_RETRY,
        CLAUDE_COMPACTION, CLAUDE_MEMORY, CLAUDE_SHELL, CLAUDE_RETRY,
        HERMES_COMPACTION, HERMES_MEMORY, HERMES_SHELL, HERMES_RETRY,
        OPENCODE_COMPACTION, OPENCODE_MEMORY, OPENCODE_SHELL, OPENCODE_RETRY,
        DSH_COMPACTION, DSH_MEMORY, DSH_SHELL, DSH_RETRY,
        QWEN_COMPACTION, QWEN_MEMORY, QWEN_SHELL, QWEN_RETRY,
        KILO_COMPACTION, KILO_MEMORY, KILO_SHELL, KILO_RETRY,
    )
}

#: Per-brand instance configuration target and codec (target None = not
#: pinnable at document level). The C2 file claims never cover project scope.
BRAND_TARGETS: dict[str, tuple[str | None, str | None]] = {
    cell.brand: (cell.target, cell.codec)
    for cell in CELLS.values()
}

#: Native target filenames for documentation (handle ids carry the same
#: vocabulary the host issues). dsh has no single-file target.
NATIVE_TARGET_NAMES = {
    "pi": "settings.json (agent dir)",
    "codex": "config.toml (CODEX_HOME)",
    "claude-code": "settings.json",
    "hermes": "config.yaml (HERMES_HOME)",
    "opencode": "opencode.json (user tier)",
    "dsh": "Cordis per-package assembly (no single file)",
    "qwen": "settings.json (user tier)",
    "kilo": "kilo.jsonc (~/.config/kilo)",
}


def cell(brand: str, group: str) -> GroupCell:
    """The verdict for one brand × group; KeyError on an unknown pair (the
    vocabulary itself is closed)."""
    return CELLS[(brand, group)]


def compiled_keys(brand: str, group: str) -> dict[str, tuple[str, ...]]:
    """canonical param → native path, for keys this evidence level compiles."""
    return {key.canonical: key.path for key in CELLS[(brand, group)].keys
            if key.canonical is not None and not key.admin_only}


def admin_only_keys(brand: str, group: str) -> tuple[NativeKey, ...]:
    """Keys excluded from presets (RA-4): the profile editor renders these
    disabled with the recorded reason, and compile never claims them."""
    return tuple(key for key in CELLS[(brand, group)].keys if key.admin_only)


def uncompiled_evidence(brand: str, group: str) -> tuple[NativeKey, ...]:
    """Documented-but-not-compiled keys (shape-unmapped / experimental)."""
    return tuple(key for key in CELLS[(brand, group)].keys
                 if key.canonical is None and not key.admin_only)
