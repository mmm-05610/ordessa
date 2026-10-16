"""Closed, non-secret first-case Engineering startup configuration."""
from pathlib import Path

from ordessa_infrastructure.encoding import decode_json


class UserConfigurationError(ValueError):
    """A user configuration file is malformed or ambiguous."""


_ROOT_KEYS = {"version", "engineering"}
_ENGINEERING_KEYS = {
    "libraryPath", "libraryId", "realm", "project", "schemaVersion",
    "createLibrary", "machineCapabilities",
}
_SCHEMAS = {7, 8, 10, 13, 14, 15}


def load_engineering_user_configuration(path: Path) -> dict[str, object]:
    """Read explicit library settings; never create, migrate, or open the DB."""
    if not isinstance(path, Path):
        raise UserConfigurationError("user configuration path must be explicit")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise UserConfigurationError("user configuration file is unavailable") from error
    if len(raw) > 1_048_576:
        raise UserConfigurationError("user configuration exceeds 1 MiB")
    try:
        value = decode_json(raw.decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError):
        raise UserConfigurationError("user configuration is not strict UTF-8 JSON") from None
    if type(value) is not dict or set(value) != _ROOT_KEYS or type(value["version"]) is not int or value["version"] != 1:
        raise UserConfigurationError("user configuration has invalid top-level fields")
    engineering = value["engineering"]
    if type(engineering) is not dict or set(engineering) != _ENGINEERING_KEYS:
        raise UserConfigurationError("Engineering configuration fields are incomplete or unknown")
    path_value = engineering["libraryPath"]
    if type(path_value) is not str or not path_value or not Path(path_value).is_absolute():
        raise UserConfigurationError("libraryPath must be an explicit absolute path")
    for field in ("libraryId", "realm", "project"):
        item = engineering[field]
        if type(item) is not str or not item or item.strip() != item:
            raise UserConfigurationError(f"invalid Engineering {field}")
    if type(engineering["schemaVersion"]) is not int or engineering["schemaVersion"] not in _SCHEMAS:
        raise UserConfigurationError("explicit supported schemaVersion required")
    if type(engineering["createLibrary"]) is not bool:
        raise UserConfigurationError("createLibrary must be explicit boolean")
    capabilities = engineering["machineCapabilities"]
    if (type(capabilities) is not list or any(type(item) is not str or not item for item in capabilities)
            or len(set(capabilities)) != len(capabilities)):
        raise UserConfigurationError("machineCapabilities must be an explicit unique string array")
    return {
        "library_path": Path(path_value),
        "library_id": engineering["libraryId"],
        "realm": engineering["realm"],
        "project": engineering["project"],
        "schema_version": engineering["schemaVersion"],
        "create_library": engineering["createLibrary"],
        "machine_capabilities": tuple(capabilities),
    }


__all__ = ["UserConfigurationError", "load_engineering_user_configuration"]
