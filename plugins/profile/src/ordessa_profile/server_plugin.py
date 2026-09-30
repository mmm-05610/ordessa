"""Profile wire adapter. Domain logic and storage remain in ProfileCore.

The product injects the Harness catalog, configuration port and facet providers.
No host or sibling implementation is imported. v2 methods deliberately do not
replace the legacy ``profiles.*`` execution-record surface.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from server_plugin_api import (ServerMethodDescriptor, ServerPluginContext,
                               ServerPluginDescriptor, ServerPluginRegistration,
                               WireError)

from .core import ProfileCore
from .errors import ProfileError


def project(value: Any) -> Any:
    """Project DTO keys, never rewrite user values or schema property names."""
    if isinstance(value, list):
        return [project(item) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            parts = key.split("_")
            name = parts[0] + "".join(part.title() for part in parts[1:])
            result[name] = item if key in {"value", "value_schema", "items_json"} else project(item)
        return result
    return value


class ProfileServerPlugin:
    def __init__(self, *, harnesses=None, config_port=None, providers=()) -> None:
        self.harnesses = harnesses
        self.config_port = config_port
        self.providers = tuple(providers)
        self.core = None

    def descriptor(self):
        return ServerPluginDescriptor(id="ordessa.profile", display_name="Profile", version="2",
            requires=() if self.harnesses is not None else ("ordessa.server-compat",))

    def build(self, context: ServerPluginContext):
        directory = Path(context.data_root) / "plugins" / "profile"
        directory.mkdir(parents=True, exist_ok=True)
        harnesses = self.harnesses
        if harnesses is None:
            directory_port = context.ports["harness.directory"]

            class Catalog:
                def registered(self):
                    return directory_port.registered()

                def exists(self, harness_id):
                    return harness_id in directory_port.registered()

                def required_item_ids(self, harness_id):
                    return frozenset()

            harnesses = Catalog()
        core = ProfileCore(directory / "profile-store.sqlite", harnesses=harnesses,
                           config_port=self.config_port)
        self.core = core
        try:
            for owner, provider in self.providers:
                core.register_v2_provider(provider, owner)
        except BaseException:
            core.db.close()
            self.core = None
            raise

        def catalog(p):
            groups = {}
            for row in core.profiles.list(realm=p.get("realm", "local")):
                hid = row["harness_id"]
                if not harnesses.exists(hid):
                    continue
                group = groups.setdefault(hid, {"harnessId": hid, "harnessTitle": hid, "profiles": []})
                group["profiles"].append({"profileId": row["profile_id"], "harnessId": hid,
                                          "displayName": row["display_name"], "archived": False})
            return list(groups.values())

        operations = {
            "configuredHarnesses": ((), (), lambda p: list(getattr(harnesses, "registered", lambda: ())())),
            "listProfiles": ((), ("realm", "includeArchived"), lambda p: core.profiles.list(
                realm=p.get("realm"), include_archived=p.get("includeArchived", False))),
            "getProfile": (("profileId",), (), lambda p: core.profiles.get(p["profileId"])),
            "createProfile": (("operationKey", "realm", "harnessId", "displayName"), (),
                lambda p: core.profiles.create(p["operationKey"], realm=p["realm"],
                    harness_id=p["harnessId"], display_name=p["displayName"])),
            "renameProfile": (("operationKey", "profileId", "expectedVersion", "displayName"), (),
                lambda p: core.profiles.rename(p["operationKey"], profile_id=p["profileId"],
                    expected_version=p["expectedVersion"], display_name=p["displayName"])),
            "archiveProfile": (("operationKey", "profileId", "expectedVersion"), (),
                lambda p: core.profiles.archive(p["operationKey"], profile_id=p["profileId"], expected_version=p["expectedVersion"])),
            "restoreProfile": (("operationKey", "profileId", "expectedVersion"), (),
                lambda p: core.profiles.restore(p["operationKey"], profile_id=p["profileId"], expected_version=p["expectedVersion"])),
            "describeFacets": ((), ("harnessId",), lambda p: core.describe_facets(p.get("harnessId"))),
            "resolvePreview": (("profileId",), ("sessionUid",), lambda p: core.resolve_preview(p["profileId"], p.get("sessionUid"))),
            "profileCatalog": ((), ("realm",), catalog),
        }

        def wrap(handler):
            def invoke(params: Mapping[str, Any]):
                for name, value in params.items():
                    if name == "includeArchived":
                        valid = isinstance(value, bool)
                    elif name == "expectedVersion":
                        valid = type(value) is int and value > 0
                    elif name == "harnessId" and value is None:
                        valid = True  # describeFacets accepts the unfiltered catalog
                    else:
                        valid = isinstance(value, str) and bool(value.strip())
                    if not valid:
                        raise WireError("INVALID_REQUEST", f"Invalid Profile parameter: {name}")
                try:
                    # C-03 carries object results only, even for list operations.
                    return {"data": project(handler(params))}
                except ProfileError as exc:
                    family = "NOT_FOUND" if exc.status == 404 else "INVALID_REQUEST" if exc.status == 422 else "CONFLICT_REQUEST"
                    raise WireError(family, exc.message, details={"internalCode": exc.code},
                                    current=project(exc.current)) from exc
            return invoke

        methods = tuple(ServerMethodDescriptor(
            method_id="profiles.v2." + operation,
            required_params=frozenset(required), optional_params=frozenset(optional),
            handler=wrap(handler), owner="ordessa.profile",
        ) for operation, (required, optional, handler) in operations.items())

        def dispose():
            core.db.close()
            if self.core is core:
                self.core = None

        return ServerPluginRegistration(methods=methods,
            provided_ports={"profile.core": core}, disposal=dispose)
