#!/usr/bin/env python3
"""Report forbidden Python dependency edges from source and package metadata.

The scanner derives import roots from each project's setuptools package
discovery configuration. It deliberately does not infer a Python package from
the spelling of a distribution name or from a directory prefix.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import re
import sys
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


# The default Python product is a distribution under apps/server/deployment.
# products/ is retired as a Python project root and may contain only inert
# historical/build residue. It must not become a second source tree again.
LAYERS = ("packages", "plugins", "apps")
RETIRED_PYTHON_ROOT = "products"
REQUIRED_PRODUCT_METADATA = Path("apps/server/deployment/default-product/pyproject.toml")
BOUNDARY_CONFIG = Path(__file__).with_name("package-boundaries.json")
PYTHON_WORKSPACE_MANIFEST = "python-workspace.json"


class ScanError(Exception):
    """An incomplete scan condition; callers must not treat it as clean."""


@dataclass(frozen=True)
class Project:
    name: str
    layer: str
    metadata_path: Path
    package_dirs: tuple[tuple[str, Path], ...]
    python_files: tuple[Path, ...]
    dependencies: tuple[str, ...]


@dataclass(frozen=True)
class Finding:
    rule: str
    mechanism: str
    source_file: str
    line: int
    source_project: str
    source_layer: str
    imported_module: str
    target_project: str
    target_layer: str
    detail: str


@dataclass(frozen=True)
class DeniedEdge:
    rule: str
    sources: tuple[str, ...]
    targets: tuple[str, ...]


@dataclass(frozen=True)
class BoundaryConfig:
    denied_edges: tuple[DeniedEdge, ...]
    retired_paths: tuple[str, ...]
    retired_python_modules: tuple[str, ...]
    retired_distributions: tuple[str, ...]


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _dist_key(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _relative_pattern(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise ScanError(f"invalid {label}: expected a non-empty repository-relative POSIX path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ScanError(f"invalid {label}: {value!r}")
    return value


def _string_list(value: Any, label: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty) or not all(isinstance(item, str) and item for item in value):
        raise ScanError(f"invalid {label}: expected {'an' if allow_empty else 'a non-empty'} array of strings")
    return tuple(value)


def _python_source_files(directory: Path) -> set[Path]:
    return {path.resolve() for suffix in ("*.py", "*.pyi")
            for path in directory.rglob(suffix) if path.is_file()}


def _load_boundary_config(config_path: Path = BOUNDARY_CONFIG) -> BoundaryConfig:
    """Load the shared, scanner-owned policy; fixture roots cannot shadow it."""
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ScanError(f"cannot read boundary policy {config_path}: {exc}") from exc
    if (not isinstance(raw, dict) or type(raw.get("schema_version")) is not int
            or raw["schema_version"] != 1):
        raise ScanError(f"unsupported boundary policy schema in {config_path}")
    expected = {"schema_version", "denied_edges", "retired_paths", "retired_python_modules", "retired_distributions"}
    if not expected.issubset(raw) or set(raw) - expected - {"standard"}:
        raise ScanError(f"boundary policy fields do not match schema_version 1 in {config_path}")
    if "standard" in raw and (not isinstance(raw["standard"], str) or not raw["standard"].strip()):
        raise ScanError(f"invalid boundary policy standard reference in {config_path}")
    raw_edges = raw.get("denied_edges")
    if not isinstance(raw_edges, list) or not raw_edges:
        raise ScanError(f"invalid denied_edges in {config_path}: expected a non-empty array")
    edges: list[DeniedEdge] = []
    for index, item in enumerate(raw_edges):
        if not isinstance(item, dict) or set(item) != {"rule", "from", "to"}:
            raise ScanError(f"invalid denied_edges[{index}] in {config_path}")
        rule = item.get("rule")
        if not isinstance(rule, str) or not rule.strip():
            raise ScanError(f"invalid denied_edges[{index}].rule in {config_path}")
        sources = tuple(_relative_pattern(pattern, f"denied_edges[{index}].from")
                        for pattern in _string_list(item.get("from"), f"denied_edges[{index}].from"))
        targets = tuple(_relative_pattern(pattern, f"denied_edges[{index}].to")
                        for pattern in _string_list(item.get("to"), f"denied_edges[{index}].to"))
        edges.append(DeniedEdge(rule, sources, targets))
    retired_path_values = _string_list(raw.get("retired_paths"), "retired_paths")
    if any(any(character in path for character in "*?[]") for path in retired_path_values):
        raise ScanError(f"retired_paths must be literal prefixes in {config_path}")
    retired_paths = tuple(_relative_pattern(path, "retired_paths entry") for path in retired_path_values)
    retired_modules = _string_list(raw.get("retired_python_modules"), "retired_python_modules", allow_empty=True)
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", name)
           for name in retired_modules):
        raise ScanError(f"invalid retired_python_modules in {config_path}")
    retired_distributions = tuple(_dist_key(name) for name in
                                  _string_list(raw.get("retired_distributions"), "retired_distributions", allow_empty=True))
    if any(not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name) for name in retired_distributions):
        raise ScanError(f"invalid retired_distributions in {config_path}")
    return BoundaryConfig(tuple(edges), retired_paths, tuple(retired_modules), retired_distributions)


def _configured_rules(config: BoundaryConfig, source_path: str, target_path: str) -> tuple[str, ...]:
    return tuple(edge.rule for edge in config.denied_edges
                 if any(fnmatch.fnmatchcase(source_path, pattern) for pattern in edge.sources)
                 and any(fnmatch.fnmatchcase(target_path, pattern) for pattern in edge.targets))


def _matches(package: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(package, pattern) for pattern in patterns)


def _package_layout(metadata_path: Path, data: dict[str, Any]) -> tuple[tuple[tuple[str, Path], ...], tuple[Path, ...]]:
    """Read setuptools package roots and discover concrete import packages."""
    tool = data.get("tool", {})
    setuptools = tool.get("setuptools", {})
    packages_config = setuptools.get("packages", {})
    find = packages_config.get("find") if isinstance(packages_config, dict) else None
    if not isinstance(find, dict):
        explicit = setuptools.get("packages")
        if isinstance(explicit, list) and all(isinstance(item, str) for item in explicit):
            package_dir = setuptools.get("package-dir", {})
            if not isinstance(package_dir, dict):
                raise ScanError(f"unsupported package-dir in {metadata_path}")
            mapping: list[tuple[str, Path]] = []
            files: list[Path] = []
            for package in explicit:
                prefixes = [key for key in package_dir if key == "" or package == key or package.startswith(key + ".")]
                prefix = max(prefixes, key=len) if prefixes else ""
                base_value = package_dir.get(prefix, ".")
                base = (metadata_path.parent / base_value).resolve()
                suffix = package[len(prefix):].lstrip(".") if prefix else package
                directory = base.joinpath(*suffix.split(".")) if suffix else base
                init = directory / "__init__.py"
                stub_init = directory / "__init__.pyi"
                if not init.is_file() and not stub_init.is_file():
                    raise ScanError(f"declared package {package!r} has no __init__.py or __init__.pyi: {init}")
                mapping.append((package, directory))
                files.extend(_python_source_files(directory))
            if not mapping:
                raise ScanError(f"no Python package roots declared by {metadata_path}")
            return tuple(mapping), tuple(sorted(set(files)))
        raise ScanError(f"unsupported or missing [tool.setuptools.packages.find] in {metadata_path}")

    where_value = find.get("where", ["."])
    if isinstance(where_value, str):
        where_value = [where_value]
    if not isinstance(where_value, list) or not where_value or not all(isinstance(item, str) for item in where_value):
        raise ScanError(f"invalid setuptools find.where in {metadata_path}")
    include = find.get("include", ["*"])
    exclude = find.get("exclude", [])
    if isinstance(include, str):
        include = [include]
    if isinstance(exclude, str):
        exclude = [exclude]
    if not all(isinstance(item, str) for item in [*include, *exclude]):
        raise ScanError(f"invalid setuptools find include/exclude in {metadata_path}")

    package_dir = setuptools.get("package-dir", {})
    if not isinstance(package_dir, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in package_dir.items()):
        raise ScanError(f"invalid setuptools package-dir in {metadata_path}")

    packages: dict[str, Path] = {}
    source_files: set[Path] = set()
    for where in where_value:
        base = (metadata_path.parent / where).resolve()
        if not base.is_dir():
            raise ScanError(f"setuptools package source root is missing: {base}")
        for init in (*base.rglob("__init__.py"), *base.rglob("__init__.pyi")):
            directory = init.parent
            try:
                relative = directory.relative_to(base)
            except ValueError:
                continue
            package = ".".join(relative.parts)
            if not package or not _matches(package, include) or _matches(package, exclude):
                continue
            packages[package] = directory.resolve()
            source_files.update(_python_source_files(directory))

    # Respect explicit package-dir entries when they point at package roots
    # outside the configured find.where tree. These mappings are exact names.
    for package, relative in package_dir.items():
        if not package:
            continue
        directory = (metadata_path.parent / relative).resolve()
        if (directory / "__init__.py").is_file() or (directory / "__init__.pyi").is_file():
            packages[package] = directory
            source_files.update(_python_source_files(directory))

    if not packages:
        raise ScanError(f"setuptools metadata resolved no Python packages: {metadata_path}")
    return tuple(sorted(packages.items())), tuple(sorted(source_files))


def _dependencies(data: dict[str, Any], metadata_path: Path) -> tuple[str, ...]:
    project = data.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("name"), str) or not project["name"].strip():
        raise ScanError(f"missing [project].name in {metadata_path}")
    raw: list[Any] = project.get("dependencies", [])
    optional = project.get("optional-dependencies", {})
    if not isinstance(raw, list) or not isinstance(optional, dict):
        raise ScanError(f"invalid dependency metadata in {metadata_path}")
    for group, entries in optional.items():
        if not isinstance(entries, list):
            raise ScanError(f"invalid optional dependency group {group!r} in {metadata_path}")
        raw.extend(entries)
    result = []
    for requirement in raw:
        if not isinstance(requirement, str):
            raise ScanError(f"non-string dependency in {metadata_path}")
        match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
        if match:
            result.append(_dist_key(match.group(1)))
        elif requirement.strip():
            raise ScanError(f"cannot parse dependency {requirement!r} in {metadata_path}")
    return tuple(result)


def _within_prefix(relative_path: str, prefix: str) -> bool:
    return relative_path == prefix or relative_path.startswith(prefix.rstrip("/") + "/")


def _check_retired_owners(root: Path, config: BoundaryConfig) -> None:
    """Reject revived source and registration before deriving any active owners."""
    active_suffixes = {".py", ".pyi"}
    for prefix in config.retired_paths:
        retired = root / prefix
        current = root
        retired_stat = None
        for component in prefix.split("/"):
            current = current / component
            try:
                component_stat = current.lstat()
            except (FileNotFoundError, NotADirectoryError):
                break
            if current.is_symlink():
                raise ScanError(f"retired Python path is linked: {current.relative_to(root).as_posix()}")
            retired_stat = component_stat
        if retired_stat is not None:
            candidates = [retired]
            if retired.is_dir():
                candidates.extend(sorted(retired.rglob("*")))
            for candidate in candidates:
                if candidate.is_symlink():
                    raise ScanError(f"retired Python path contains a symlink: {candidate.relative_to(root).as_posix()}")
                if candidate.is_file() and (candidate.name == "pyproject.toml" or candidate.suffix in active_suffixes):
                    raise ScanError(f"retired Python source or metadata remains: {_relative(candidate, root)}")

    workspace_manifest = root / PYTHON_WORKSPACE_MANIFEST
    try:
        workspace_stat = workspace_manifest.lstat()
    except FileNotFoundError:
        workspace_stat = None
    if workspace_stat is not None:
        if workspace_manifest.is_symlink():
            raise ScanError(f"Python workspace manifest is linked: {workspace_manifest}")
        try:
            workspace = json.loads(workspace_manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ScanError(f"cannot read Python workspace manifest {workspace_manifest}: {exc}") from exc
        if not isinstance(workspace, dict) or workspace.get("schema_version") != 1:
            raise ScanError(f"unsupported Python workspace manifest schema in {workspace_manifest}")
        entries = workspace.get("projects") if isinstance(workspace, dict) else None
        if not isinstance(entries, list):
            raise ScanError(f"invalid projects array in Python workspace manifest {workspace_manifest}")
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise ScanError(f"invalid projects[{index}] path in Python workspace manifest {workspace_manifest}")
            workspace_path = _relative_pattern(entry["path"], f"Python workspace projects[{index}].path")
            for prefix in config.retired_paths:
                if _within_prefix(workspace_path, prefix):
                    raise ScanError(f"retired Python workspace entry remains: {workspace_path}")
            distribution = entry.get("distribution")
            if isinstance(distribution, str) and _dist_key(distribution) in config.retired_distributions:
                raise ScanError(f"retired Python workspace distribution remains: {distribution}")


def _load_projects(root: Path, config: BoundaryConfig) -> list[Project]:
    projects: list[Project] = []
    _check_retired_owners(root, config)
    retired_root = root / RETIRED_PYTHON_ROOT
    if retired_root.is_symlink() or (retired_root.exists() and not retired_root.is_dir()):
        raise ScanError(f"retired Python root is not an ordinary directory: {retired_root}")
    if retired_root.is_dir():
        entries = tuple(retired_root.rglob("*"))
        links = sorted(path for path in entries if path.is_symlink())
        if links:
            raise ScanError(f"retired products root contains a symlink: {links[0]}")
        stale_source = sorted(path for path in entries if path.is_file() and
                              (path.name == "pyproject.toml" or path.suffix in {".py", ".pyi"}))
        if stale_source:
            raise ScanError(f"retired products Python source or metadata remains: {stale_source[0]}")
    for layer in LAYERS:
        layer_root = root / layer
        if not layer_root.is_dir():
            raise ScanError(f"required scan root is missing: {layer_root}")
        if layer == "apps":
            product_metadata = root / REQUIRED_PRODUCT_METADATA
            if product_metadata.is_symlink() or not product_metadata.is_file():
                raise ScanError(f"required default-product metadata is missing or linked: {product_metadata}")
        metadata_files = sorted(layer_root.rglob("pyproject.toml"))
        if not metadata_files:
            raise ScanError(f"required scan root has no pyproject.toml: {layer_root}")
        found = 0
        for metadata_path in metadata_files:
            try:
                data = tomllib.loads(metadata_path.read_text(encoding="utf-8"))
                project_data = data.get("project")
                if not isinstance(project_data, dict) or not isinstance(project_data.get("name"), str):
                    raise ScanError(f"missing [project].name in {metadata_path}")
                if _dist_key(project_data["name"]) in config.retired_distributions:
                    raise ScanError(f"retired Python distribution remains at {_relative(metadata_path, root)}: {project_data['name']}")
                packages, files = _package_layout(metadata_path, data)
                dependencies = _dependencies(data, metadata_path)
            except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
                raise ScanError(f"cannot read package metadata {metadata_path}: {exc}") from exc
            projects.append(Project(
                name=project_data["name"],
                layer=layer,
                metadata_path=metadata_path.resolve(),
                package_dirs=packages,
                python_files=files,
                dependencies=dependencies,
            ))
            found += 1
        if not found:
            raise ScanError(f"required scan root has no resolvable Python packages: {layer_root}")
    return projects


def _rule(source_layer: str, target_layer: str) -> str | None:
    if source_layer in {"packages", "plugins"} and target_layer in {"apps", "products"}:
        return "packages_and_plugins_must_not_import_apps"
    if source_layer == "packages" and target_layer == "plugins":
        return "public_packages_must_not_import_concrete_plugins"
    return None


def _module_map(projects: list[Project]) -> dict[str, Project]:
    result: dict[str, Project] = {}
    for project in projects:
        for package, _ in project.package_dirs:
            prior = result.get(package)
            if prior is not None and prior.metadata_path != project.metadata_path:
                raise ScanError(f"ambiguous import package {package!r}: {prior.metadata_path} and {project.metadata_path}")
            result[package] = project
    return result


def _package_for_module(module: str, module_map: dict[str, Project]) -> tuple[str, Path, Project] | None:
    candidates = [name for name in module_map if module == name or module.startswith(name + ".")]
    if not candidates:
        return None
    longest = max(len(name) for name in candidates)
    owners = {name: module_map[name] for name in candidates if len(name) == longest}
    if len(owners) != 1:
        raise ScanError(f"ambiguous import owner for {module!r}")
    package = next(iter(owners))
    project = owners[package]
    directory = dict(project.package_dirs)[package]
    return package, directory, project


def _owner_for_module(module: str, module_map: dict[str, Project]) -> Project | None:
    resolved = _package_for_module(module, module_map)
    return resolved[2] if resolved else None


def _module_target_path(module: str, module_map: dict[str, Project], root: Path) -> tuple[Project | None, str | None]:
    resolved = _package_for_module(module, module_map)
    if resolved is None:
        return None, None
    package, directory, project = resolved
    suffix = module[len(package):].lstrip(".")
    target = directory.joinpath(*suffix.split(".")) if suffix else directory
    if target.is_dir() and ((target / "__init__.py").is_file() or (target / "__init__.pyi").is_file()):
        target = target / ("__init__.py" if (target / "__init__.py").is_file() else "__init__.pyi")
    elif target.with_suffix(".py").is_file():
        target = target.with_suffix(".py")
    elif target.with_suffix(".pyi").is_file():
        target = target.with_suffix(".pyi")
    return project, target.resolve().relative_to(root.resolve()).as_posix()


def _source_module(file: Path, project: Project) -> tuple[str, bool]:
    matches = [(name, directory) for name, directory in project.package_dirs
               if file in {directory / "__init__.py", directory / "__init__.pyi"} or directory in file.parents]
    if not matches:
        raise ScanError(f"Python source is not under a declared package root: {file}")
    name, directory = max(matches, key=lambda item: len(item[1].parts))
    relative = file.relative_to(directory)
    is_init = relative.name in {"__init__.py", "__init__.pyi"}
    parts = list(relative.parts[:-1] if is_init else (*relative.parts[:-1], relative.stem))
    module = ".".join([name, *parts]) if parts else name
    return module, is_init


def _resolve_relative(name: str, package: str, level: int) -> str | None:
    if level < 1:
        return name
    package_parts = package.split(".") if package else []
    keep = len(package_parts) - level + 1
    if keep < 0:
        return None
    prefix = package_parts[:keep]
    suffix = name.split(".") if name else []
    return ".".join([*prefix, *suffix])


def _constant_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _constant_string(node.left), _constant_string(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _package_expression(node: ast.AST | None, source_package: str) -> str | None:
    value = _constant_string(node)
    if value is not None:
        return source_package if value == "__package__" else value
    if isinstance(node, ast.Name) and node.id == "__package__":
        return source_package
    return None


class _ImportCollector(ast.NodeVisitor):
    def __init__(self, module_name: str, is_init: bool) -> None:
        self.module_name = module_name
        self.package_name = module_name if is_init else module_name.rpartition(".")[0]
        self.importlib_aliases: set[str] = {"importlib"}
        self.function_aliases: set[str] = set()
        self.imports: list[tuple[str, int, str, str]] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "importlib":
                self.importlib_aliases.add(alias.asname or "importlib")
            self.imports.append((alias.name, node.lineno, "import", f"import {alias.name}"))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "importlib" and node.level == 0:
            for alias in node.names:
                if alias.name == "import_module":
                    self.function_aliases.add(alias.asname or alias.name)
        raw = node.module or ""
        target = _resolve_relative(raw, self.package_name, node.level)
        if target:
            self.imports.append((target, node.lineno, "from", f"from {'.' * node.level}{raw} import ..."))
        # Imported members can name concrete child modules, including namespace
        # packages whose parent has no __init__.py. Resolve them as separate
        # candidates; ordinary attributes simply have no concrete source owner.
        for alias in node.names:
            if alias.name == "*":
                continue
            member = f"{target}.{alias.name}" if target else _resolve_relative(alias.name, self.package_name, node.level)
            if member:
                self.imports.append((member, node.lineno, "from-member",
                                     f"from {'.' * node.level}{raw} import {alias.name}"))

    def visit_Call(self, node: ast.Call) -> None:
        call_kind: str | None = None
        if isinstance(node.func, ast.Name):
            if node.func.id == "__import__":
                call_kind = "__import__"
            elif node.func.id in self.function_aliases:
                call_kind = "importlib.import_module"
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "import_module" and isinstance(node.func.value, ast.Name) and node.func.value.id in self.importlib_aliases:
            call_kind = "importlib.import_module"

        if call_kind:
            name = _constant_string(node.args[0]) if node.args else None
            if name is not None:
                package_arg: str | None = None
                if call_kind == "importlib.import_module":
                    if len(node.args) > 1:
                        package_arg = _package_expression(node.args[1], self.package_name)
                    for keyword in node.keywords:
                        if keyword.arg == "package":
                            package_arg = _package_expression(keyword.value, self.package_name)
                    if name.startswith("."):
                        level = len(name) - len(name.lstrip("."))
                        target = _resolve_relative(name[level:], package_arg, level) if package_arg else None
                    else:
                        target = name
                else:
                    level_node = node.args[4] if len(node.args) > 4 else None
                    for keyword in node.keywords:
                        if keyword.arg == "level":
                            level_node = keyword.value
                    level = level_node.value if isinstance(level_node, ast.Constant) and isinstance(level_node.value, int) else 0
                    if level > 0:
                        target = _resolve_relative(name, self.package_name, level)
                    else:
                        target = name
                if target:
                    self.imports.append((target, node.lineno, call_kind, f"{call_kind}({name!r})"))
        self.generic_visit(node)


def _finding(source: Project, source_file: Path, line: int, mechanism: str, expression: str,
             imported: str, target: Project, target_path: str, root: Path,
             config: BoundaryConfig) -> list[Finding]:
    source_path = _relative(source_file, root)
    rules = []
    coarse = _rule(source.layer, target.layer)
    if coarse:
        rules.append(coarse)
    rules.extend(rule for rule in _configured_rules(config, source_path, target_path) if rule not in rules)
    return [Finding(
        rule=rule,
        mechanism=mechanism,
        source_file=source_path,
        line=line,
        source_project=source.name,
        source_layer=source.layer,
        imported_module=imported,
        target_project=target.name,
        target_layer=target.layer,
        detail=expression,
    ) for rule in rules]


def _is_retired_module(module: str, retired_modules: tuple[str, ...]) -> str | None:
    return next((retired for retired in retired_modules
                 if module == retired or module.startswith(retired + ".")), None)


def scan_root(root: Path, *, config_path: Path = BOUNDARY_CONFIG) -> tuple[list[Finding], list[str]]:
    root = root.resolve()
    errors: list[str] = []
    findings: list[Finding] = []
    config = _load_boundary_config(config_path)
    projects = _load_projects(root, config)
    module_map = _module_map(projects)
    dist_map: dict[str, Project] = {}
    for project in projects:
        key = _dist_key(project.name)
        if key in dist_map and dist_map[key].metadata_path != project.metadata_path:
            raise ScanError(f"ambiguous distribution name {project.name!r}")
        dist_map[key] = project

    for project in projects:
        for dependency in project.dependencies:
            retired = next((name for name in config.retired_distributions if dependency == name), None)
            if retired:
                errors.append(f"{_relative(project.metadata_path, root)}: retired Python distribution dependency remains: {retired}")
                continue
            target = dist_map.get(dependency)
            if target is None:
                continue
            findings.extend(_finding(project, project.metadata_path, 0, "metadata-dependency", dependency,
                                     target.name, target, _relative(target.metadata_path, root), root, config))

    for project in projects:
        for source_file in project.python_files:
            try:
                source = source_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(source_file))
                module_name, is_init = _source_module(source_file, project)
            except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
                errors.append(f"{_relative(source_file, root)}: {type(exc).__name__}: {exc}")
                continue
            collector = _ImportCollector(module_name, is_init)
            collector.visit(tree)
            for imported, line, mechanism, expression in collector.imports:
                retired = _is_retired_module(imported, config.retired_python_modules)
                if retired:
                    errors.append(f"{_relative(source_file, root)}:{line}: retired Python module import remains: {imported} (root {retired})")
                    continue
                try:
                    target, target_path = _module_target_path(imported, module_map, root)
                except ScanError as exc:
                    errors.append(f"{_relative(source_file, root)}:{line}: {exc}")
                    continue
                if target is None:
                    continue
                if mechanism == "from-member" and not (root / (target_path or "")).exists():
                    continue
                findings.extend(_finding(project, source_file, line, mechanism, expression,
                                         imported, target, target_path or "", root, config))

    findings.sort(key=lambda item: (item.source_file, item.line, item.mechanism, item.imported_module))
    errors = sorted(set(errors))
    return findings, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2], help="repository root (default: this script's repository)")
    args = parser.parse_args(argv)
    try:
        findings, errors = scan_root(args.root)
    except (ScanError, OSError) as exc:
        report = {"root": str(args.root.resolve()), "ok": False, "violations": [], "errors": [str(exc)]}
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2
    report = {
        "root": str(args.root.resolve()),
        "ok": not findings and not errors,
        "violations": [asdict(item) for item in findings],
        "errors": errors,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if errors else (1 if findings else 0)


if __name__ == "__main__":
    raise SystemExit(main())
