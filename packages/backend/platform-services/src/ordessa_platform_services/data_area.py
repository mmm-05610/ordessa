"""E4 data-area adapters: file-backed namespaces (spec 026/005 T005-10).

Identity rules frozen here:

* a namespace maps to ONE stable directory under the root — plugin source
  moves never move user data; the on-disk layout keeps its existing
  identifiers (M07);
* closing a handle releases the ACCESS relation only — data bytes survive
  (uninstall keeps data); purge is a separate authorized effect that this
  adapter refuses to perform implicitly;
* a schema declaration outside the claimed supported range refuses WRITES
  before any byte changes (old binaries against new schemas stay honest).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ordessa_environment_api.services import DataAreaDescriptor

_NAMESPACE = re.compile(r"^[a-z][a-z0-9._-]{0,95}$")


class DataAreaError(RuntimeError):
    code = "DATA_AREA"


class FileDataAreaAdapter:
    """One root directory; namespaces are stable subdirectories."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._claims: dict[str, DataAreaDescriptor] = {}
        self._handles: dict[str, Path] = {}

    def _namespace_root(self, namespace: str) -> Path:
        if not isinstance(namespace, str) or not _NAMESPACE.match(namespace):
            raise DataAreaError(f"namespace {namespace!r} is not a stable identity")
        return self._root / namespace.replace(".", "/")

    def claim(self, namespace: str, access: str, schema_declaration: str) -> DataAreaDescriptor:
        if access not in ("read", "write"):
            raise DataAreaError(f"access must be read|write, got {access!r}")
        lo, _, hi = schema_declaration.partition("-")
        area = self._namespace_root(namespace)
        area.mkdir(parents=True, exist_ok=True)
        descriptor = DataAreaDescriptor(
            area_id=f"area.{namespace}", namespace=namespace,
            owner_domain=namespace.rsplit(".", 1)[0], backend_kind="file",
            supported_schema_range=schema_declaration,
            current_schema_evidence=self._read_current_schema(area, hi),
            access=access, persistence_guarantee="durable", retention="keep",
        )
        self._claims[namespace] = descriptor
        return descriptor

    @staticmethod
    def _read_current_schema(area: Path, hi: str) -> str | None:
        marker = area / "data-area.json"
        if marker.exists():
            try:
                return str(json.loads(marker.read_text(encoding="utf-8"))["schema"])
            except (ValueError, KeyError):
                return None
        return hi  # a fresh area starts at the top of the declared range

    def open(self, area_id: str) -> Path:
        namespace = area_id[5:] if area_id.startswith("area.") else area_id
        descriptor = self._claims.get(namespace)
        if descriptor is None:
            raise DataAreaError(f"area {area_id!r} was not claimed in this adapter")
        return self._namespace_root(namespace)

    def close(self, area_id: str) -> None:
        """Releases the access relation; bytes stay on disk by contract."""
        namespace = area_id[5:] if area_id.startswith("area.") else area_id
        self._handles.pop(namespace, None)
        self._claims.pop(namespace, None)

    def inspect(self, area_id: str) -> DataAreaDescriptor:
        namespace = area_id[5:] if area_id.startswith("area.") else area_id
        descriptor = self._claims.get(namespace)
        if descriptor is None:
            raise DataAreaError(f"area {area_id!r} is not open")
        return descriptor

    def write_schema_marker(self, area_id: str, schema: str) -> None:
        """Writing advances the schema marker ONLY inside the declared range."""
        namespace = area_id[5:] if area_id.startswith("area.") else area_id
        descriptor = self._claims.get(namespace)
        if descriptor is None or descriptor.access != "write":
            raise DataAreaError(f"area {area_id!r} is not claimed for write")
        lo, _, hi = descriptor.supported_schema_range.partition("-")
        current = descriptor.current_schema_evidence
        if current is not None and current > hi:
            raise DataAreaError(
                f"area schema is at {current!r}, above this adapter's supported "
                f"{descriptor.supported_schema_range!r}; refusing to write (an old "
                "binary never silently downgrades or upgrades newer data)"
            )
        if not (lo <= schema <= hi):
            raise DataAreaError(
                f"schema {schema!r} outside supported range {descriptor.supported_schema_range!r}; "
                "refusing to write (an old binary never silently upgrades)"
            )
        marker = self._namespace_root(namespace) / "data-area.json"
        marker.write_text(json.dumps({"schema": schema}, sort_keys=True), encoding="utf-8")

    def purge(self, area_id: str, *, authorization: Any) -> None:
        """Purge is a separate authorized effect — the adapter performs it
        only with an explicit authorization object, never on close."""
        if authorization is None:
            raise DataAreaError("purge requires an explicit authorization object")
        namespace = area_id[5:] if area_id.startswith("area.") else area_id
        import shutil

        shutil.rmtree(self._namespace_root(namespace), ignore_errors=False)
