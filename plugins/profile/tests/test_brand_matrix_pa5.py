"""PA-5 controlled brand matrix: pi / codex / claude-code.

Four matrix cells per brand, driven through the REAL harness brand faces
(read-only consumption of ``ordessa_harness`` renderers) on top of the
profile-api public surface — never directly against the profile store:

- 字段投影 golden: each brand's own renderer consumes controlled profile
  facts and the projection is pinned byte-for-byte against
  ``tests/goldens/brand_matrix/<brand>.json``.
- 会话覆盖/切 Profile 清除: a session-only overlay is present, a switch is
  confirmed through the port, and the overlay clears while a second
  session on the same harness keeps its own state; the brand face renders
  the post-switch effective fields with no residue.
- reset 到品牌面: A→B where B lacks the ``extra`` item compiles an
  explicit reset intent that reaches the port (G08); the brand face
  re-rendered from B equals the clean-B golden, so the removed field is
  gone from the brand projection — never filtered, never faked.
- restart-resume 保活: a controlled restart (fresh ProfileCore over the
  same store) keeps the settled binding and its receipt; a pending
  selection survives the restart and applies exactly once afterwards.

Environment facts (F5, first-hand evidence in
specs/014-plugin-release/reports/P-A-report.md): the codex and claude CLI
binaries are absent on this machine, so those rows stop at the controlled
brand face and their "real CLI load" cell is unknown; the local ``pi``
(0.86.1) is version-skewed against the 0.84.2 pin and its probe record
proved the projected ``--agent-dir``/``--skill-dir`` flags are hard errors
on 0.86.1, so the pi row is offline controlled too. The port double is the
shared marked controlled fixture (ScriptedConfigPort); the harness faces
are consumed read-only, nothing under plugins/harness is modified.
"""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from conftest import ScriptedConfigPort, ScriptedV2Provider, make_core

BRANDS = ("pi", "codex", "claude-code")
GOLDEN_DIR = Path(__file__).resolve().parent / "goldens" / "brand_matrix"
WRITE_GOLDENS = os.environ.get("ORDESSA_PROFILE_MATRIX_WRITE_GOLDENS") == "1"

FACET = "model"
CHOICE = "choice"
EXTRA = "extra"
A_CHOICE = "alpha"
B_CHOICE = "beta"
EXTRA_VALUE = "override"


# --------------------------------------------------------------- brand faces
# One mapping per brand from the abstract {choice, extra} facts into that
# brand's native rendering face — the same canonical→dialect discipline
# native_materialization applies to protocols, applied to profile fields.


def _pi_face(root: Path, *, value: str, extra: bool) -> dict:
    from ordessa_harness.pi.config import PiProfile
    from ordessa_harness.pi.projection import PiProjection
    from pacthold_runtime_compat.resource_contracts import (
        PromptFragmentV1, WorkspaceV1)

    # each face invocation gets its own tree: a shared pi-home would let a
    # previous call's instructions.md leak into the directory-tree digest
    root = root / "faces" / f"{value}-{int(extra)}"
    home = root / "pi-home"
    home.mkdir(parents=True, exist_ok=True)
    sessions = home / "sessions"
    sessions.mkdir(exist_ok=True)
    binary = root / "pi-offline-stand-in"
    binary.write_bytes(b"#!controlled-offline-stand-in\n")
    instructions = None
    if extra:
        instructions = home / "instructions.md"
        instructions.write_text("controlled instructions\n", encoding="utf-8")
    workspace = root / "workspace"
    workspace.mkdir(exist_ok=True)
    (workspace / "README.md").write_bytes(b"controlled workspace\n")
    profile = PiProfile(
        profile_id="p1", revision=1, digest="sha256:" + "0" * 64,
        binary=str(binary), agent_dir=home, session_root=sessions,
        model=value, instructions=instructions)
    request = SimpleNamespace(
        resolved_inputs=[
            SimpleNamespace(contract_id=WorkspaceV1.contract_id,
                            value=WorkspaceV1(path=workspace,
                                              source_digest="sha256:ws")),
            SimpleNamespace(contract_id=PromptFragmentV1.contract_id,
                            value=PromptFragmentV1(
                                title="t", content="hello",
                                digest="sha256:frag")),
        ],
        execution_id="exec-1")
    spec = PiProjection().command(request, profile)
    return {
        "argv": list(spec.argv),
        "cwd_token": spec.cwd_token,
        "io_mode": spec.io_mode,
        "projector_id": spec.projector_id,
        "sources": sorted(
            [s.kind, s.guest_target, s.access, s.provenance, s.expected_digest]
            for s in spec.runtime_sources),
    }


