"""Direct human/script discovery; Skill installation is not required."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import uuid

from .initialization import discover, save_report
from .client import ClientError, WireClient, load_service, parse_json, core_schema, profile_ref_valid, MAX_BYTES


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse may echo argv values, including a mistakenly pasted secret.
        raise ClientError("PARAMETER_INVALID", "Invalid command arguments; consult --help", 2)


def parser():
    root = Parser(prog="ordessa-agent", description="Independent Agent Tools initialization and service client")
    commands = root.add_subparsers(dest="command", required=True, parser_class=Parser)
    init = commands.add_parser("init", help="Observe local Harness executables without running them")
    init.add_argument("--json", action="store_true", help="Stable machine envelope")
    init.add_argument("--path", help="Explicit search PATH; only absolute entries are searched")
    init.add_argument("--output", help="Save an observation report to a new selected file")
    def connection(child):
        child.add_argument("--config", required=True, help="Protected service configuration JSON")
        child.add_argument("--service", required=True, help="Configured service alias")
        child.add_argument("--json", action="store_true", help="Stable machine envelope")
        child.add_argument("--timeout", type=float, default=10, help="Read timeout in seconds (0 < value <= 120)")
    for command in ("doctor", "capabilities"):
        connection(commands.add_parser(command))
    profile = commands.add_parser("profiles")
    actions = profile.add_subparsers(dest="action", required=True, parser_class=Parser)
    for action in ("list", "show", "entry", "preview", "create", "edit", "clone", "rename", "archive", "restore"):
        child = actions.add_parser(action)
        connection(child)
        if action in {"show", "preview", "clone"}:
            child.add_argument("profile_ref", help="Complete ProfileRef JSON or @file")
        if action in {"entry", "edit", "rename", "archive", "restore"}:
            child.add_argument("profile_id")
        if action in {"create", "clone"}:
            child.add_argument("--profile-id", required=True)
        if action in {"create", "clone", "rename"}:
            child.add_argument("--name", required=True)
        if action in {"create", "edit"}:
            child.add_argument("--file", required=True, help="Manifest JSON file")
        if action in {"edit", "rename", "archive", "restore"}:
            child.add_argument("--expected-catalog-revision", required=True, type=int)
        if action == "edit":
            child.add_argument("--base-manifest", required=True, help="Complete base ProfileRef JSON or @file")
        if action in {"create", "edit", "clone", "rename", "archive", "restore"}:
            child.add_argument("--request-id", required=True)
        if action == "list":
            child.add_argument("--include-archived", action="store_true")
    return root


def json_input(value, *, file_only=False):
    try:
        if file_only or value.startswith("@"):
            with Path(value if file_only else value[1:]).open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("oversized input")
        else:
            raw = value.encode("utf-8")
        result = parse_json(raw)
        if not isinstance(result, dict):
            raise ValueError("object required")
        return result
    except (OSError, ValueError, RecursionError):
        raise ClientError("PARAMETER_INVALID", "Input must be a readable bounded JSON object", 2) from None


def reference(value):
    result = json_input(value)
    schema = core_schema()["schema"]["profileRef"]
    if not profile_ref_valid(result):
        raise ClientError("PARAMETER_INVALID", "ProfileRef fields do not match the published schema", 2)
    return result


def profile_request(options):
    action = {"show": "read", "entry": "readEntry"}.get(options.action, options.action)
    params = {}
    for attr, key in (("profile_id", "profileId"), ("name", "displayName"),
                      ("expected_catalog_revision", "expectedCatalogRevision"), ("request_id", "requestId")):
        if hasattr(options, attr):
            value = getattr(options, attr)
            if not value or (attr == "expected_catalog_revision" and value < 1):
                raise ClientError("PARAMETER_INVALID", "Required identifiers and revisions must be nonempty and positive", 2)
            params[key] = value
    if hasattr(options, "profile_ref"):
        params["profileRef"] = reference(options.profile_ref)
    if hasattr(options, "base_manifest"):
        params["baseManifestRef"] = reference(options.base_manifest)
    if hasattr(options, "file"):
        params["manifest"] = json_input(options.file, file_only=True)
    if options.action == "list" and options.include_archived:
        params["includeArchived"] = True
    return "agents.profiles." + action, params


def profile_result(action, result, environment_namespace=None):
    schema = core_schema()["schema"]
    def ref(value):
        return profile_ref_valid(value) and (environment_namespace is None or value["environmentNamespace"] == environment_namespace)
    def entry(value):
        return (isinstance(value, dict) and set(value) == set(schema["results"]["catalogEntry"]["required"])
                and isinstance(value["profileId"], str) and bool(value["profileId"])
                and isinstance(value["displayName"], str) and bool(value["displayName"])
                and type(value["catalogRevision"]) is int and value["catalogRevision"] > 0
                and (value["archivedAt"] is None or isinstance(value["archivedAt"], str))
                and ref(value["currentManifestRef"])
                and value["profileId"] == value["currentManifestRef"]["profileId"])
    if not isinstance(result, dict):
        return False
    if action == "list":
        return set(result) == set(schema["results"]["list"]["required"]) and isinstance(result["entries"], list) and all(entry(value) for value in result["entries"])
    if action == "show":
        return set(result) == set(schema["results"]["manifest"]["required"]) and ref(result["ref"]) and isinstance(result["content"], dict)
    if action == "preview":
        return (set(result) == set(schema["results"]["preview"]["required"])
                and ref(result["profileRef"]) and result["status"] == "unresolved"
                and result["referenceCoverage"] == "unknown" and result["ready"] is False
                and result["error"] == {"code": "providerUnavailable", "retryable": False})
    return entry(result)


def emit(args, envelope):
    if "--json" in args:
        print(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")))
    elif envelope["error"] is not None:
        print(envelope["error"]["code"] + ": " + envelope["error"]["message"], file=sys.stderr)
    else:
        print(json.dumps(envelope["data"], ensure_ascii=False, indent=2))


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    request_id = str(uuid.uuid4())
    service_ref = None
    data = None
    evidence = {"level": "unobserved"}
    try:
        options = parser().parse_args(args)
        if options.command == "init":
            data = discover(options.path)
            evidence = {"level": "localExecutableDiscovery", "executedBinaries": False,
                        "serverHostChecked": False, "runtimeVerified": False}
            found = bool(data["foundFamilies"])
            envelope = {"apiVersion": "agent-tools/1", "requestId": request_id,
                        "serviceRef": None, "operationRef": None,
                        "status": "confirmed" if found else "refused", "data": data, "evidence": evidence,
                        "error": None if found else {"code": "HARNESS_EXECUTABLES_NOT_FOUND" if data["scanCompleteForSearchedEntries"] else "HARNESS_DISCOVERY_INCOMPLETE",
                            "message": "No executable Harness candidates confirmed; inspect local discovery diagnostics",
                            "retryable": False, "recoveryAction": "inspectLocalInstallation"}}
            if options.output:
                save_report(options.output, envelope)
            emit(args, envelope)
            return 0 if found else 4
        prepared = profile_request(options) if options.command == "profiles" else None
        if not math.isfinite(options.timeout) or not 0 < options.timeout <= 120:
            raise ClientError("PARAMETER_INVALID", "Timeout must be greater than zero and at most 120 seconds", 2)
        service = load_service(options.config, options.service)
        requested_id = getattr(options, "request_id", request_id)
        if service.token in requested_id:
            raise ClientError("PARAMETER_INVALID", "Request identity cannot contain authentication material", 2)
        request_id = requested_id
        service_ref = service.alias
        client = WireClient(service, timeout=options.timeout)
        discovery = client.hello(str(uuid.uuid4()))
        data = {"discovery": {"status": "confirmed", "protocolVersion": discovery["protocolVersion"]},
                "coreAgent": {"status": "unavailable", "reasonCode": "CORE_API_UNAVAILABLE"}}
        if options.command == "capabilities":
            data["capabilities"] = discovery["capabilities"]
        evidence = {"level": "wireDiscoveryObserved"}
        if not any(item["id"] == "agents.capabilities" and item["supported"] for item in discovery["capabilities"]):
            raise ClientError("CORE_API_UNAVAILABLE", "wire/1 discovery succeeded; the required Agent core public contract is not available", 4)
        core = client.negotiate(str(uuid.uuid4()))
        data["coreAgent"] = core
        evidence = {"level": "coreCapabilitiesObserved"}
        if core["supports"]["profileCatalog"] is not True:
            raise ClientError("PROFILE_CATALOG_UNAVAILABLE", "Profile catalog guarantees are unavailable", 4)
        if prepared is not None:
            method, params = prepared
            result = client.core_call(method, params, request_id)
            effectful = core_schema()["schema"]["methods"][method]["effectful"]
            if (not profile_result(options.action, result, core["environmentNamespace"])
                    or service.token in json.dumps(result)
                    or (options.action in {"show", "preview"} and result.get("ref", result.get("profileRef")) != params["profileRef"])
                    or ("profileId" in params and result.get("profileId") != params["profileId"])):
                raise ClientError("OUTCOME_UNKNOWN" if effectful else "CORE_RESPONSE_INVALID", "Core result could not be safely validated", 6 if effectful else 4)
            data = result
            evidence = {"level": "profileCatalogObserved"}
            if options.action == "preview":
                raise ClientError("PROVIDER_UNAVAILABLE", "Profile preview remains unresolved until trusted providers are available", 4)
        envelope = {"apiVersion": "agent-tools/1", "requestId": request_id,
                    "serviceRef": service_ref, "operationRef": None, "status": "confirmed",
                    "data": data, "evidence": evidence, "error": None}
        emit(args, envelope)
        return 0
    except ClientError as error:
        envelope = {"apiVersion": "agent-tools/1", "requestId": request_id,
                    "serviceRef": service_ref, "operationRef": None,
                    "status": "unknown" if error.exit_code == 6 else "refused",
                    "data": data, "evidence": evidence,
                    "error": {"code": error.code, "message": error.message,
                              "retryable": False, "recoveryAction": "inspectLocalInstallation" if args[:1] == ["init"] else "inspectService"}}
        emit(args, envelope)
        return error.exit_code


if __name__ == "__main__":
    sys.exit(main())
