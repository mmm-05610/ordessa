"""Controlled document generation retains each brand's public CLI semantics."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "harness_deployment_generation", ROOT / "tooling/generation/generate-harness-deployment.py"
)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


@pytest.mark.parametrize("brand", tuple(tool.TEMPLATES))
def test_actual_selected_template_generates_original_document(brand, tmp_path):
    from functools import partial
    from importlib import import_module
    from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog
    from ordessa_agents.harness.providers.declarations.capability_claims import capability_claims

    output = tmp_path / "deployment.json"
    digest = "sha256:" + "a" * 64
    arguments = ["--out", str(output)]
    if brand == "opencode":
        arguments += ["--binary-token", "binary", "--binary-digest", digest]
    else:
        arguments += ["--artifact-token", "artifact", "--tree-digest", digest]
    assert tool.main([brand, *arguments]) == 0
    document = json.loads(output.read_text())
    template = import_module(tool.TEMPLATES[brand])
    captured = capture_selected_harness_catalog()
    expected = template.capability_claims(
        capabilities_for=partial(capability_claims, captured.registry)
    )
    assert document["harnesses"][0]["capabilityClaims"] == expected
    assert len(document["harnesses"]) == 1


def test_unknown_template_refuses_before_capture_or_output(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("unknown selection must not import a template")
    monkeypatch.setattr(tool.importlib, "import_module", forbidden)
    with pytest.raises(SystemExit) as refused:
        tool.main(["unregistered", "--out", str(tmp_path / "unused.json")])
    assert refused.value.code == 2
    assert not (tmp_path / "unused.json").exists()