def _codex_face(root: Path, *, value: str, extra: bool) -> dict:
    from ordessa_harness.codex import production
    declaration = production.harness_deployment(
        artifact_token="matrix-token-0001",
        tree_digest="sha256:" + "0" * 64,
        preferred_auth_method=value,
        adapter_environment=(
            {"CODEX_HOME": production.CODEX_HOME, "NO_BROWSER": "1",
             "ORDESSA_MATRIX_EXTRA": EXTRA_VALUE}
            if extra else None))
    return declaration


def _claude_face(root: Path, *, value: str, extra: bool) -> dict:
    from ordessa_harness.claude.profile import ClaudeProfileRef, ClaudeProjection

    settings: dict = {"model": value}
    if extra:
        settings["permissions"] = {"allow": ["Read"]}

    class _Repo:
        def get(self, profile_id, revision):
            return {"profile": {
                "settings": settings,
                "credential_locator": "vault://controlled-locator"}}

    # per-invocation execution root: a shared dir would let a previous
    # call's agent-box-manifest.json leak into native_files
    projection = ClaudeProjection(
        root / "claude-exec-roots" / f"{value}-{int(extra)}", _Repo())
    ref = ClaudeProfileRef("p1", 1, "sha256:" + "0" * 64)
    out = projection.materialize("exec-1", ref, resources=(
        ("instruction", "AGENTS.md", "controlled instructions\n"),
        ("mcp", "controlled-server", {"command": "/bin/true"}),
        ("skill", "demo", "# demo\n"),
    ))
    return {
        "settings": json.loads(
            (out / ".claude" / "settings.json").read_text(encoding="utf-8")),
        "mcp": json.loads((out / ".mcp.json").read_text(encoding="utf-8")),
        "manifest": json.loads(
            (out / "agent-box-manifest.json").read_text(encoding="utf-8")),
    }


_FACES = {"pi": _pi_face, "codex": _codex_face, "claude-code": _claude_face}


def _face(brand: str, root: Path, *, value: str, extra: bool) -> dict:
    return _FACES[brand](root, value=value, extra=extra)


def _golden(brand: str) -> dict:
    path = GOLDEN_DIR / f"{brand}.json"
    if WRITE_GOLDENS:
        return {}
    assert path.exists(), (
        f"brand golden missing: {path}; regenerate with "
        "ORDESSA_PROFILE_MATRIX_WRITE_GOLDENS=1 and commit it")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_goldens(brand: str, payload: dict) -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    (GOLDEN_DIR / f"{brand}.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")


# ----------------------------------------------------------------- fixtures


