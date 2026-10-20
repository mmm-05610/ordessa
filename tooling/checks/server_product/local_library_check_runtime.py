"""Compose the single fixed Local Library check with its original Work guard.

This case helper installs nothing and starts nothing. Its pins cover the
prepared runner/runtime, not the repository files the approved Work may edit.
It grants no Work or Unit authority and does not provide an OS sandbox.
"""
from collections.abc import Mapping
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shlex

from ordessa_server.composition.unit_file_callback_approval import UnitFileCallbackApproval
from ordessa_units.api import UnitApiRefused


def catalog_runtime_digest(root):
    """Hash exact prepared runtime files and link targets, including additions."""
    root = Path(root)
    inventory = []
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            inventory.append((relative, 'link', str(path.readlink())))
        elif path.is_file():
            inventory.append((relative, 'file', hashlib.sha256(path.read_bytes()).hexdigest()))
    return hashlib.sha256(json.dumps(inventory, separators=(',', ':')).encode()).hexdigest()


def fixed_catalog_check(*, python_executable, runner, project_root, pinned_files,
                        runtime_tree_digest, allowed_paths, scope_guard):
    """Return exact command, guarded callback factory and pre-dispatch verifier."""
    python, script, project = map(Path, (python_executable, runner, project_root))
    if (not all(path.is_absolute() and '..' not in path.parts for path in (python, script, project))
            or script.resolve() != script or project.resolve() != project
            or any(part.is_symlink() for path in (script, project) for part in (path, *path.parents))
            or not project.is_dir() or not callable(scope_guard)
            or not isinstance(pinned_files, Mapping) or not pinned_files):
        raise UnitApiRefused('Prepared catalog runtime and original Work scope required')
    pins = tuple((Path(name), digest) for name, digest in pinned_files.items())
    if any(not path.is_absolute() or path.resolve() != path or type(digest) is not str
           or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest)
           for path, digest in pins):
        raise UnitApiRefused('Exact prepared check artifact pins required')
    env_target = Path('/usr/bin/env').resolve()
    if not {script, env_target, python.resolve(), python.parent.parent / 'pyvenv.cfg'} <= {path for path, _ in pins}:
        raise UnitApiRefused('Runner, env, actual interpreter and isolated runtime configuration must be pinned')
    resolved_python = python.resolve()
    runtime_root = python.parent.parent
    paths = tuple(allowed_paths)
    command = shlex.join(('/usr/bin/env', '-i', 'PATH=/usr/bin:/bin', str(python), '-I', '-B',
                         str(script), '--project-root', str(project)))

    def verify():
        if (python.resolve() != resolved_python or Path('/usr/bin/env').resolve() != env_target
                or catalog_runtime_digest(runtime_root) != runtime_tree_digest):
            raise UnitApiRefused('Prepared check interpreter selection changed')
        for path, digest in pins:
            if (not path.is_file() or path.resolve() != path
                    or any(part.is_symlink() for part in (path, *path.parents))
                    or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
                raise UnitApiRefused('Prepared check artifact changed')
        return True

    @contextmanager
    def current_scope(**request):
        verify()
        with scope_guard(**request):
            yield

    def callback_factory(**owner):
        verify()
        return UnitFileCallbackApproval(**owner, allowed_paths=paths,
            scope_guard=current_scope, approved_check_command=command)

    verify()
    return command, callback_factory, verify
