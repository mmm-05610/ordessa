"""Opaque Server-owned root carrier and explicit host validation port."""
from __future__ import annotations
from pathlib import Path
from typing import Protocol

class RootOwnershipError(RuntimeError):
    """The requested product path is not covered by the current root owner."""


class OwnedRootBinding:
    """Opaque path-bound proof; only the Server host bridge can issue one.

    The public type is intentionally not constructible. Its provenance is a
    trusted-code composition boundary, not an isolation boundary against other
    Python code already executing in this process.
    """

    __slots__ = ("root_path", "store_path", "child_path", "_validate_current",
                 "_issued_identity")

    def __new__(cls, *_args, **_kwargs):
        raise TypeError("OwnedRootBinding values are issued by the Server host")

    def __setattr__(self, _name, _value):
        raise AttributeError("OwnedRootBinding values are immutable")

    def validate_for(
        self, *, root_path: Path | str, store_path: Path | str, child_path: Path | str,
    ) -> None:
        """Unissued public carriers cannot claim host ownership."""
        raise RootOwnershipError("owned root proof was not issued by the Server host")


class RootOwnershipPort(Protocol):
    """Host capability that binds a child path to its already-held data root."""

    def bind_owned_root(
        self, *, root_path: Path | str, store_path: Path | str,
        child_path: Path | str,
    ) -> OwnedRootBinding: ...


    def validate_owned_root(
        self, binding: OwnedRootBinding, *, root_path: Path | str,
        store_path: Path | str, child_path: Path | str,
    ) -> None:
        """Revalidate using the trusted host issuer rather than caller overrides."""
        ...


__all__ = ["OwnedRootBinding", "RootOwnershipError", "RootOwnershipPort"]