def _world(ce: Path, brand: str, *, port: ScriptedConfigPort | None = None):
    ce.mkdir(parents=True, exist_ok=True)
    core = make_core(
        ce, harnesses={brand: frozenset()},
        config_port=port if port is not None else ScriptedConfigPort(),
        v2_providers=((ScriptedV2Provider(
            FACET, ((CHOICE, {"type": "string"}), (EXTRA, {"type": "string"})),
            schema_version="1.0.0", capability_rule="yes"),
            "brand-matrix-domain"),),
    )
    a = core.profiles.create("ka", harness_id=brand, display_name="A")
    b = core.profiles.create("kb", harness_id=brand, display_name="B")
    core.profiles.set_facet_values(
        "ka1", profile_id=a["profile_id"], expected_version=1,
        values=[{"facet_id": FACET, "item_id": CHOICE, "value": A_CHOICE},
                {"facet_id": FACET, "item_id": EXTRA, "value": EXTRA_VALUE}])
    core.profiles.set_facet_values(
        "kb1", profile_id=b["profile_id"], expected_version=1,
        values=[{"facet_id": FACET, "item_id": CHOICE, "value": B_CHOICE}])
    core.sessions.open_session("ks", session_id="S", harness_id=brand,
                               profile_id=a["profile_id"])
    core.sessions.open_session("kt", session_id="T", harness_id=brand,
                               profile_id=a["profile_id"])
    return core, a, b


# -------------------------------------------------------------------- cells


@pytest.mark.parametrize("brand", BRANDS)
def test_brand_field_projection_matches_golden(tmp_path, brand):
    """Cell 1 — 字段投影 golden: the real brand face renders controlled
    profile facts exactly as pinned."""
    payload = {"projection": _face(brand, tmp_path, value=A_CHOICE, extra=True),
               "after_switch": _face(brand, tmp_path, value=B_CHOICE,
                                     extra=False)}
    if WRITE_GOLDENS:
        _write_goldens(brand, payload)
        pytest.skip("golden written; rerun without the write env")
    assert payload == _golden(brand)


@pytest.mark.parametrize("brand", BRANDS)
def test_brand_switch_clears_overlay_and_keeps_other_sessions(tmp_path, brand):
    """Cell 2 — 会话覆盖/切 Profile 清除: overlay clears only on a confirmed
    switch, the other session is untouched, and the brand face renders the
    post-switch fields with no residue."""
    core, a, b = _world(tmp_path / "ce", brand)
    core.sessions.set_overlay(
        "o1", session_id="S", facet_id=FACET, item_id=CHOICE,
        value="gamma")
    core.sessions.set_overlay(
        "o2", session_id="T", facet_id=FACET, item_id=CHOICE,
        value="tau")
    s_config = core.sessions.session_config("S")
    overlay_values = {i["item_id"]: i["value"] for i in s_config["items"]}
    assert overlay_values[CHOICE] == "gamma"  # overlay wins while it lives
    assert s_config["switch_state"] == "settled"

    core.sessions.select_profile("sel1", session_id="S",
                                 profile_id=b["profile_id"])
    ticket = core.sessions.begin_turn("t1", session_id="S")
    assert ticket["applied_switch"] is True
    s_config = core.sessions.session_config("S")
    assert s_config["current"]["profile_id"] == b["profile_id"]
    assert s_config["switch_state"] == "settled"
    assert s_config["pending"] is None
    values = {i["item_id"]: i["value"] for i in s_config["items"]}
    sources = {i["item_id"]: i["source"] for i in s_config["items"]}
    assert values[CHOICE] == B_CHOICE and sources[CHOICE] == "profile"
    # B lacks the extra item entirely: the switch removed it from the
    # effective projection (no overlay residue, no stale profile value)
    assert EXTRA not in values

    t_config = core.sessions.session_config("T")
    t_values = {i["item_id"]: i["value"] for i in t_config["items"]}
    t_sources = {i["item_id"]: i["source"] for i in t_config["items"]}
    assert t_config["current"]["profile_id"] == a["profile_id"]
    assert t_values[CHOICE] == "tau" and t_sources[CHOICE] == "session_only"

    # the post-switch face renders B's fields with no A residue
    assert _face(brand, tmp_path, value=B_CHOICE, extra=False) == \
        _golden(brand)["after_switch"]


