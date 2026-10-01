"""Profile wire adapter. Domain logic and storage remain in ProfileCore.

The product injects the Harness catalog, configuration port and facet providers.
No host or sibling implementation is imported. v2 methods deliberately do not
replace the legacy ``profiles.*`` execution-record surface.
"""
from __future__ import annotations

from pathlib import Path
from dataclasses import asdict
from typing import Any, Mapping

from server_plugin_api import (ServerMethodDescriptor, ServerPluginContext,
                               ServerPluginDescriptor, ServerPluginRegistration,
                               WireError)

from .core import ProfileCore
from .errors import ProfileError
from .contracts import SessionRef


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
    def __init__(self, *, harnesses=None, config_port=None, providers=(),
                 native_registration_factory=None) -> None:
        self.harnesses = harnesses
        self.config_port = config_port
        self.providers = tuple(providers)
        self.core = None
        self.native_registration_factory = native_registration_factory

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
            native_registration = (
                self.native_registration_factory(core)
                if self.native_registration_factory is not None else None)
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

        def save(p):
            values, unsets = [], []
            seen = set()
            patches = p["patches"]
            if not isinstance(patches, list) or not 1 <= len(patches) <= 256:
                raise WireError("INVALID_REQUEST", "Profile patches must be a nonempty bounded array")
            for patch in patches:
                if not isinstance(patch, dict):
                    raise WireError("INVALID_REQUEST", "Invalid Profile patch")
                op = patch.get("op")
                expected = {"facetId", "itemId", "op"} | ({"value"} if op == "set" else set())
                if (not isinstance(op, str) or op not in {"set", "unset"} or set(patch) != expected
                        or any(not isinstance(patch.get(k), str) or not patch[k].strip()
                               for k in ("facetId", "itemId"))):
                    raise WireError("INVALID_REQUEST", "Invalid Profile patch")
                identity = (patch["facetId"], patch["itemId"])
                if identity in seen:
                    raise WireError("INVALID_REQUEST", "Duplicate Profile patch")
                seen.add(identity)
                item = {"facet_id": identity[0], "item_id": identity[1]}
                if op == "set":
                    values.append({**item, "value": patch["value"]})
                else:
                    unsets.append(item)
            return {"profile": core.profiles.set_facet_values(p["operationKey"],
                profile_id=p["profileId"], expected_version=p["expectedVersion"],
                values=values, unsets=unsets)}

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
            "saveProfile": (("operationKey", "profileId", "expectedVersion", "patches"), (), save),
            "archiveProfile": (("operationKey", "profileId", "expectedVersion"), (),
                lambda p: core.profiles.archive(p["operationKey"], profile_id=p["profileId"], expected_version=p["expectedVersion"])),
            "restoreProfile": (("operationKey", "profileId", "expectedVersion"), (),
                lambda p: core.profiles.restore(p["operationKey"], profile_id=p["profileId"], expected_version=p["expectedVersion"])),
            "describeFacets": ((), ("harnessId",), lambda p: core.describe_facets(p.get("harnessId"))),
            "resolvePreview": (("profileId",), ("sessionUid",), lambda p: core.resolve_preview(p["profileId"], p.get("sessionUid"))),
            "profileCatalog": ((), ("realm",), catalog),
        }

        if native_registration is not None:
            def prepare_native(p):
                prepare = getattr(native_registration, 'prepare_native_creation', None)
                if prepare is None:
                    raise ProfileError('APPLICATION_PORT_ABSENT', 'Native preparation unavailable', status=409)
                return prepare(connection_id=p['connectionId'], profile_id=p['profileId'], operation_id=p['operationId'])

            operations['prepareNativeCreation'] = (
                ('connectionId', 'profileId', 'operationId'), (), prepare_native)

            def register_native(p):
                binding = native_registration.register(
                    connection_id=p["connectionId"],
                    native_session_id=p["nativeSessionId"], profile_id=p["profileId"])
                return {"session_ref": asdict(binding.session_ref),
                        "target": asdict(binding.snapshot.target)}

            operations["registerNativeSession"] = (
                ("connectionId", "nativeSessionId", "profileId"), (), register_native)

            def session_ref(p):
                value = p["sessionRef"]
                ref = SessionRef(value["realm"], value["harnessId"], value["nativeSessionKey"], value["sessionUid"])
                native_registration.require_registered(ref)
                return ref

            def select(p):
                ref = session_ref(p)
                result = core.sessions.select_profile(p["operationKey"], session_id=ref.session_uid,
                                                      profile_id=p["profileId"])
                return {"session_ref": asdict(ref), "pending_profile_id": result["pending_profile_id"],
                        "pending_seq": result["pending_seq"], "switch_state": "pending"}

            def inspect(p):
                ref = session_ref(p)
                result = core.sessions.session_config(ref.session_uid)
                evidence = dict(result["evidence"])
                if evidence["receipt"] is not None:
                    evidence["receipt"] = receipt_dto(evidence["receipt"])
                items = [{"facet_id": item["facet_id"], "item_id": item["item_id"],
                          "value": item["value"],
                          "state": "disabled" if isinstance(item["value"], dict) and item["value"].get("disabled") is True else "explicit",
                          "source": {"kind": "session-overlay" if item["source"] == "session_only" else "profile",
                                     "revision": item["revision"]}}
                         for item in result["items"]]
                return {**{k: result[k] for k in ("switch_state", "current", "pending", "items", "unavailable", "blockers", "evidence")},
                        "session_ref": asdict(ref), "evidence": evidence, "items": items}

            def receipt_dto(receipt):
                identity = {key: receipt[key] for key in ("realm", "harness_id", "native_session_key", "session_uid")}
                return {**{key: value for key, value in receipt.items() if key not in identity},
                        "session_ref": identity}

            def begin(p):
                ref = session_ref(p)
                result = core.sessions.begin_turn(p["operationKey"], session_id=ref.session_uid)
                return {"turn_id": result["turn_id"], "applied_switch": result["applied_switch"],
                        **({"receipt": receipt_dto(result["receipt"])} if "receipt" in result else {})}

            def override(p, *, clear=False):
                ref = session_ref(p)
                kwargs = {"session_id": ref.session_uid, "facet_id": p["facetId"], "item_id": p["itemId"]}
                if clear:
                    core.sessions.clear_overlay(p["operationKey"], **kwargs)
                else:
                    core.sessions.set_overlay(p["operationKey"], **kwargs, value=p["value"])
                return inspect(p)

            def reconcile(p):
                ref = session_ref(p)
                result = core.sessions.reconcile(p["operationKey"], session_id=ref.session_uid)
                return {"operation_id": result["operation_id"], "state": result["state"],
                        **({"receipt": receipt_dto(result["receipt"])} if result.get("receipt") is not None else {}),
                        **({"reason": result["reason"]} if "reason" in result else {})}

            operations.update({
                "selectForSession": (("operationKey", "sessionRef", "profileId"), (), select),
                "inspectSessionConfig": (("sessionRef",), (), inspect),
                "beginTurnApplication": (("operationKey", "sessionRef"), (), begin),
                "setSessionOverride": (("operationKey", "sessionRef", "facetId", "itemId", "value"), (), override),
                "clearSessionOverride": (("operationKey", "sessionRef", "facetId", "itemId"), (), lambda p: override(p, clear=True)),
                "reconcile": (("operationKey", "sessionRef"), (), reconcile),
            })

        def wrap(handler):
            def invoke(params: Mapping[str, Any]):
                for name, value in params.items():
                    if name == "sessionRef":
                        valid = (isinstance(value, dict) and set(value) == {"realm", "harnessId", "nativeSessionKey", "sessionUid"}
                                 and all(isinstance(v, str) and bool(v.strip()) for v in value.values()))
                    elif name == "value":
                        valid = True  # the registered facet validates values before mutation
                    elif name == "patches":
                        valid = True  # save validates the complete structured patch before mutation
                    elif name == "includeArchived":
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

        ports = {"profile.core": core}
        if native_registration is not None:
            ports["profile.native-sessions"] = native_registration
        return ServerPluginRegistration(methods=methods,
            provided_ports=ports, disposal=dispose)
