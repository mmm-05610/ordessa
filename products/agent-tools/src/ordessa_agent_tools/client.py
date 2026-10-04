"""Bounded, non-retrying wire/1 transport and explicit local configuration."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import http.client
from importlib.resources import files
import hashlib
import json
import os
import re
import socket
import ssl
import stat
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener, HTTPSHandler

MAX_BYTES = 1024 * 1024


def core_schema():
    try:
        contract = parse_json(files("ordessa_agent_tools").joinpath("schema.json").read_bytes())
        encoded = json.dumps(contract["schema"], sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        if "sha256:" + hashlib.sha256(encoded.encode()).hexdigest() != contract["schemaDigest"]:
            raise ValueError("digest")
        return contract
    except (OSError, ValueError, KeyError, TypeError):
        raise ClientError("CLIENT_SCHEMA_UNAVAILABLE", "Client core schema could not be verified", 4) from None


def profile_ref_valid(value):
    """Validate only the schema shipped from the public core authority."""
    schema = core_schema()["schema"]["profileRef"]
    if not isinstance(value, dict) or set(value) != set(schema["required"]):
        return False
    for name, shape in schema["properties"].items():
        item = value[name]
        if shape["type"] == "integer":
            if type(item) is not int or item < shape["minimum"]:
                return False
        elif not isinstance(item, str) or not re.fullmatch(shape["pattern"], item):
            return False
    return True


class ClientError(Exception):
    def __init__(self, code: str, message: str, exit_code: int):
        super().__init__(message)
        self.code, self.message, self.exit_code = code, message, exit_code


def parse_json(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate member")
            result[key] = value
        return result
    def constant(_value):
        raise ValueError("non-finite JSON")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    # Overflowed numeric exponents and escaped lone surrogates are also
    # invalid finite UTF-8 values, even though json.loads accepts them.
    json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    return value


@dataclass(frozen=True)
class Service:
    alias: str
    endpoint: str
    token: str


def load_service(path: str, alias: str) -> Service:
    try:
        # Refuse symlink substitution and inspect the same descriptor we read.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            mode = os.fstat(stream.fileno()).st_mode
            if not stat.S_ISREG(mode) or mode & (stat.S_IWGRP | stat.S_IWOTH):
                raise ClientError("CONFIG_PERMISSIONS", "Configuration must be a regular file without group or other write access", 2)
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("oversized configuration")
        config = parse_json(raw)
        if not isinstance(config, dict) or set(config) != {"services"} or not isinstance(config["services"], dict):
            raise ValueError("configuration shape")
        for name, entry in config["services"].items():
            if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", name)
                    or not isinstance(entry, dict) or set(entry) != {"endpoint", "tokenEnv"}):
                raise ValueError("service shape; plaintext secrets are forbidden")
            validate_endpoint(entry["endpoint"])
            if not isinstance(entry["tokenEnv"], str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", entry["tokenEnv"]):
                raise ValueError("token environment name")
        entry = config["services"].get(alias)
        if entry is None:
            raise ClientError("SERVICE_NOT_CONFIGURED", "Selected service is not configured", 2)
        token = os.environ.get(entry["tokenEnv"], "")
        if not token or any(ord(char) < 33 or ord(char) > 126 for char in token):
            raise ClientError("TOKEN_UNAVAILABLE", "A valid token environment value is required", 3)
        return Service(alias, entry["endpoint"].rstrip("/"), token)
    except ClientError:
        raise
    except (OSError, ValueError, TypeError, RecursionError):
        raise ClientError("CONFIG_INVALID", "Configuration is unreadable or invalid; use endpoint and tokenEnv only", 2) from None


def validate_endpoint(value):
    if not isinstance(value, str) or any(char.isspace() or ord(char) < 32 for char in value):
        raise ValueError("endpoint")
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
        raise ValueError("endpoint")
    parsed.port  # Validate malformed/out-of-range ports without exposing them.
    if parsed.scheme == "http":
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            # Avoid DNS rebinding: insecure HTTP requires a loopback literal.
            loopback = False
        if not loopback:
            raise ValueError("HTTP requires a loopback IP literal; use TLS elsewhere")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class WireClient:
    def __init__(self, service: Service, *, timeout: float = 10):
        self.service, self.timeout = service, timeout
        # Disable ambient proxies to prevent handing local bearer tokens to them.
        self.opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))

    def call(self, method: str, params: dict, request_id: str, *, effectful: bool = False):
        if not re.fullmatch(r"[a-z][a-zA-Z0-9]*(\.[a-z][a-zA-Z0-9]*)+", method):
            raise ClientError("PARAMETER_INVALID", "Invalid wire method", 2)
        body = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}, allow_nan=False).encode()
        request = Request(self.service.endpoint + "/wire/v1/" + method, data=body,
                          headers={"Authorization": "Bearer " + self.service.token, "Content-Type": "application/json"}, method="POST")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ValueError("response oversized")
                result = parse_json(raw)
        except HTTPError as error:
            status = error.code
            error.close()
            if status in {401, 403}:
                raise ClientError("AUTHORIZATION_REFUSED", "Service authentication or authorization was refused", 3) from None
            if 300 <= status < 400:
                raise ClientError("REDIRECT_REFUSED", "Service redirects are refused", 4) from None
            raise ClientError("SERVICE_UNAVAILABLE", "Service did not provide a usable response", 6 if effectful else 4) from None
        except (socket.timeout, TimeoutError):
            raise ClientError("OUTCOME_UNKNOWN" if effectful else "OBSERVATION_TIMEOUT", "Response was not observed before the timeout", 6 if effectful else 7) from None
        except URLError as error:
            if isinstance(error.reason, (socket.timeout, TimeoutError)):
                raise ClientError("OUTCOME_UNKNOWN" if effectful else "OBSERVATION_TIMEOUT", "Response was not observed before the timeout", 6 if effectful else 7) from None
            raise ClientError("OUTCOME_UNKNOWN" if effectful else "SERVICE_UNAVAILABLE", "Service response could not be observed", 6 if effectful else 4) from None
        except (OSError, http.client.HTTPException):
            raise ClientError("OUTCOME_UNKNOWN" if effectful else "SERVICE_UNAVAILABLE", "Service response could not be observed", 6 if effectful else 4) from None
        except (ValueError, RecursionError):
            raise ClientError("OUTCOME_UNKNOWN" if effectful else "WIRE_RESPONSE_INVALID", "Service response could not be validated", 6 if effectful else 4) from None
        if (not isinstance(result, dict) or result.get("jsonrpc") != "2.0"
                or type(result.get("id")) is not str or result["id"] != request_id
                or set(result) not in ({"jsonrpc", "id", "result"}, {"jsonrpc", "id", "error"})):
            raise ClientError("OUTCOME_UNKNOWN" if effectful else "WIRE_RESPONSE_INVALID", "Service returned an invalid wire envelope", 6 if effectful else 4)
        if "error" in result:
            error = result["error"]
            if not isinstance(error, dict) or not isinstance(error.get("code"), (str, int)) or isinstance(error.get("code"), bool):
                raise ClientError("OUTCOME_UNKNOWN" if effectful else "WIRE_RESPONSE_INVALID", "Service returned an invalid wire error", 6 if effectful else 4)
            # Never expose server messages, details, or untrusted error codes.
            authorization = error["code"] in {"UNAUTHENTICATED", "FORBIDDEN"}
            if error["code"] == "OUTCOME_UNKNOWN":
                raise ClientError("OUTCOME_UNKNOWN", "Service reports an unknown outcome; query existing evidence", 6)
            if error["code"] in {"CONFLICT_VERSION", "CONFLICT_REQUEST", "CONFLICT_REFERENCE"}:
                raise ClientError("PRECONDITION_CONFLICT", "Service refused conflicting revision, request, or target preconditions", 5)
            if error["code"] == "INVALID_REQUEST":
                raise ClientError("PARAMETER_INVALID", "Service refused request parameters", 2)
            if effectful and not authorization and error["code"] not in {"CAPABILITY_UNSUPPORTED", "NOT_FOUND", "APPROVAL_INVALID"}:
                raise ClientError("OUTCOME_UNKNOWN", "Service could not confirm the write outcome; query existing evidence", 6)
            raise ClientError("AUTHORIZATION_REFUSED" if authorization else "WIRE_REFUSED", "Service refused the wire request", 3 if authorization else 4)
        return result["result"]

    def core_call(self, method, params, request_id):
        definition = core_schema()["schema"]["methods"].get(method)
        if definition is None or not set(definition["required"]) <= params.keys() or set(params) - set(definition["required"] + definition["optional"]):
            raise ClientError("PARAMETER_INVALID", "Parameters do not match the published core schema", 2)
        return self.call(method, params, request_id, effectful=definition["effectful"])

    def negotiate(self, request_id):
        expected = core_schema()
        result = self.core_call("agents.capabilities", {}, request_id)
        if (not isinstance(result, dict) or set(result) != {"contractVersion", "schemaDigest", "schema", "environmentNamespace", "supports"}
                or result["contractVersion"] != expected["schema"]["contractVersion"]
                or result["schemaDigest"] != expected["schemaDigest"] or result["schema"] != expected["schema"]):
            raise ClientError("CORE_VERSION_UNSUPPORTED", "Agent core version or schema does not match this client", 4)
        supports = result["supports"]
        if (not isinstance(supports, dict) or set(supports) != {"profileCatalog", "nodes", "managedInput"}
                or any(type(value) is not bool for value in supports.values())
                or supports["nodes"] is not False or supports["managedInput"] is not False
                or not isinstance(result["environmentNamespace"], str) or not result["environmentNamespace"]):
            raise ClientError("CORE_RESPONSE_INVALID", "Agent core capability schema is invalid", 4)
        if self.service.token in json.dumps(result):
            raise ClientError("CORE_RESPONSE_INVALID", "Agent core returned an unsafe response", 4)
        return {key: result[key] for key in ("contractVersion", "schemaDigest", "environmentNamespace", "supports")}

    def hello(self, request_id: str):
        result = self.call("server.hello", {"clientVersions": ["wire/1"], "clientPresentationSupports": []}, request_id)
        if (not isinstance(result, dict) or not isinstance(result.get("serverId"), str) or not result["serverId"]
                or not isinstance(result.get("protocolVersion"), str)
                or not isinstance(result.get("capabilities"), list) or not isinstance(result.get("auth"), dict)
                or type(result["auth"].get("required")) is not bool):
            raise ClientError("WIRE_RESPONSE_INVALID", "Service discovery schema is invalid", 4)
        if result["protocolVersion"] != "wire/1":
            raise ClientError("WIRE_VERSION_UNSUPPORTED", "Service does not provide wire/1", 4)
        if result["auth"]["required"] and result["auth"].get("schemes") != ["session_token"]:
            raise ClientError("AUTH_SCHEME_UNSUPPORTED", "Service authentication scheme is unsupported", 4)
        capabilities, seen = [], set()
        for entry in result["capabilities"]:
            if (not isinstance(entry, dict) or set(entry) - {"id", "supported", "reason"}
                    or not isinstance(entry.get("id"), str)
                    or not re.fullmatch(r"[a-z][a-zA-Z0-9]*(\.[a-zA-Z][a-zA-Z0-9]*)*", entry["id"])
                    or entry["id"] in seen or type(entry.get("supported")) is not bool
                    or self.service.token in entry["id"]
                    or (not entry["supported"] and not isinstance(entry.get("reason"), str))):
                raise ClientError("WIRE_RESPONSE_INVALID", "Service capability schema is invalid", 4)
            seen.add(entry["id"])
            # Reason text is untrusted and may contain credentials.
            capabilities.append({"id": entry["id"], "supported": entry["supported"]})
        return {"protocolVersion": "wire/1", "capabilities": capabilities}
