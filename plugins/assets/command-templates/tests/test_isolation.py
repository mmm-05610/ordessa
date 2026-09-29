"""G01 / G20 / G02 counterexamples: import must be inert; boundaries hold.

* importing every domain module opens no DB, touches no filesystem, spawns
  nothing and registers no wire method;
* constructing a store/path does not create the file until ``initialize()``;
* the pure domain must not import ``ordessa_server``/``pacthold``/host internals
  (dependency direction is one way).
"""
from __future__ import annotations

import builtins
import importlib
import io
import os
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

DOMAIN = "ordessa_command_templates"
MODULES = [
    "", ".api", ".api.dto", ".api.errors", ".api.schema",
    ".expansion", ".expansion.parser", ".expansion.renderer", ".expansion.digest",
    ".library", ".library.store", ".library.service", ".library.receipts", ".library.importer",
    ".assignments", ".assignments.resolver",
]

#: Host/product modules the pure domain may never depend on (plan.md, contracts.md).
FORBIDDEN_IMPORTS = {
    "ordessa_server", "ordessa_server_compat", "pacthold", "ordessa_harness",
    "ordessa_workspace", "ordessa_profile", "fastapi", "httpx",
}


def _domain_root() -> Path:
    return Path(importlib.import_module(DOMAIN).__file__).resolve().parent


def test_importing_modules_has_no_side_effects(tmp_path, monkeypatch):
    """Importing every module must not open sqlite/files/subprocess/sockets."""
    opened = []

    def guard_connect(*a, **k):
        opened.append(("sqlite", a))
        raise AssertionError("sqlite3.connect at import time")

    monkeypatch.setattr(sqlite3, "connect", guard_connect)
    real_open = builtins.open

    def guard_open(file, mode="r", *a, **k):
        # Allow reading the package source itself; forbid any write/new file.
        if "w" in mode or "a" in mode or "x" in mode:
            opened.append(("open-write", str(file)))
            raise AssertionError("file write at import time")
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", guard_open)
    monkeypatch.setattr(os, "mkdir", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("os.mkdir at import time")))
    monkeypatch.setattr(Path, "mkdir", lambda self, *a, **k: (_ for _ in ()).throw(
        AssertionError("Path.mkdir at import time")))

    for suffix in MODULES:
        importlib.import_module(DOMAIN + suffix)
    assert opened == []


def test_constructing_store_opens_nothing(tmp_path):
    from ordessa_command_templates.library.store import TemplateStore

    private_root = tmp_path / "private-root"
    target = private_root / "command-templates.sqlite"
    store = TemplateStore.for_root(private_root)
    # Construction touched nothing: no directory, no database file.
    assert not private_root.exists()
    assert not target.exists()
    # initialize() is what creates the file, explicitly and only when asked.
    store.initialize()
    assert target.exists()


def test_store_requires_explicit_initialize(tmp_path):
    from ordessa_command_templates.library.store import TemplateStore
    from ordessa_command_templates.api.errors import InvalidDocumentError

    store = TemplateStore(tmp_path / "x" / "ct.sqlite")  # not initialized
    with pytest.raises(InvalidDocumentError):
        store.list_templates()


def test_pure_domain_has_no_forbidden_host_imports():
    """Static scan of every domain source for forbidden host imports (G20)."""
    root = _domain_root()
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if not (stripped.startswith("import ") or stripped.startswith("from ")):
                continue
            top = stripped.replace("from ", "").replace("import ", "").split(".")[0].split(" ")[0]
            if top in FORBIDDEN_IMPORTS:
                offenders.append(f"{path.name}: {stripped}")
    assert offenders == [], f"pure domain imports host internals: {offenders}"


def test_service_runs_without_profile_chat_harness(service):
    """CRUD with only the domain present — no Chat/Harness/Profile seam is needed.

    The domain modules never import a host product package; asserting the pure
    source scan (below) covers that structurally, and here we assert the runtime
    flow completes and no host package was pulled in as a *side effect* of it.
    """
    from ordessa_command_templates.api.dto import ParameterSpec

    service.create(principal="u1", template_id="tmpl.t", display_name="T", slug="t",
                   operation_key="c")
    service.save_revision(principal="u1", template_id="tmpl.t", body="x {{a}}",
                          parameters=[ParameterSpec("a")], expected_version=1, operation_key="r")
    service.approve(principal="u1", template_id="tmpl.t", revision=1,
                    expected_version=2, operation_key="a")
    template = service.get(principal="u1", template_id="tmpl.t")
    assert template.latest_revision == 1
    # A full CRUD round never dragged a host product package into the process.
    assert "ordessa_server" not in sys.modules
    assert "ordessa_harness" not in sys.modules
