#!/usr/bin/env python3
"""Order 118: an absent artifact must never read as "no failures, therefore green".

`QA-010` measured one pinned sha giving two answers on the same suite: with the
Worker artifacts missing, `18 failed / 961 passed / 21 skipped`; with only the
artifacts added back, `1 failed / 999 passed / 0 skipped`. The 21 skips were not
"skipped by design" - they were artifact-gated cases that never ran, and the
count line had no way to say so. `QA-007` asked a *human* to write a
"Worker 工件在/不在" line next to every count; this makes the *tool* write it.

Three classes, one default. A skip reason is classified as:

  ARTIFACT  a build product this repository owns (Worker binary, sidecar entry,
            the git-ignored npm closure) - missing means the claim was not tested
  TOOL      a host capability (bwrap, node, the claude CLI, a wsl.exe channel)
  DESIGN    the test says it is out of scope here (Windows ACL evidence, ...)

Anything the rules do not name is UNKNOWN, and UNKNOWN is never green: the
whole defect is "absence read as success", so absence-of-a-classification must
not be allowed to restore it (same reasoning as order 117's tri-state).

Usage:
    python3 scripts/server-round1/artifact_presence.py            # presence report
    python3 scripts/server-round1/artifact_presence.py --classify <log>
    python3 scripts/server-round1/artifact_presence.py --self-test
"""
from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import sys

# This file is `<repo>/scripts/artifact_presence.py`, so parents[0] is `scripts`
# and parents[1] is the repo root. It used to say parents[2], which resolved to
# the repo's *parent* — so every path in ARTIFACT_PATHS was probed one level too
# high and none could ever be found. That made `render()`'s
# `WORKER_ARTIFACT=...` line unconditionally ABSENT and the whole presence report
# incapable of reporting a present artifact. Fail-safe rather than falsely green,
# but a gate that measures nothing. The paths themselves are stale in their own
# right; that is registered in docs/known-issues.md and not decided here.
ROOT = pathlib.Path(__file__).resolve().parents[1]

ARTIFACT = "ARTIFACT"
TOOL = "TOOL"
DESIGN = "DESIGN"
UNKNOWN = "UNKNOWN"

#: (label, repo-relative path). Kept literal on purpose: this is the same list
#: the skipping tests name in their own reason strings, so a drift between the
#: two is visible rather than absorbed.
ARTIFACT_PATHS = {
    "worker-debug": "workers/agent-box-worker/target/debug/agent-box-worker",
    "worker-release": "workers/agent-box-worker/target/release/agent-box-worker",
    "worker-musl-dir": "workers/agent-box-worker/target/x86_64-unknown-linux-musl",
    "sidecar-entry": "plugins/agent-box-harness/runtime/worker-entry.mjs",
    "acp-npm-closure": ("plugins/agent-box-harness/packaging/claude/node_modules"
                        "/@agentclientprotocol/claude-agent-acp"),
}

HOST_TOOLS = ("bwrap", "node", "npm", "claude", "tmux", "wsl.exe")

#: Artifacts this integration tree is expected NOT to have, each with the
#: preparation step it is waiting on. LNX-002 review item 3: the absences here are
#: a **preparation** gap - named, not a test defect - and the answer is not to
#: copy a build out of another tree to manufacture a pass.
#:
#: The register is checked in both directions by
#: `test_every_claimed_artifact_path_is_named_here_rather_than_inferred`: a new
#: absence with no entry fails, and an entry that has since been satisfied also
#: fails (so this cannot quietly outlive the gap it describes).
PREPARATION_GAPS = {
    "worker-debug": "cargo build (debug) has not been run in workers/agent-box-worker in this tree",
    "worker-release": "cargo build --release has not been run in this tree",
    "worker-musl-dir": "no x86_64-unknown-linux-musl cross-build exists in this tree",
    "acp-npm-closure": ("plugins/agent-box-harness/packaging/claude has not been npm-installed, "
                        "so the ACP client closure is absent"),
}

