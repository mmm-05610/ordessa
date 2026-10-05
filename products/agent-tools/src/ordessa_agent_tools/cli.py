"""Direct human/script discovery; Skill installation is not required."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import uuid

from .initialization import discover, save_report
from .providers import definition_ref_valid, provider_result_valid
from .nodes import node_result_valid
from .configuration import node_ref_valid, description_result_valid, snapshot_result_valid, change_request_valid, operation_result_valid, operation_disposition
from .client import ClientError, WireClient, load_service, parse_json, core_schema, profile_ref_valid, provider_schema, MAX_BYTES


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
    providers = commands.add_parser("providers", help="Observe the service's admitted Provider registry")
    provider_actions = providers.add_subparsers(dest="action", required=True, parser_class=Parser)
    for action in ("list", "describe"):
        child = provider_actions.add_parser(action)
        connection(child)
        if action == "describe":
            child.add_argument("definition_ref", help="Complete DefinitionRef JSON or @file")
    nodes = commands.add_parser("nodes", help="Consume published Node management methods")
    node_actions = nodes.add_subparsers(dest="node_action", required=True, parser_class=Parser)
    for action in ('list', 'inspect'):
        child = node_actions.add_parser(action, help='Read durable Node publications; does not verify native runtime state')
        child.set_defaults(action=action)
        connection(child)
        if action == 'inspect':
            child.add_argument('node_ref', help='Complete NodeRef JSON or @file')
    configuration = node_actions.add_parser("configuration", help="Observe owner configuration capabilities")
    configuration_actions = configuration.add_subparsers(dest="action", required=True, parser_class=Parser)
    for action, help_text in (("describe", "Read owner capability descriptions; does not inspect or apply values"),
                              ("inspect", "Observe owner actual configuration and explicit unknown fields")):
        child = configuration_actions.add_parser(action, help=help_text)
        connection(child)
        child.add_argument("node_ref", help="Complete NodeRef JSON or @file")
    for action in ("apply", "query"):
        child = configuration_actions.add_parser(action, help="Submit a fixed configuration change" if action == "apply" else "Reconcile the original configuration operation without resending the change")
        connection(child)
        child.add_argument("node_ref", help="Complete NodeRef JSON or @file")
        if action == "apply":
            child.add_argument("--file", required=True, help="Complete change JSON with requestId, expectedConfigurationRevision, declarations, applicationPolicy")
        else:
            child.add_argument("operation_ref", help="Original core operation identity")
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
    operation_ref = None
    result_status = None
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
        if options.command == "providers":
            params = {}
            if options.action == "describe":
                definition = json_input(options.definition_ref)
                if not definition_ref_valid(definition):
                    raise ClientError("PARAMETER_INVALID", "Complete DefinitionRef required", 2)
                params["definitionRef"] = definition
            prepared = ("agents.providers." + options.action, params)
        if options.command == 'nodes' and options.node_action != 'configuration':
            params = {}
            if options.node_action == 'inspect':
                node = json_input(options.node_ref)
                if not node_ref_valid(node):
                    raise ClientError('PARAMETER_INVALID', 'Complete NodeRef required', 2)
                params['nodeRef'] = node
            prepared = ('agents.nodes.' + ('read' if options.node_action == 'inspect' else 'list'), params)
        elif options.command == "nodes":
            node = json_input(options.node_ref)
            if not node_ref_valid(node):
                raise ClientError("PARAMETER_INVALID", "Complete NodeRef required", 2)
            params = {"nodeRef": node}
            if options.action == "apply":
                change = json_input(options.file, file_only=True)
                if not change_request_valid(change):
                    raise ClientError("PARAMETER_INVALID", "Complete bounded configuration change required", 2)
                params["change"] = change
                options.request_id = change["requestId"]
            elif options.action == "query":
                if not isinstance(options.operation_ref, str) or not options.operation_ref or len(options.operation_ref) > 256:
                    raise ClientError("PARAMETER_INVALID", "Original operation identity required", 2)
                params["operationRef"] = options.operation_ref
            prepared = ("agents.nodes.configuration." + options.action, params)
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
        if options.command in {"profiles", "doctor"} and core["supports"]["profileCatalog"] is not True:
            raise ClientError("PROFILE_CATALOG_UNAVAILABLE", "Profile catalog guarantees are unavailable", 4)
        if options.command == "providers":
            method, params = prepared
            if method not in core.get("supportedMethods", ()):
                raise ClientError("PROVIDER_DISCOVERY_UNAVAILABLE", "Service did not publish Provider discovery", 4)
            if "definitionRef" in params and not definition_ref_valid(params["definitionRef"], core["environmentNamespace"]):
                raise ClientError("PARAMETER_INVALID", "DefinitionRef belongs to another service environment", 2)
            result = client.core_call(method, params, request_id)
            runtime_version = core_schema(client.schema_version)["schema"]["configurationChange"]["providerContractVersion"]
            contract = provider_schema()["schema"]
            if contract["contractVersion"] != runtime_version:
                raise ClientError("CLIENT_SCHEMA_UNAVAILABLE", "Provider schema version differs from the Agent contract", 4)
            if (not provider_result_valid(options.action, result, core["environmentNamespace"], runtime_version, contract["supportedMethods"], params.get("definitionRef"))
                    or service.token in json.dumps(result)):
                raise ClientError("CORE_RESPONSE_INVALID", "Provider registry result could not be safely validated", 4)
            data = result
            evidence = {"level": "providerRegistryObserved", "runtimeVerified": False}
        elif options.command == 'nodes' and options.node_action != 'configuration':
            method, params = prepared
            if method not in core.get('supportedMethods', ()):
                raise ClientError('NODE_OBSERVATION_UNAVAILABLE', 'Service did not publish the requested Node observation', 4)
            if 'nodeRef' in params and not node_ref_valid(params['nodeRef'], core['environmentNamespace']):
                raise ClientError('PARAMETER_INVALID', 'NodeRef belongs to another service environment', 2)
            if service.token in json.dumps(params):
                raise ClientError('PARAMETER_INVALID', 'Node request cannot contain authentication material', 2)
            result = client.core_call(method, params, request_id)
            if (not node_result_valid(options.action, result, core['environmentNamespace'],
                    core_schema(client.schema_version)['schema'], params.get('nodeRef'))
                    or service.token in json.dumps(result)):
                raise ClientError('CORE_RESPONSE_INVALID', 'Node publication could not be safely validated', 4)
            data = result
            if options.action == 'inspect' and result['node'] is None:
                raise ClientError('NODE_NOT_FOUND', 'No publication exists for the requested NodeRef', 4)
            evidence = {'level': 'nodePublicationObserved', 'runtimeVerified': False}
        elif options.command == "nodes":
            method, params = prepared
            if method not in core.get("supportedMethods", ()):
                raise ClientError("NODE_CONFIGURATION_UNAVAILABLE", "Service did not publish the requested configuration method", 4)
            if not node_ref_valid(params["nodeRef"], core["environmentNamespace"]):
                raise ClientError("PARAMETER_INVALID", "NodeRef belongs to another service environment", 2)
            if "change" in params and not change_request_valid(params["change"], core["environmentNamespace"]):
                raise ClientError("PARAMETER_INVALID", "Configuration material belongs to another environment", 2)
            if service.token in json.dumps(params):
                raise ClientError("PARAMETER_INVALID", "Configuration request cannot contain authentication material", 2)
            result = client.core_call(method, params, request_id)
            managing = options.action in {"apply", "query"}
            valid = (operation_result_valid(result, core["environmentNamespace"], params.get("operationRef"), params.get("change")) if managing
                     else description_result_valid(result) if options.action == "describe"
                     else snapshot_result_valid(result, core["environmentNamespace"]))
            if not valid or service.token in json.dumps(result):
                raise ClientError("OUTCOME_UNKNOWN" if options.action == "apply" else "CORE_RESPONSE_INVALID",
                                  "Owner configuration result could not be safely validated", 6 if options.action == "apply" else 4)
            data = result
            if managing:
                operation_ref = result["operationRef"]
                result_status, exit_code, code = operation_disposition(result)
                evidence = {"level": "configurationOperationObserved", "runtimeVerified": False,
                            "allDeclarationsApplied": result["status"] == "published" and result["configurationResult"]["overallOutcome"] == "applied"}
                if exit_code:
                    raise ClientError(code, "Configuration outcome requires inspection of the original operation; do not resend", exit_code)
            else:
                evidence = {"level": "configurationDescriptionObserved" if options.action == "describe" else "configurationSnapshotObserved",
                            "runtimeVerified": False, "configurationValuesObserved": options.action == "inspect"}
        elif prepared is not None:
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
                    "serviceRef": service_ref, "operationRef": operation_ref, "status": result_status or "confirmed",
                    "data": data, "evidence": evidence, "error": None}
        emit(args, envelope)
        return 0
    except ClientError as error:
        envelope = {"apiVersion": "agent-tools/1", "requestId": request_id,
                    "serviceRef": service_ref, "operationRef": operation_ref,
                    "status": result_status or ("unknown" if error.exit_code == 6 else "refused"),
                    "data": data, "evidence": evidence,
                    "error": {"code": error.code, "message": error.message,
                              "retryable": False, "recoveryAction": "inspectLocalInstallation" if args[:1] == ["init"] else "inspectService"}}
        emit(args, envelope)
        return error.exit_code


if __name__ == "__main__":
    sys.exit(main())
