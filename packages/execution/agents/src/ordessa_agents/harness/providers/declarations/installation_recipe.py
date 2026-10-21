"""Explicit own build/deployment recipe facts; no capture, discovery or writes; explicit build paths are checked on demand."""
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

@dataclass(frozen=True)
class InstallationRecipe:
    owner_id: str
    builder: Path
    npm_root: Path | None
    facts: Mapping[str, Any]
    requires_binary: bool = False
    binary_environment_key: str | None = None
    binary_output_relative: str | None = None
    binary_missing_message: str | None = None

    def __getattr__(self, name):
        try:
            return self.facts[name]
        except KeyError:
            raise AttributeError(name) from None


@dataclass(frozen=True)
class BuildRecipeFiles:
    """Caller-supplied source/build inputs, never inferred from provider location."""
    owner_id: str
    builder: Path
    npm_root: Path | None

    def require(self, *, owner_id: str, requires_npm: bool):
        if self.owner_id != owner_id:
            raise ValueError("INSTALLATION_BUILD_OWNER_MISMATCH")
        if not isinstance(self.builder, Path) or not self.builder.is_absolute():
            raise ValueError("INSTALLATION_BUILD_PATH_INVALID")
        if not self.builder.is_file():
            raise ValueError("INSTALLATION_BUILDER_MISSING")
        if requires_npm:
            if not isinstance(self.npm_root, Path) or not self.npm_root.is_absolute():
                raise ValueError("INSTALLATION_BUILD_PATH_INVALID")
            if not self.npm_root.is_dir():
                raise ValueError("INSTALLATION_NPM_ROOT_MISSING")
            if not all((self.npm_root / name).is_file() for name in ("package.json", "package-lock.json")):
                raise ValueError("INSTALLATION_NPM_INPUT_MISSING")
        elif self.npm_root is not None:
            raise ValueError("INSTALLATION_UNEXPECTED_NPM_ROOT")
        return self
