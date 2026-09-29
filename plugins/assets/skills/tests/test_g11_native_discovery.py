"""G11 — managed content and native-discovered content stay SPLIT, and the
observer physically cannot touch anything outside the given guest root.

verification.md G11 counter-examples: "用户/项目原生目录被修改, 原生项被
误报'已禁用'". The observer is read-only, $HOME-blind and symlink-shy;
native rows are never managed rows and can never be reported as disabled.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from ordessa_skills.native_discovery import observation as obs


def _skill(dir_path: Path, name: str, description: str = "d") -> Path:
    dir_path.mkdir(parents=True)
    (dir_path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\nbody\n",
        encoding="utf-8")
    return dir_path


def _snapshot(root: Path) -> dict[str, str]:
    seen = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for f in filenames:
            p = Path(dirpath) / f
            if p.is_symlink():
                seen[str(p.relative_to(root))] = "symlink"
            else:
                seen[str(p.relative_to(root))] = hashlib.sha256(
                    p.read_bytes()).hexdigest()
    return seen


SLOT = obs.DiscoverySlot("skills", "runtime_home_skills")


def test_native_rows_are_observed_split_and_read_only(tmp_path):
    root = tmp_path / "guest-home"
    _skill(root / "skills" / "alpha", "alpha")
    _skill(root / "skills" / "beta", "Beta-Native")
    before = _snapshot(root)

    report = obs.observe_native_skills(root, [SLOT])

    names = {row.native_name for row in report.observations}
    assert names == {"alpha", "Beta-Native"}
    assert all(row.location_category == "runtime_home_skills"
               for row in report.observations)
    assert all(row.provenance.startswith("skills/") and not row.provenance.startswith("/")
               for row in report.observations)
    # The observer never wrote, created or deleted a single byte.
    assert _snapshot(root) == before
    # ...and nothing appeared outside the given root.
    outside = _snapshot(tmp_path)
    assert _snapshot(root) == before
    assert "guest-home" in {p.split("/")[0] for p in outside}


def test_native_rows_are_never_managed_and_never_reported_disabled(tmp_path):
    root = tmp_path / "guest"
    _skill(root / "skills" / "solo", "solo")
    report = obs.observe_native_skills(root, [SLOT])
    row, = report.observations
    assert row.managed is False
    # No evidenced masking port exists -> honest unknown, and the only
    # disable outcome is CANNOT_DISABLE (ux.md: 不擅自显示"启用/禁用成功").
    assert row.can_be_masked == "unknown"
    assert row.disable_state == obs.CANNOT_DISABLE
    assert obs.ORDISSA_DISABLE_SCOPE == "managed_only"


def test_the_real_home_is_never_scanned():
    from ordessa_skills.api.errors import AssetDomainError
    with pytest.raises(AssetDomainError) as exc:
        obs.observe_native_skills(Path.home(), [SLOT])
    assert exc.value.code == obs.HOME_CODE


def test_symlinks_are_never_followed_out(tmp_path):
    outside = tmp_path / "outside"
    _skill(outside / "gamma", "gamma")
    root = tmp_path / "guest"
    (root / "skills").mkdir(parents=True)
    (root / "skills" / "link").symlink_to(outside / "gamma", target_is_directory=True)
    (root / "skills" / "real").symlink_to(outside, target_is_directory=True)

    before = _snapshot(outside)
    report = obs.observe_native_skills(root, [SLOT])

    assert report.observations == ()
    assert any("symlink" in d for d in report.diagnostics)
    assert _snapshot(outside) == before  # not even read through


def test_whole_slot_symlink_is_skipped(tmp_path):
    outside = tmp_path / "outside-skills"
    _skill(outside / "delta", "delta")
    root = tmp_path / "guest"
    root.mkdir()
    (root / "skills").symlink_to(outside, target_is_directory=True)
    report = obs.observe_native_skills(root, [SLOT])
    assert report.observations == ()
    assert any("symlink" in d for d in report.diagnostics)


def test_budgets_are_inherited_and_enforced(tmp_path):
    from ordessa_skills.api.identity import (
        MAX_ASSET_ENTRIES, MAX_FRONTMATTER_BYTES)
    assert MAX_ASSET_ENTRIES == 512
    assert MAX_FRONTMATTER_BYTES == 64 * 1024
    root = tmp_path / "guest"
    for name in ("a1", "a2", "a3"):
        _skill(root / "skills" / name, name)

    with pytest.raises(obs.NativeDiscoveryError) as exc:
        obs.observe_native_skills(root, [SLOT], budget_entries=2)
    assert exc.value.code == obs.BUDGET_CODE

    # Oversize SKILL.md -> diagnosed, not ingested.
    fat = root / "skills" / "a1" / "SKILL.md"
    fat.write_text("---\nname: a1\ndescription: x\n---\n" + "y" * (64 * 1024),
                   encoding="utf-8")
    report = obs.observe_native_skills(root, [SLOT])
    names = {row.native_name for row in report.observations}
    assert "a1" not in names
    assert any("budget" in d or "exceeds" in d for d in report.diagnostics)


def test_slot_paths_are_relative_only():
    with pytest.raises(obs.NativeDiscoveryError):
        obs.DiscoverySlot("/runtime/home/skills", "runtime_home_skills")
    with pytest.raises(obs.NativeDiscoveryError):
        obs.DiscoverySlot("skills/../../../etc", "x")
    with pytest.raises(obs.NativeDiscoveryError):
        obs.DiscoverySlot("~/skills", "home")


def test_the_directory_handle_of_every_scanned_slot_is_closed(tmp_path, monkeypatch):
    """fd hygiene: the sweep must not leak the scandir directory handle —
    not on the happy path, not when the budget aborts mid-scan."""
    root = tmp_path / "guest"
    _skill(root / "skills" / "alpha", "alpha")
    _skill(root / "skills" / "beta", "beta")
    real_scandir = os.scandir
    opened: list = []

    class _Tracked:
        def __init__(self, inner) -> None:
            self._inner = inner
            self.closed = False
            opened.append(self)

        def __iter__(self):
            return iter(self._inner)

        def close(self):
            self.closed = True
            self._inner.close()

    monkeypatch.setattr(
        obs.os, "scandir",
        lambda path, *a, **k: _Tracked(real_scandir(path, *a, **k)))

    report = obs.observe_native_skills(root, [SLOT])
    assert len(report.observations) == 2
    assert opened, "the sweep never opened a scandir handle — the probe checks nothing"
    assert all(item.closed for item in opened)

    # Budget refusal aborts mid-scan; the handle is still closed.
    opened.clear()
    with pytest.raises(obs.NativeDiscoveryError):
        obs.observe_native_skills(root, [SLOT], budget_entries=1)
    assert opened and all(item.closed for item in opened)


def test_scandir_leak_surfaces_as_error_under_resourcewarning(tmp_path):
    # Belt to the counting fake's braces: with ResourceWarning escalated,
    # an unclosed scandir iterator would abort the sweep with a warning.
    import warnings
    root = tmp_path / "guest"
    _skill(root / "skills" / "alpha", "alpha")
    with warnings.catch_warnings():
        warnings.simplefilter("error", ResourceWarning)
        report = obs.observe_native_skills(root, [SLOT])
    assert len(report.observations) == 1


def test_observer_source_never_imports_the_library_or_writes():
    import ast
    from pathlib import Path as P
    src = P(obs.__file__)
    tree = ast.parse(src.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = node.module if isinstance(node, ast.ImportFrom) else None
            names = ([mod] if mod else []) + [
                a.name for a in node.names if isinstance(node, ast.Import)]
            for name in names:
                assert "library" not in (name or ""), src
        if isinstance(node, ast.Attribute):
            assert node.attr not in {
                "write_text", "write_bytes", "mkdir", "rmtree", "remove",
                "touch", "chmod"}, f"write primitive {node.attr} in {src}"