#: Ordered (class, pattern) rules. First match wins per class - a reason may
#: match several (the 086 round names a Worker binary *and* bubblewrap), and the
#: most severe class decides the verdict.
RULES = (
    (ARTIFACT, r"worker binary|not built|artifact|sidecar entry|node_modules|target/(debug|release)"
               r"|prebuilt|plugin runtime is unavailable"),
    (TOOL, r"bwrap|bubblewrap|node is unavailable|claude cli|npm|tmux|wsl\.exe|docker|no .*channel"),
    (DESIGN, r"windows|posix mode bits|by design|manual only|opt-in|not a .*evidence"
             r"|is not set for this run|cannot be provoked"),
)

SEVERITY = {ARTIFACT: 0, TOOL: 1, UNKNOWN: 2, DESIGN: 3}


def artifact_presence(root: pathlib.Path = ROOT) -> list[tuple[str, bool, str]]:
    return [(label, (root / relative).exists(), relative)
            for label, relative in ARTIFACT_PATHS.items()]


def tool_presence() -> list[tuple[str, bool]]:
    return [(name, shutil.which(name) is not None) for name in HOST_TOOLS]


def classify_skip(reason: str) -> list[str]:
    """Every class this reason claims, in rule order. Empty means UNKNOWN."""
    text = reason.lower()
    hits = [cls for cls, pattern in RULES if re.search(pattern, text)]
    return hits or [UNKNOWN]


def verdict(classes: set[str], failures: int) -> str:
    """The one word a count line must carry.

    `failures > 0` is not this function's problem - it is already red. This
    answers the question the old reading got wrong: *a run with zero failures*
    is still not green when a claim never ran.
    """
    if failures:
        return "FAILED"
    if ARTIFACT in classes:
        return "DEGRADED_ARTIFACT_ABSENT"
    if UNKNOWN in classes:
        return "DEGRADED_UNCLASSIFIED_SKIP"
    if TOOL in classes:
        return "PARTIAL_HOST_TOOLS_ABSENT"
    if DESIGN in classes:
        return "GREEN_DESIGN_SKIPS_ONLY"
    return "GREEN_NO_SKIPS"


def render(classes_by_node: dict[str, list[str]], failures: int = 0) -> list[str]:
    """The self-reporting block. Every line is machine-readable (`KEY=value`)."""
    lines = []
    for label, present, relative in artifact_presence():
        lines.append(f"ARTIFACT_{label}={'present' if present else 'ABSENT'} {relative}")
    for name, present in tool_presence():
        lines.append(f"TOOL_{name}={'present' if present else 'ABSENT'}")
    flat = {node: cls for node, cls in classes_by_node.items()}
    counts: dict[str, int] = {}
    for classes in flat.values():
        for cls in classes:
            counts[cls] = counts.get(cls, 0) + 1
    for cls in (ARTIFACT, TOOL, DESIGN, UNKNOWN):
        if counts.get(cls):
            lines.append(f"SKIPPED_CLASSIFIED_{cls.lower()}={counts[cls]}")
    lines.append(f"SKIPPED_TOTAL={len(flat)}")
    all_classes = {cls for classes in flat.values() for cls in classes}
    lines.append(f"WORKER_ARTIFACT={'present' if all(p for _l, p, _r in artifact_presence()) else 'ABSENT'}")
    lines.append(f"VERDICT={verdict(all_classes, failures)}")
    return lines


RS_LOG_LINE = re.compile(r"^SKIPPED\s+(?:\[.*?\]\s+)?([^:]+):(\d+):\s*(.*)$")

REASON_LITERAL = re.compile(r'(?<![A-Za-z0-9_])reason=\s*"([^"]+)"|pytest\.skip\(\s*"([^"]+)"')

#: LNX-002 review, item 2. The scan above matches a `reason="…"` keyword, and the
#: negative lookbehind keeps it from matching the tail of a *different* identifier:
#: `terminal_reason="max_tokens"` (a `complete_turn` argument) used to be read as a
#: skip reason and landed in UNKNOWN, which turned 118's drift gate red on two
#: ordinary tests. The guard is on the identifier, not on the value - no value is
#: special-cased, so a genuine `pytest.skip(reason="max_tokens")` still counts.


