#!/usr/bin/env python3
"""001 T001-02/T001-07 — classify tracked files and freeze the source manifest.

Outputs JSON on stdout: one record per git-tracked file with category,
type, mode, symlink target and (for non-binary text/code inputs) a sha256
content digest. Re-run and diff to detect concurrent edits; symlink
targets outside the repo root are flagged so the caller can refuse.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys

ROOT = subprocess.run(
    ["git", "-C", os.path.dirname(os.path.abspath(__file__)), "rev-parse", "--show-toplevel"],
    check=True, capture_output=True, text=True,
).stdout.strip()

# Paths that must never be tracked; a hit is a hard failure, not a category.
FORBIDDEN_PATTERNS = (
    "key.txt", "token.txt", ".env", "secrets/", ".secret", "credentials/",
    ".c1-001-runtime", ".c1-001-secrets", "runtime/native-pi-user",
)

TEST_MARKERS = (
    "/tests/", "/test/", "test_", "_test.py", ".test.ts", ".test.tsx",
    ".test.mjs", ".test.js", "_spec.ts", "/testsuite/",
)

DOC_SUFFIXES = (".md", ".txt", ".rst", ".adoc")
ASSEMBLY_NAMES = (
    "package.json", "package-lock.json", "pyproject.toml", "tsconfig.json",
    "manifest.json", "extensions.json", "extensions.lock", "vitest.config.ts",
    "vitest.config.mjs", "rollup.config.mjs", "harnesses.toml", "uv.lock",
    "requirements.txt", "setup.cfg",
)
SOURCE_SUFFIXES = (
    ".py", ".ts", ".tsx", ".mjs", ".js", ".cjs", ".go", ".sql", ".css",
    ".html", ".json", ".toml", ".sh", ".yml", ".yaml", ".svg", ".pyi",
)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", ROOT, *args], check=True, capture_output=True, text=True
    ).stdout


def classify(path: str) -> tuple[str, str]:
    """Return (category, note) for a tracked path."""
    low = path.lower()
    base = os.path.basename(path)
    for pat in FORBIDDEN_PATTERNS:
        if pat in low:
            return ("forbidden", pat)
    suffix = os.path.splitext(base)[1].lower()
    if suffix in (".c", ".h"):
        return ("source", "")
    if base in ("Makefile", "MANIFEST.in", "SHA256SUMS") or suffix in (
        ".mod", ".sum", ".typed",
    ) or base == ".gitignore":
        return ("assembly", "")
    if suffix in (".pdf", ".tgz"):
        return ("asset-binary", "")
    if path.startswith((".github/", "tooling/", "packaging/", "scripts/")) or base in ASSEMBLY_NAMES:
        return ("assembly", "")
    if any(m in low for m in TEST_MARKERS) or low.endswith(TEST_MARKERS[4:7]):
        return ("test", "")
    if suffix in DOC_SUFFIXES or path.startswith(("docs/", "specs/", "evidence/", ".specify/")):
        return ("doc", "")
    if suffix in SOURCE_SUFFIXES:
        return ("source", "")
    if suffix in (".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".icns"):
        return ("asset-binary", "")
    return ("other", suffix or "no-ext")


def digest(rel: str) -> str | None:
    p = os.path.join(ROOT, rel)
    st = os.lstat(p)
    if stat.S_ISLNK(st.st_mode):
        return None
    if stat.S_ISREG(st.st_mode) and st.st_size > 8 * 1024 * 1024:
        return "LARGE:" + str(st.st_size)
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    files = git("ls-files", "-z").split("\0")
    records = []
    violations = []
    for path in files:
        if not path:
            continue
        p = os.path.join(ROOT, path)
        st = os.lstat(p)
        category, note = classify(path)
        if category == "forbidden":
            violations.append({"path": path, "note": note})
        rec = {
            "path": path,
            "category": category,
            "note": note,
            "mode": oct(stat.S_IMODE(st.st_mode)),
            "type": ("symlink" if stat.S_ISLNK(st.st_mode)
                     else "dir" if stat.S_ISDIR(st.st_mode) else "file"),
        }
        if stat.S_ISLNK(st.st_mode):
            target = os.readlink(p)
            rec["link"] = target
            resolved = os.path.normpath(os.path.join(os.path.dirname(path), target))
            if resolved.startswith(".."):
                rec["outOfBounds"] = True
                violations.append({"path": path, "note": "symlink escapes repo root"})
        else:
            d = digest(path)
            if d:
                rec["sha256"] = d
        records.append(rec)
    summary: dict[str, int] = {}
    for r in records:
        summary[r["category"]] = summary.get(r["category"], 0) + 1
    out = {
        "head": git("rev-parse", "HEAD").strip(),
        "generatedBy": os.path.abspath(__file__),
        "summary": summary,
        "violations": violations,
        "files": records,
    }
    json.dump(out, sys.stdout, indent=1, sort_keys=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
