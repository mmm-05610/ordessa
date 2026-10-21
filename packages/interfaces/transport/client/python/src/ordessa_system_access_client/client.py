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


def profile_schema():
    value=_schema_mirror('sdk-contract-catalog.json')
    return value['schema']['profileFormat']


def _schema_mirror(filename):
    try:
        value=parse_json(files('ordessa_system_access_client').joinpath(filename).read_bytes())
        encoded=json.dumps(value['schema'],sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False).encode()
        if value['schemaDigest']!='sha256:'+hashlib.sha256(encoded).hexdigest():raise ValueError('digest')
        return value
    except (OSError,ValueError,KeyError,TypeError):
        raise ClientError('CLIENT_SCHEMA_UNAVAILABLE','Current SDK data schema unavailable',4) from None


def profile_ref_valid(value):
    """Validate only the schema shipped from the public core authority."""
    schema = profile_schema()["profileRef"]
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


#: A configured token file is a locator, never a secret in the configuration.
_MAX_TOKEN_BYTES = 4096


def read_token_file(path: str) -> str:
    """Read one private token file: regular, no symlink, mode 0600, printable ASCII.

    The Server writes this file itself (auto-generated on first start); a caller
    only ever names its path. A group/other-accessible or oversized file is
    refused rather than trimmed: silently accepting it would widen who can use
    the instance.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise ClientError("TOKEN_UNAVAILABLE", "The configured token file is unavailable", 3) from None
    with os.fdopen(fd, "rb") as stream:
        mode = os.fstat(stream.fileno()).st_mode
        if not stat.S_ISREG(mode) or mode & 0o077:
            raise ClientError("TOKEN_PERMISSIONS", "The token file must be a private regular file (0600)", 3)
        raw = stream.read(_MAX_TOKEN_BYTES + 1)
    if len(raw) > _MAX_TOKEN_BYTES:
        raise ClientError("TOKEN_UNAVAILABLE", "The token file is oversized", 3)
    try:
        token = raw.decode("ascii").strip()
    except UnicodeDecodeError:
        raise ClientError("TOKEN_UNAVAILABLE", "The token file is not ASCII", 3) from None
    if not token or any(ord(char) < 33 or ord(char) > 126 for char in token):
        raise ClientError("TOKEN_UNAVAILABLE", "The token file has no usable token value", 3)
    return token


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
                    or not isinstance(entry, dict)
                    or set(entry) not in ({"endpoint", "tokenEnv"}, {"endpoint", "tokenFile"})):
                raise ValueError("service shape; endpoint plus exactly one of tokenEnv/tokenFile")
            validate_endpoint(entry["endpoint"])
            if "tokenEnv" in entry:
                if not isinstance(entry["tokenEnv"], str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", entry["tokenEnv"]):
                    raise ValueError("token environment name")
            elif not isinstance(entry["tokenFile"], str) or not os.path.isabs(entry["tokenFile"]):
                raise ValueError("token file must be an absolute path")
        entry = config["services"].get(alias)
        if entry is None:
            raise ClientError("SERVICE_NOT_CONFIGURED", "Selected service is not configured", 2)
        if "tokenFile" in entry:
            return Service(alias, entry["endpoint"].rstrip("/"), read_token_file(entry["tokenFile"]))
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


class CapabilityClient:
    def __init__(self, service: Service, *, timeout: float = 10):
        self.service, self.timeout = service, timeout
        # Disable ambient proxies to prevent handing local bearer tokens to them.
        self.opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))

    def _call(self, method: str, params: dict, request_id: str, *, effectful: bool = False):
        if method not in ("operations.call","operations.describe","capabilities.list"):
            raise ClientError("PARAMETER_INVALID", "Invalid wire method", 2)
        body = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}, allow_nan=False).encode()
        if len(body)>MAX_BYTES or self.service.token in body.decode():
            raise ClientError('PARAMETER_INVALID','Request oversized or contains authentication material',2)
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
            # Frozen §2 observation mappings: a missing reference or an
            # unproven observation are typed refusals, never a green answer.
            if error["code"] == "NOT_FOUND":
                raise ClientError("OPERATION_NOT_FOUND", "Service did not find the requested operation reference", 4)
            if error["code"] == "UNAVAILABLE":
                raise ClientError("SERVICE_UNAVAILABLE", "Core observation could not be completed", 4)
            raise ClientError("AUTHORIZATION_REFUSED" if authorization else "WIRE_REFUSED", "Service refused the wire request", 3 if authorization else 4)
        return result["result"]


    def _envelope(self,method,params,request_id,*,effectful=False):
        value=self._call(method,params,request_id,effectful=effectful)
        expected={'apiVersion','requestId','command','status','data','error','operationRef','evidenceRefs'}
        if (type(value) is not dict or set(value)!=expected or value['apiVersion']!='agent-tools/1'
                or value['requestId']!=request_id or value['command']!=params.get('operationId',method)
                or value['status'] not in ('completed','accepted','refused','unknown')
                or value['data'] is not None and type(value['data']) is not dict
                or type(value['evidenceRefs']) is not list
                or any(type(x) is not str for x in value['evidenceRefs'])
                or value['operationRef'] is not None and type(value['operationRef']) is not str
                or self.service.token in json.dumps(value)):
            raise ClientError('OUTCOME_UNKNOWN' if effectful else 'WIRE_RESPONSE_INVALID','Invalid capability envelope',6 if effectful else 4)
        error=value['error']
        if error is not None and (type(error) is not dict or set(error)!={'code','message','retryable'}
                or type(error['code']) is not str or type(error['message']) is not str or type(error['retryable']) is not bool):
            raise ClientError('OUTCOME_UNKNOWN' if effectful else 'WIRE_RESPONSE_INVALID','Invalid capability error',6 if effectful else 4)
        allowed_errors={'INVALID_INPUT','AUTHORITY_UNAVAILABLE','PERMISSION_DENIED','ENDPOINT_UNAVAILABLE','CAPABILITY_UNSUPPORTED','CONFLICT','PROTOCOL_INVALID','PROVIDER_UNAVAILABLE','EFFECT_UNKNOWN','OBSERVATION_TIMEOUT','CLEANUP_PENDING'}
        if error is not None:
            if error['code'] not in allowed_errors:
                raise ClientError('OUTCOME_UNKNOWN' if effectful else 'WIRE_RESPONSE_INVALID','Unsupported capability error',6 if effectful else 4)
            value={**value,'error':{**error,'message':'Capability operation did not complete'}}
        if (value['status']=='refused' and error is None or value['status'] in ('completed','accepted') and error is not None):
            raise ClientError('OUTCOME_UNKNOWN' if effectful else 'WIRE_RESPONSE_INVALID','Conflicting capability result',6 if effectful else 4)
        return value

    def capabilities(self,request_id):
        return self._envelope('capabilities.list',{},request_id)

    def describe(self,operation_id,request_id):
        return self._envelope('operations.describe',{'operationId':operation_id},request_id)

    def invoke(self,operation_id,inputs,request_id,*,effectful=True):
        if (type(operation_id) is not str or not re.fullmatch(r'[a-z][a-zA-Z0-9-]*(\.[a-z][a-zA-Z0-9-]*)+',operation_id)
                or type(inputs) is not dict):
            raise ClientError('PARAMETER_INVALID','Invalid capability invocation',2)
        return self._envelope('operations.call',{'operationId':operation_id,'input':inputs},request_id,effectful=effectful)

    def profile_capabilities(self,request_id,required_operation):
        envelope=self.invoke('agents.profiles.capabilities',{},request_id,effectful=False)
        if envelope['status']!='completed':
            raise ClientError('CORE_API_UNAVAILABLE','Original Profile capability unavailable',4)
        value=envelope['data'];schema=profile_schema()
        encoded=json.dumps(schema,sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False).encode()
        if (type(value) is not dict or set(value)!={'contractVersion','schema','schemaDigest','environmentNamespace','supports','supportedMethods'}
                or value['contractVersion']!='profile-json/1' or value['schema']!=schema
                or value['schemaDigest']!='sha256:'+hashlib.sha256(encoded).hexdigest()
                or type(value['environmentNamespace']) is not str or not value['environmentNamespace']
                or type(value['supports']) is not dict or value['supports'].get('profileCatalog') is not True
                or type(value['supportedMethods']) is not list or required_operation not in value['supportedMethods']
                or any(type(x) is not str or not x.startswith('agents.profiles.') for x in value['supportedMethods'])):
            raise ClientError('CORE_VERSION_UNSUPPORTED','Original Profile data schema/support mismatch',4)
        return value