@pytest.mark.parametrize("brand", BRANDS)
def test_brand_reset_reaches_port_and_brand_face(tmp_path, brand):
    """Cell 3 — reset 到品牌面: A→B removes the extra item; an explicit
    reset intent reaches the port (G08) and the re-rendered brand face
    equals the clean-B golden — the removal is real, never filtered."""
    ce = tmp_path / "ce"
    port = ScriptedConfigPort()
    core, a, b = _world(ce, brand, port=port)
    # contrast face: A's state still carries the extra field
    assert _face(brand, tmp_path, value=A_CHOICE, extra=True) == \
        _golden(brand)["projection"]

    core.config_port = port
    core.sessions.select_profile("sel1", session_id="S",
                                 profile_id=b["profile_id"])
    ticket = core.sessions.begin_turn("t1", session_id="S")
    assert ticket["applied_switch"] is True
    applied = port.applied[0]
    ops = {(i.facet_id, i.item_id): i.op for i in applied}
    values = {(i.facet_id, i.item_id): i.value for i in applied}
    assert ops[(FACET, EXTRA)] == "reset"          # explicit, not filtered
    assert ops[(FACET, CHOICE)] == "set"
    assert values[(FACET, CHOICE)] == B_CHOICE

    s_config = core.sessions.session_config("S")
    assert s_config["switch_state"] == "settled"
    assert _face(brand, tmp_path, value=B_CHOICE, extra=False) == \
        _golden(brand)["after_switch"]


@pytest.mark.parametrize("brand", BRANDS)
def test_brand_restart_resume_keeps_binding(tmp_path, brand):
    """Cell 4 — restart-resume 保活: a controlled restart keeps the settled
    binding and receipt; a pending selection survives the restart and
    applies exactly once afterwards."""
    ce = tmp_path / "ce"
    core, a, b = _world(ce, brand)
    core.sessions.select_profile("sel1", session_id="S",
                                 profile_id=b["profile_id"])
    core.sessions.begin_turn("t1", session_id="S")

    restarted = make_core(
        ce, harnesses={brand: frozenset()},
        config_port=ScriptedConfigPort(),
        v2_providers=((ScriptedV2Provider(
            FACET, ((CHOICE, {"type": "string"}), (EXTRA, {"type": "string"})),
            schema_version="1.0.0", capability_rule="yes"),
            "brand-matrix-domain"),),
    )
    s_config = restarted.sessions.session_config("S")
    assert s_config["current"]["profile_id"] == b["profile_id"]
    assert s_config["switch_state"] == "settled"
    assert s_config["evidence"]["journal"]["state"] == "confirmed"
    assert s_config["evidence"]["receipt"] is not None
    # a turn without a pending selection never re-applies anything
    ticket = restarted.sessions.begin_turn("t2", session_id="S")
    assert ticket["applied_switch"] is False
    assert restarted.config_port.counters["apply"] == 0

    c = restarted.profiles.create("kc", harness_id=brand, display_name="C")
    restarted.profiles.set_facet_values(
        "kc1", profile_id=c["profile_id"], expected_version=1,
        values=[{"facet_id": FACET, "item_id": CHOICE, "value": "gamma"}])
    restarted.sessions.select_profile("sel2", session_id="S",
                                      profile_id=c["profile_id"])

    resumed = make_core(
        ce, harnesses={brand: frozenset()},
        config_port=ScriptedConfigPort(),
        v2_providers=((ScriptedV2Provider(
            FACET, ((CHOICE, {"type": "string"}), (EXTRA, {"type": "string"})),
            schema_version="1.0.0", capability_rule="yes"),
            "brand-matrix-domain"),),
    )
    s_config = resumed.sessions.session_config("S")
    assert s_config["switch_state"] == "pending"  # the pending switch survived
    assert s_config["pending"]["profile_id"] == c["profile_id"]
    ticket = resumed.sessions.begin_turn("t3", session_id="S")
    assert ticket["applied_switch"] is True
    assert resumed.config_port.counters["apply"] == 1  # exactly once
    assert resumed.sessions.session_config("S")["current"]["profile_id"] == \
        c["profile_id"]
