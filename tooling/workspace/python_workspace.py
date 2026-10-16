"""Validate/install explicitly enumerated same-checkout Python distributions.

No product imports, inferred editable paths, fixture distributions or secret reads.
External dependencies are installed separately; pip check proves their closure.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib


def _safe_directory(project_dir: Path, root: Path, value: str, label: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe {label}: {value}")
    candidate = project_dir / relative
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_dir():
        raise ValueError(f"missing or outside {label}: {value}")
    return resolved


def _valid_package_name(name: str) -> bool:
    return bool(name) and all(part.isidentifier() for part in name.split("."))


def _package_source_paths(project_dir: Path, root: Path, metadata: dict) -> list[Path]:
    setuptools = metadata.get("tool", {}).get("setuptools", {})
    packages = setuptools.get("packages")
    package_dir = setuptools.get("package-dir", {})
    if not isinstance(package_dir, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in package_dir.items()
    ):
        raise ValueError(f"invalid setuptools package-dir mapping: {project_dir}")
    if any(key and not _valid_package_name(key) for key in package_dir):
        raise ValueError(f"invalid setuptools package-dir package name: {project_dir}")

    roots: list[Path] = []
    if isinstance(packages, dict):
        find = packages.get("find")
        if find is None or not isinstance(find, dict):
            raise ValueError(f"unsupported setuptools packages configuration: {project_dir}")
        where = find.get("where", ["src"])
        if not isinstance(where, list) or not where or not all(isinstance(x, str) for x in where):
            raise ValueError(f"invalid setuptools packages.find.where: {project_dir}")
        roots.extend(_safe_directory(project_dir, root, value, "package source") for value in where)
    elif isinstance(packages, list):
        if not packages or not all(
            isinstance(name, str) and _valid_package_name(name) for name in packages
        ):
            raise ValueError(f"invalid explicit setuptools packages list: {project_dir}")
        mappings = sorted(package_dir, key=lambda key: (key.count("."), len(key)), reverse=True)
        for name in packages:
            matches = [key for key in mappings if key == "" or name == key or name.startswith(key + ".")]
            if matches:
                key = matches[0]
                base = _safe_directory(project_dir, root, package_dir[key], "package-dir target")
                suffix = name[len(key):].lstrip(".") if key else name
                package_path = base.joinpath(*suffix.split(".")) if suffix else base
                if not package_path.resolve().is_relative_to(root) or not package_path.is_dir():
                    raise ValueError(f"missing explicit setuptools package: {name} in {project_dir}")
                source_root = base
                for _part in key.split(".") if key else ():
                    source_root = source_root.parent
            else:
                # With no package-dir entry the package is rooted at the project directory.
                package_path = project_dir.joinpath(*name.split("."))
                if not package_path.resolve().is_relative_to(root) or not package_path.is_dir():
                    raise ValueError(f"missing explicit setuptools package: {name} in {project_dir}")
                source_root = project_dir
            roots.append(source_root.resolve())
    elif packages is None:
        # Preserve this helper's existing src-layout default for implicit find mode.
        roots.append(_safe_directory(project_dir, root, "src", "package source"))
    else:
        raise ValueError(f"unsupported setuptools packages configuration: {project_dir}")

    # A package-dir mapping may point packages outside the find.where roots.
    # Convert each mapped package directory back to its import search root.
    for package_name, value in package_dir.items():
        mapped = _safe_directory(project_dir, root, value, "package-dir target")
        package_parts = package_name.split(".") if package_name else ()
        if package_parts and tuple(mapped.parts[-len(package_parts):]) != tuple(package_parts):
            raise ValueError(
                "unsupported setuptools package-dir mapping; mapped directory does not end "
                f"with package name {package_name!r}: {project_dir}"
            )
        source_root = mapped
        for _part in package_parts:
            source_root = source_root.parent
        if not source_root.resolve().is_relative_to(root):
            raise ValueError(f"package-dir import root escapes workspace: {project_dir}")
        roots.append(source_root.resolve())

    unique: list[Path] = []
    seen: set[Path] = set()
    for source in roots:
        resolved = source.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def _validated_workspace(root: Path) -> tuple[list[Path], list[Path]]:
    root = root.resolve()
    data = json.loads((root / "python-workspace.json").read_text())
    if data.get("schema_version") != 1 or not data.get("projects"):
        raise ValueError("invalid or empty Python workspace")
    declared = set()
    distributions = set()
    result: list[Path] = []
    all_source_paths: list[Path] = []
    for item in data["projects"]:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe workspace path")
        directory = root / relative
        if not directory.resolve().is_relative_to(root) or relative.as_posix() in declared:
            raise ValueError("outside or duplicate workspace path")
        metadata = tomllib.loads((directory / "pyproject.toml").read_text())
        project = metadata["project"]
        if any(project[k] != item[k] for k in ("version",)) or project["name"] != item["distribution"]:
            raise ValueError(f"workspace metadata drift: {relative}")
        if project["name"] in distributions:
            raise ValueError("duplicate Python distribution")
        project_sources = _package_source_paths(directory, root, metadata)
        declared.add(relative.as_posix())
        distributions.add(project["name"])
        result.append(directory)
        all_source_paths.extend(project_sources)
    actual = {p.parent.relative_to(root).as_posix()
              for group in ("packages", "plugins", "apps", "products")
              for p in (root / group).rglob("pyproject.toml")
              if not any(x in {"tests", "fixtures", "examples", "node_modules", "dist"}
                         for x in p.relative_to(root).parts)}
    if actual != declared:
        raise ValueError(f"workspace enumeration mismatch: {sorted(actual ^ declared)}")
    unique_source_paths: list[Path] = []
    seen_source_paths: set[Path] = set()
    for path in all_source_paths:
        if path not in seen_source_paths:
            seen_source_paths.add(path)
            unique_source_paths.append(path)
    return result, unique_source_paths


def projects(root: Path) -> list[Path]:
    """Validate this workspace's supported setuptools layouts and return projects.

    This validates the workspace's find.where or explicit package-list metadata;
    it is not a general interpreter for every setuptools configuration.
    """
    return _validated_workspace(root)[0]


def source_paths(root: Path) -> list[Path]:
    """Return source roots derived from registered setuptools metadata.

    These are filesystem import roots, not a runtime namespace-composition
    mechanism. Only suffix-aligned package-dir mappings can be converted into
    ordinary roots; arbitrary package aliases are rejected. Even a valid root
    list cannot merge a regular parent package spanning multiple roots through
    PYTHONPATH alone.
    """
    return _validated_workspace(root)[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--source-paths", action="store_true",
                        help="print metadata-derived source roots joined with the platform path separator")
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    directories, roots = _validated_workspace(args.root)
    if args.source_paths:
        print(os.pathsep.join(str(path) for path in roots), flush=True)
    else:
        print(f"Validated {len(directories)} same-source Python distributions", flush=True)
    if args.install:
        command = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                   "--no-deps", "--no-build-isolation"]
        for directory in directories:
            command.extend(["-e", str(directory)])
        return subprocess.call(command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
