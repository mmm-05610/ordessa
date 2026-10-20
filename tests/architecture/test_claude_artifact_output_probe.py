"""Countertests for the explicit Claude output detector.

These only exercise path/marker validation using pytest-owned temporary files;
they do not claim to build or validate the Claude ACP runtime artifact.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

DETECTOR = Path(__file__).resolve().parents[2] / "tooling" / "checks" / "artifact_presence.py"
MARKER = ".agentbox-claude-runtime-artifact"
MARKER_CONTENT = "agentbox-claude-runtime-artifact-r1\n"
ENTRY = Path("node_modules/@agentclientprotocol/claude-agent-acp/dist/index.js")
ENV = "ORDESSA_CLAUDE_RUNTIME_ARTIFACT_OUTPUT"


def _load_detector():
    spec = importlib.util.spec_from_file_location("artifact_presence_countertests", DETECTOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _owned_output(path: Path, marker_bytes: bytes | None = None) -> Path:
    path.mkdir(parents=True)
    marker = MARKER_CONTENT.encode("utf-8") if marker_bytes is None else marker_bytes
    (path / MARKER).write_bytes(marker)
    entry = path / ENTRY
    entry.parent.mkdir(parents=True)
    entry.write_bytes(b"controlled marker-probe fixture; not a built runtime")
    return path


def test_claude_output_inside_repository_is_rejected(tmp_path, monkeypatch):
    detector = _load_detector()
    repo = tmp_path / "repo"
    output = _owned_output(repo / "artifacts" / "claude")
    monkeypatch.setattr(detector, "ROOT", repo)
    monkeypatch.setenv(ENV, str(output))

    present, detail = detector._claude_runtime_artifact_presence()

    assert not present
    assert "outside the repository" in detail


def test_claude_output_outside_repository_requires_owned_marker_and_entry(tmp_path, monkeypatch):
    detector = _load_detector()
    repo = tmp_path / "repo"
    repo.mkdir()
    output = _owned_output(tmp_path / "claude-artifact")
    monkeypatch.setattr(detector, "ROOT", repo)
    monkeypatch.setenv(ENV, str(output))

    present, detail = detector._claude_runtime_artifact_presence()

    assert present
    assert "marker and ACP entry present" in detail
    assert str(output) not in detail


@pytest.mark.parametrize("kind", ["missing", "symlink"])
def test_missing_or_symlink_output_is_not_a_built_artifact(tmp_path, monkeypatch, kind):
    detector = _load_detector()
    repo = tmp_path / "repo"
    repo.mkdir()
    if kind == "missing":
        output = tmp_path / "not-built"
    else:
        target = _owned_output(tmp_path / "real-output")
        output = tmp_path / "output-link"
        output.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(detector, "ROOT", repo)
    monkeypatch.setenv(ENV, str(output))

    present, detail = detector._claude_runtime_artifact_presence()

    assert not present
    assert "NOT_BUILT" in detail


def test_invalid_utf8_marker_fails_closed_as_not_built(tmp_path, monkeypatch):
    detector = _load_detector()
    repo = tmp_path / "repo"
    repo.mkdir()
    output = _owned_output(tmp_path / "invalid-marker", marker_bytes=b"\xff")
    monkeypatch.setattr(detector, "ROOT", repo)
    monkeypatch.setenv(ENV, str(output))

    present, detail = detector._claude_runtime_artifact_presence()

    assert not present
    assert "NOT_BUILT" in detail