def skip_inventory(root: pathlib.Path = ROOT) -> list[tuple[str, str]]:
    """Every `reason=` a test can skip with, with the class it lands in.

    This is the list `QA-010` asked for and that a present-artifact tree cannot
    produce by running: a tree with everything installed shows zero skips, so
    the gates that *would* have been silent are read off their own conditions.
    It is a scan of declarations, and is labelled as such wherever it is used.
    """
    found = []
    for path in sorted((root / "tests").rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in REASON_LITERAL.finditer(line):
                reason = next(group for group in match.groups() if group)
                found.append((f"{path.relative_to(root)}:{lineno}", reason))
    return found



def classes_from_rs_log(text: str) -> dict[str, list[str]]:
    """Parse the `-rs` short summary into {nodeid-ish: classes}."""
    out: dict[str, list[str]] = {}
    for line in text.splitlines():
        match = RS_LOG_LINE.match(line.strip())
        if not match:
            continue
        path, lineno, reason = match.groups()
        out[f"{path}:{lineno}"] = classify_skip(reason)
    return out


def _self_test() -> int:
    """Fixed samples: the old reading vs this one, both directions.

    A classifier that cannot show what it changes is a classifier that was
    never needed - so the falsifier here is arithmetic, not prose.
    """
    samples = [
        ("sidecar entry not built", [ARTIFACT]),
        ("the real-harness round needs the release Worker binary and bubblewrap", [ARTIFACT, TOOL]),
        ("bwrap is required", [TOOL]),
        ("bubblewrap is not installed on this host", [TOOL]),
        ("node is unavailable", [TOOL]),
        ("no wsl.exe channel on this host", [TOOL]),
        ("POSIX mode bits are not Windows ACL evidence", [DESIGN]),
        ("some reason nobody declared", [UNKNOWN]),
    ]
    bad = 0
    for reason, expected in samples:
        got = classify_skip(reason)
        if got != expected:
            print(f"FAIL classify {reason!r}: expected {expected}, got {got}")
            bad += 1
    checks = [
        (verdict({ARTIFACT}, 0), "DEGRADED_ARTIFACT_ABSENT"),
        (verdict({UNKNOWN}, 0), "DEGRADED_UNCLASSIFIED_SKIP"),
        (verdict({TOOL}, 0), "PARTIAL_HOST_TOOLS_ABSENT"),
        (verdict({DESIGN}, 0), "GREEN_DESIGN_SKIPS_ONLY"),
        (verdict(set(), 0), "GREEN_NO_SKIPS"),
        (verdict({ARTIFACT}, 3), "FAILED"),
    ]
    for got, expected in checks:
        if got != expected:
            print(f"FAIL verdict: expected {expected}, got {got}")
            bad += 1
    # The disagreement this order exists for: QA-010's shape is 21
    # artifact-gated skips with zero failures, which the old reading called a
    # pass. If a future edit makes both rules agree, that is the regression.
    old_rule_says_green = (0 == 0)  # "failures == 0", the whole verdict it had
    new_rule_says_green = verdict({ARTIFACT}, 0).startswith("GREEN")
    if not (old_rule_says_green and not new_rule_says_green):
        print("FAIL: QA-010's shape must stay green to the old rule and not to this one")
        bad += 1
    if verdict({ARTIFACT}, 0).startswith("GREEN"):
        print("FAIL: artifact absence is still readable as green")
        bad += 1
    rendered = "\n".join(render({"t.py:1": [ARTIFACT]}))
    for token in ("WORKER_ARTIFACT=", "VERDICT="):
        if token not in rendered:
            print(f"FAIL: the report lost its own {token} line")
            bad += 1
    print(f"self-test: {len(samples)} classify samples, {len(checks)} verdict samples -> "
          + ("RED" if bad else "GREEN"))
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--classify", metavar="LOG", help="a `pytest -q -rs` output file")
    parser.add_argument("--inventory", action="store_true",
                        help="list every declared skip reason in tests/ with its class")
    parser.add_argument("--failures", type=int, default=0)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()
    if args.inventory:
        counts: dict[str, int] = {}
        for site, reason in skip_inventory():
            classes = classify_skip(reason)
            for cls in classes:
                counts[cls] = counts.get(cls, 0) + 1
            print(f"{'/'.join(classes)}\t{site}\t{reason}")
        print(f"# totals {counts}")
        return 0
    classes = classes_from_rs_log(pathlib.Path(args.classify).read_text(encoding="utf-8")) \
        if args.classify else {}
    for line in render(classes, failures=args.failures):
        print(line)
    if args.classify:
        for node, cls in sorted(classes.items()):
            print(f"SKIP\t{','.join(cls)}\t{node}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
