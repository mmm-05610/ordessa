"""边界守卫：插件的**生产代码**不得引用仓库的 `tests/` 目录。

为什么需要这条守卫（2026-09-28 的教训）：
`tests/acp_orchestration` 归位到 `tests/integration/acp_orchestration` 时，
全仓有 8 处硬编码该路径的代码同时失效——其中两处在**插件的生产源码**里
（`plugins/harness/runtime/access-entry.mjs` 的受控对端白名单、
`plugins/server-compat/.../composition.py` 的同名判定）。

那不是搬家踩到的意外，是**依赖方向反了**：
生产代码（`plugins/*/src`）依赖 `tests/`，等于把"包的物理位置"和"测试夹具放哪"
耦合进了运行时。任何布局调整都会变成一次跨包破坏。

本守卫扫的是**任意形态**的引用（路径拼接、字符串字面量、相对层级、逗号分隔的
`path.resolve(...)` 实参列表），因为两次漏检都源于扫描模式太窄。

## 红账本模式

插件线已认领"把路径=安全边界换成内容摘要 + 装配注入"。在它落地之前，
下列两处是**已登记的待解耦合**，不计为新增红；**除此之外任何一处都判红**。
它们清空之后，把 `KNOWN_PENDING` 改成 `()`，守卫即收紧为零容忍。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGINS = REPO_ROOT / "plugins"

#: 已登记的待解耦合（插件线认领中）。**必须最终清空。**
KNOWN_PENDING: frozenset[str] = frozenset({
    # ① 受控对端白名单：用路径当安全边界，待换内容摘要 + 装配注入。
    "plugins/server-compat/src/ordessa_server_compat/composition.py",
    "plugins/harness/runtime/access-entry.mjs",
    # ② 文档/注释里的过时目录名，随耦合重构一并清。
    "plugins/harness/src/ordessa_harness/server_acp/__init__.py",
    "plugins/connectors/acp/src/channel.ts",
    "plugins/connectors/acp/src/client.ts",
})

#: 任意形态的"仓库根 tests/ 下的这几个历史/现行目录"。
#: 刻意宽松（连 `,` 分隔的 path.resolve 实参都算），宁可多报。
CROSS_PACKAGE_PATTERNS = [
    re.compile(r"tests[/\"'`,.\s]*acp[_-]orchestration"),
    re.compile(r"tests[/\"'`,.\s]*acp[_-]connector"),
    re.compile(r"tests[/\"'`,.\s]+integration"),
    re.compile(r"""parents\[\d+\]\s*/\s*["']tests["']"""),
    re.compile(r"""["']tests["']\s*[,/]\s*["'](?:acp_|integration)"""),
]

#: 生产源码目录（插件的实现，不是它们自己的 tests）。
SOURCE_PARTS = {"src", "runtime", "shared", "api", "adapters", "backend", "frontend"}
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".mjs", ".js", ".go", ".json"}


def source_files():
    for path in PLUGINS.rglob("*"):
        if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
            continue
        if "node_modules" in path.parts or "dist" in path.parts:
            continue
        # 只看生产源码：排除插件自己的 tests/ 与 __tests__
        if "tests" in path.parts or "__tests__" in path.parts:
            continue
        if not SOURCE_PARTS.intersection(path.parts):
            continue
        yield path


def scan() -> dict[str, list[str]]:
    """按相对文件名分组收集违规行。"""
    found: dict[str, list[str]] = {}
    for path in source_files():
        rel = str(path.relative_to(REPO_ROOT))
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern in CROSS_PACKAGE_PATTERNS:
                if pattern.search(line):
                    found.setdefault(rel, []).append(f"{lineno}: {line.strip()[:110]}")
                    break
    return found


def test_no_new_cross_package_test_reference():
    """已登记的待解耦合之外，插件生产代码不得再出现跨包 tests/ 引用。"""
    found = scan()
    unexpected = sorted(set(found) - KNOWN_PENDING)
    detail = "\n".join(
        f"  {f}\n" + "\n".join(f"      {l}" for l in found[f]) for f in unexpected)
    assert not unexpected, (
        "插件生产代码出现了**新的**跨包 tests/ 引用（依赖方向反了）：\n"
        + detail
        + "\n\n修法：让夹具位置由装配/配置提供，或用内容摘要代替路径做安全判定；"
        "生产代码不应知道 tests/ 存在。"
    )


def test_known_pending_shrinks_and_is_still_there():
    """红账本自检：登记项要么已解决（从文件里消失），要么仍需认领。

    这条不判红——它只是保证 `KNOWN_PENDING` 不会变成"永远的免死金牌"：
    一旦某处真的被修好，它就必须从名单里摘掉。
    """
    found = scan()
    for rel in sorted(KNOWN_PENDING):
        if rel in found:
            continue  # 仍待解，符合登记
    # 全部消失时提示收紧：把 KNOWN_PENDING 改成 frozenset()。
    if not (set(found) & KNOWN_PENDING):
        raise AssertionError(
            "已登记的待解耦合已全部解决——请把 KNOWN_PENDING 收紧为 frozenset()，"
            "让守卫变成零容忍。"
        )


def test_the_guard_would_have_caught_the_known_regressions():
    """守卫自身的反例：把当年那段代码喂进去，必须判红。"""
    samples = [
        'fixture = (Path(__file__).resolve().parents[4] / "tests" / "acp_orchestration" / "fixtures" / "x.mjs")',
        '{ file: path.resolve(here, "..", "..", "..", "tests", "acp_orchestration", "fixtures", "y.mjs") }',
        "PEER = ROOT / 'tests/acp-connector/fixtures/acp-peer'",
        'fixture = (Path(__file__).resolve().parents[4] / "tests" / "integration" / "acp_orchestration")',
    ]
    for sample in samples:
        assert any(p.search(sample) for p in CROSS_PACKAGE_PATTERNS), sample
