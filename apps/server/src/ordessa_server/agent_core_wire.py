"""Transport-only projection of the core-owned Agent public contract."""
from __future__ import annotations

from ordessa_environment_api import (
    AdmissionRefusedError, GuaranteeUnavailableError, IdentityMismatchError, ComparisonUnavailableError,
    UnknownResultError, RequestKey,
)
from ordessa_environment_api.domain import DomainRevisionConflict
from pacthold.agents.public import (
    AGENT_CONTRACT_VERSION, ProfileNotFound, ProfileRef, ProfileRevisionConflict, ProfileValidationError,
    agent_services, wire_contract, wire_schema_digest,
)
from server_plugin_api import ServerMethodDescriptor, WireError


def agent_core_methods(environment_resolver):
    """Bind to the current host lifecycle, never create an Environment here."""
    def handler(action, definition):
        def invoke(params):
            try:
                if (not isinstance(params, dict)
                        or not set(definition["required"]) <= params.keys()
                        or params.keys() - set(definition["required"] + definition["optional"])):
                    raise ValueError("parameter shape mismatch")
                for name in ("profileId", "displayName", "requestId"):
                    if name in params and (not isinstance(params[name], str) or not params[name]):
                        raise ValueError("nonempty string required")
                if "expectedCatalogRevision" in params and (
                    type(params["expectedCatalogRevision"]) is not int or params["expectedCatalogRevision"] < 1
                ):
                    raise ValueError("positive revision required")
                if type(params.get("includeArchived", False)) is not bool:
                    raise ValueError("boolean required")
                refs = {name: ProfileRef.from_dict(params[name])
                        for name in ("profileRef", "baseManifestRef") if name in params}
                if "requestId" in params:
                    RequestKey("parameter-check", "local", params["requestId"])
            except (ValueError, TypeError, KeyError):
                raise WireError("INVALID_REQUEST", "Profile parameters are invalid", {"retryable": False}) from None
            try:
                catalog = agent_services(environment_resolver()).profiles
                if action == "capabilities":
                    return {"contractVersion": AGENT_CONTRACT_VERSION,
                            "schemaDigest": wire_schema_digest(), "schema": wire_contract(),
                            "environmentNamespace": catalog.environment_namespace,
                            "supports": dict(catalog.capabilities())}
                if action == "list":
                    return {"entries": [entry.to_dict() for entry in catalog.list(
                        include_archived=params.get("includeArchived", False))]}
                if action == "readEntry":
                    return catalog.read_entry(params["profileId"]).to_dict()
                if action in {"read", "preview", "clone"}:
                    ref = refs["profileRef"]
                    if action == "read":
                        manifest = catalog.read(ref)
                        return {"ref": manifest.ref.to_dict(), "content": manifest.content}
                    if action == "preview":
                        return dict(catalog.preview(ref))
                request = catalog.request_key(params["requestId"])
                if action == "create":
                    result = catalog.create(profile_id=params["profileId"],
                                            display_name=params["displayName"],
                                            manifest=params["manifest"], request=request)
                elif action == "clone":
                    result = catalog.clone(ref, profile_id=params["profileId"],
                                           display_name=params["displayName"], request=request)
                elif action == "edit":
                    result = catalog.edit(params["profileId"], manifest=params["manifest"],
                        expected_catalog_revision=params["expectedCatalogRevision"],
                        base_manifest_ref=refs["baseManifestRef"], request=request)
                else:
                    kwargs = {"expected_catalog_revision": params["expectedCatalogRevision"], "request": request}
                    if action == "rename":
                        kwargs["display_name"] = params["displayName"]
                    result = getattr(catalog, action)(params["profileId"], **kwargs)
                return result.to_dict()
            except (ProfileRevisionConflict, DomainRevisionConflict):
                raise WireError("CONFLICT_VERSION", "Profile revision comparison failed", {"retryable": False}) from None
            except IdentityMismatchError:
                raise WireError("CONFLICT_REQUEST", "Request or reference identity conflict", {"retryable": False}) from None
            except AdmissionRefusedError:
                raise WireError("FORBIDDEN", "Profile access refused", {"retryable": False}) from None
            except GuaranteeUnavailableError:
                raise WireError("CAPABILITY_UNSUPPORTED", "Required core guarantee unavailable", {"retryable": False}) from None
            except (UnknownResultError, ComparisonUnavailableError):
                raise WireError("OUTCOME_UNKNOWN", "Request outcome is unknown; do not resend", {"retryable": False}) from None
            except ProfileNotFound:
                raise WireError("NOT_FOUND", "Profile reference not found", {"retryable": False}) from None
            except ProfileValidationError:
                raise WireError("INVALID_REQUEST", "Profile parameters are invalid", {"retryable": False}) from None
            except Exception:
                # A failure not proven to precede commit cannot assert that an
                # effect did not occur. It never grants a retry permission.
                if action in {"create", "edit", "clone", "rename", "archive", "restore"}:
                    raise WireError("OUTCOME_UNKNOWN", "Profile change could not be confirmed; inspect results", {"retryable": False}) from None
                raise WireError("UNAVAILABLE", "Core observation unavailable", {"retryable": False}) from None
        return invoke

    return tuple(ServerMethodDescriptor(method_id=method,
        required_params=frozenset(binding["required"]),
        optional_params=frozenset(binding["optional"]),
        handler=handler(binding["action"], binding), owner="pacthold.agents")
        for method, binding in wire_contract()["methods"].items())
