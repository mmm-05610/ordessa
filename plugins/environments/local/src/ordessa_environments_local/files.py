"""Bounded local file area for one environment handle.

The area is the environment's own working space. It is deliberately **not** the
user's project directory: ``release`` must leave the project and any shared
resource untouched, and a path that escapes the area root is refused rather than
silently normalized.
"""
from __future__ import annotations

import os

from ordessa_environments import EnvironmentRefused


class LocalFileArea:
    """A real directory tree rooted at one absolute path."""

    __slots__ = ("_root",)

    def __init__(self, root: str):
        if not isinstance(root, str) or not root or not os.path.isabs(root):
            raise EnvironmentRefused("file area root must be an absolute path")
        self._root = os.path.normpath(root)

    def root(self) -> str:
        return self._root

    def path(self, relative: str) -> str:
        if not isinstance(relative, str) or not relative:
            raise EnvironmentRefused("file area path must be a non-empty relative string")
        if os.path.isabs(relative):
            raise EnvironmentRefused("file area path must be relative to the area root")
        if "\x00" in relative:
            raise EnvironmentRefused("file area path must not contain NUL")
        resolved = os.path.normpath(os.path.join(self._root, relative))
        if resolved != self._root and not resolved.startswith(self._root + os.sep):
            raise EnvironmentRefused("file area path escapes the area root")
        # Lexical containment alone lets an existing symlink redirect reads or
        # directory creation outside the area. Compare physical destinations,
        # allowing the configured root itself to be an alias. isolation=none
        # does not claim protection against concurrent filesystem mutation.
        physical_root = os.path.realpath(self._root)
        physical_target = os.path.realpath(resolved)
        if os.path.commonpath((physical_root, physical_target)) != physical_root:
            raise EnvironmentRefused("file area path escapes the area root via a symlink")
        return resolved

    def ensure(self, relative: str) -> str:
        target = self.path(relative)
        try:
            os.makedirs(target, exist_ok=True)
        except OSError as error:
            raise EnvironmentRefused(f"file area directory could not be created: {error}") from error
        return target

    def list(self) -> tuple[str, ...]:
        if not os.path.isdir(self._root):
            return ()
        found: list[str] = []
        for directory, dirnames, filenames in os.walk(self._root):
            dirnames.sort()
            for name in sorted(filenames):
                absolute = os.path.join(directory, name)
                found.append(os.path.relpath(absolute, self._root))
        return tuple(found)

    def exists(self, relative: str) -> bool:
        return os.path.exists(self.path(relative))

    def read_text(self, relative: str) -> str:
        target = self.path(relative)
        with open(target, 'r', encoding='utf-8') as stream:
            return stream.read(1024 * 1024 + 1)

    def write_text(self, relative: str, content: str) -> None:
        if not isinstance(content, str) or len(content.encode('utf-8')) > 1024 * 1024:
            raise EnvironmentRefused('file callback content exceeds bounded UTF-8 limit')
        target = self.path(relative)
        with open(target, 'w', encoding='utf-8') as stream:
            stream.write(content)

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"<LocalFileArea {self._root}>"


__all__ = ["LocalFileArea"]
