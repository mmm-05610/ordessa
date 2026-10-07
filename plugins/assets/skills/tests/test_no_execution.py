"""AC-4 / INV-5: nothing in the Skills path executes a skill's bundled script.

Ported from `plugins/assets/tests/test_no_execution.py` @ 752f148b1b.
The AST sweep now scans `src/ordessa_skills`; the store-backed test keeps
every legacy assertion and runs against the real
`ordessa_skills.library.store.SkillRevisionStore` (T03 slice B replaced the
interim test-side helper this slice retired). The legacy service-backed
preview test asserted that the row returned for `scripts/run.sh` carries the
script flag and the exact text; that same assertion is exercised at this
layer through `validate_skill_directory` + `file_preview`; the transfer and
preview mechanics themselves landed with this slice in
`library/import_transfer.py` and `library/diff.py`.
"""
from __future__ import annotations

import ast
import hashlib
import stat
from pathlib import Path

from ordessa_skills.library.store import SkillRevisionStore

SRC = Path(__file__).resolve().parents[1] / "src" / "ordessa_skills"

FORBIDDEN_CALLS = {"system", "popen"}
FORBIDDEN_IMPORTS = {"subprocess", "pty", "multiprocessing"}
FORBIDDEN_NAMES = {"exec", "eval", "compile"}


def _ast_violations():
    violations = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name.split(".")[0] in FORBIDDEN_IMPORTS
                       for alias in node.names):
                    violations.append(f"{path.name}:{node.lineno} import")
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] in FORBIDDEN_IMPORTS:
                    violations.append(f"{path.name}:{node.lineno} from-import")
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in FORBIDDEN_NAMES:
                    violations.append(f"{path.name}:{node.lineno} {func.id}()")
                if isinstance(func, ast.Attribute) and func.attr in FORBIDDEN_CALLS:
                    violations.append(f"{path.name}:{node.lineno} .{func.attr}()")
    return violations


def test_no_execution_primitives_anywhere_in_the_domain():
    assert _ast_violations() == []


def test_scripts_are_copied_as_bytes_and_never_run(tmp_path):
    source = tmp_path / "src"
    (source / "scripts").mkdir(parents=True)
    (source / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: A demo.\n---\nbody\n")
    script = source / "scripts" / "run.sh"
    script.write_text("#!/bin/sh\nexit 42\n")
    script.chmod(0o755)

    store = SkillRevisionStore(tmp_path / "assets")
    facts = store.install(source, asset_id="demo-skill", revision=1)
    stored = store.revision_dir("demo-skill", 1) / "scripts" / "run.sh"
    # The bytes are preserved verbatim; the executable bit is not.
    assert stored.read_bytes() == script.read_bytes()
    assert not stored.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    assert facts["scripts"] == ("scripts/run.sh",)
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == \
        hashlib.sha256(script.read_bytes()).hexdigest()


def test_preview_returns_script_text_with_the_script_flag(tmp_path):
    from ordessa_skills.formats.agent_skills.validator import (
        file_preview, validate_skill_directory)

    source = tmp_path / "skill"
    (source / "scripts").mkdir(parents=True)
    files = {
        "SKILL.md": b"---\nname: demo-skill\ndescription: A demo.\n---\nbody\n",
        "scripts/run.sh": b"#!/bin/sh\nexit 42\n",
    }
    for path, data in files.items():
        target = source / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    validated = validate_skill_directory(source)
    entry = [item for item in validated.entries if item.relative == "scripts/run.sh"][0]
    script_row = file_preview(entry, source)
    assert script_row["script"] is True
    assert script_row["text"] == "#!/bin/sh\nexit 42\n"
