"""Order 55: the bounded provider probes — pull the model list, test the wire.

Two one-shot outbound actions, both bounded and auditable:

* ``pull_models`` — GET ``{base_url}/models`` and return the parsed model ids;
* ``probe_connection`` — the same lightweight request used only for its status.

Hard boundaries (order 55 §1/§2):

* **https only**, except an explicit loopback exception (``http`` to
  ``127.0.0.1``/``localhost``/``::1``) so tests can run against a local fake;
  private-network addresses that are not loopback are refused (no SSRF), and a
  *name* is refused by the addresses it resolves to, not by the string;
* that one request goes **to the declared endpoint and nowhere else**: a
  redirect is not followed and a system proxy is not used, because either one
  would put a different server - and the credential header - in its place;
* connection and total deadlines, a response-size cap and an entry cap;
* the credential lives only in the request header inside this call — never in
  argv, never in a log line, never in an error message (errors quote the
  status code, not the request);
* **no probe result is ever written into a record**: the caller shows the
  list, and the user decides what to save.
"""
from __future__ import annotations

import ipaddress
import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

#: One-shot outbound budget.
CONNECT_TIMEOUT_SECONDS = 10.0
TOTAL_TIMEOUT_SECONDS = 30.0
MAX_RESPONSE_BYTES = 1 * 1024 * 1024
MAX_MODEL_ENTRIES = 512

#: The loopback names the https-only rule exempts for local fakes.
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class ProbeError(RuntimeError):
    """A typed probe refusal/failure; the message never carries the request."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class ProbeResult:
    status: str            # "ok" for pull, "reachable"/"unreachable" for test
    detail: str            # typed code or short human fact (no headers, no body)
    models: tuple[str, ...] = ()


def _validate_endpoint(base_url: str) -> tuple[str, str]:
    """Return (normalized base, host), refusing anything the order forbids.

    https is the rule; http is allowed only to an explicit loopback host.
    A non-loopback private address is refused: the probe is one outbound
    request to the *declared* endpoint, not a port scanner. The check looks at
    the addresses a host resolves to rather than the spelling of the host,
    because a name and the number behind it are the same endpoint to a scanner.
    """
    parsed = urlsplit(base_url if "://" in base_url else f"https://{base_url}")
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if scheme not in {"https", "http"} or not host:
        raise ProbeError("PROBE_ENDPOINT_BLOCKED", "the endpoint must be an http(s) URL with a host")
    if scheme == "http" and host not in _LOOPBACK_HOSTS:
        raise ProbeError("PROBE_ENDPOINT_BLOCKED", "plain http is allowed only to a loopback host")
    try:
        port = parsed.port or (443 if scheme == "https" else 80)
        resolved = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        # The name is simply not there. That is the outcome this function used
        # to reach one layer later, through the connect attempt; keeping the
        # code means an unresolvable host still answers PROBE_UNREACHABLE.
        raise ProbeError("PROBE_UNREACHABLE", "the endpoint's name does not resolve") from error
    #: Every answer, not the first one: a name that offers a public address and
    #: a private one is exactly how a "resolved fine" check gets walked past.
    for entry in resolved:
        address = ipaddress.ip_address(entry[4][0].split("%")[0])
        if address.is_loopback:
            continue
        if (address.is_private or address.is_reserved
                or address.is_multicast or address.is_link_local):
            raise ProbeError(
                "PROBE_ENDPOINT_BLOCKED",
                "private network addresses are not probeable endpoints",
            )
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
    return base, host


class _OneShotRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse to follow: a redirect is a *second* endpoint, not the declared one.

    Raising the ``HTTPError`` from here - instead of returning a new request -
    means no second connection is ever attempted, so the caller's single
    request stays single. ``_fetch_models_response`` then types it.
    """

    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise urllib.error.HTTPError(newurl, code, message, headers, fp)


#: The opener is built once, at import, from these two facts:
#: no redirects, and no system proxy. The second is not belt-and-braces -
#: with the environment's ``http_proxy`` set, ``urlopen`` hands the request
#: (absolute URI and ``Authorization`` header, in clear, for ``http``) to that
#: intermediary and reports the exchange as a probe of the *declared* endpoint.
#: A one-shot probe to a declared endpoint has to choose its own next hop.
_OPENER = urllib.request.build_opener(
    _OneShotRedirect(), urllib.request.ProxyHandler({}),
)


def _typed_http_error(error: urllib.error.HTTPError) -> ProbeError:
    if error.code in {301, 302, 303, 307, 308}:
        return ProbeError(
            "PROBE_ENDPOINT_BLOCKED",
            "the endpoint answered with a redirect; a probe makes one request to the declared endpoint",
        )
    if error.code in {401, 403}:
        return ProbeError("PROBE_AUTH_FAILED", "the endpoint rejected the credential")
    return ProbeError("PROBE_HTTP_ERROR", f"the endpoint answered with HTTP {error.code}")


def _open_request(request: urllib.request.Request, timeout: float):
    """The one network touch. A module-level function so tests (and only
    tests) can substitute the transport without patching the stdlib."""
    return _OPENER.open(request, timeout=timeout)


def _fetch_models_response(base_url: str, api_key: str | None) -> bytes:
    url = f"{base_url}/models"
    request = urllib.request.Request(url, method="GET")
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    request.add_header("Accept", "application/json")
    deadline = time.monotonic() + TOTAL_TIMEOUT_SECONDS
    try:
        with _open_request(request, CONNECT_TIMEOUT_SECONDS) as response:
            # The socket timeout bounds each read; the total deadline bounds a
            # slow-drip answer, so the probe always returns within the budget.
            chunks: list[bytes] = []
            read = 0
            while read <= MAX_RESPONSE_BYTES:
                if time.monotonic() > deadline:
                    raise ProbeError("PROBE_TIMEOUT", "the endpoint did not answer in time")
                chunk = response.read(min(65536, MAX_RESPONSE_BYTES + 1 - read))
                if not chunk:
                    break
                chunks.append(chunk)
                read += len(chunk)
            return b"".join(chunks)
    except urllib.error.HTTPError as error:
        raise _typed_http_error(error) from error
    except urllib.error.URLError as error:
        reason = getattr(error, "reason", None)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason):
            raise ProbeError("PROBE_TIMEOUT", "the endpoint did not answer in time") from error
        raise ProbeError("PROBE_UNREACHABLE", "the endpoint could not be reached") from error
    except TimeoutError as error:
        raise ProbeError("PROBE_TIMEOUT", "the endpoint did not answer in time") from error


def _parse_models_payload(content: bytes) -> tuple[str, ...]:
    if len(content) > MAX_RESPONSE_BYTES:
        raise ProbeError("PROBE_RESPONSE_TOO_LARGE", "the response exceeds the size cap")
    try:
        document = json.loads(content.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise ProbeError("PROBE_FORMAT_INVALID", "the response is not a JSON object") from error
    if not isinstance(document, dict):
        raise ProbeError("PROBE_FORMAT_INVALID", "the response is not a JSON object")
    entries = document.get("data")
    if not isinstance(entries, list):
        raise ProbeError("PROBE_FORMAT_INVALID", 'the response carries no "data" list')
    models: list[str] = []
    for entry in entries[:MAX_MODEL_ENTRIES]:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            models.append(entry["id"])
    if len(entries) > MAX_MODEL_ENTRIES:
        models = models[:MAX_MODEL_ENTRIES]
    return tuple(models)


def pull_models(base_url: str, api_key: str | None) -> ProbeResult:
    """Fetch and parse the model list; bounded, one request, nothing stored."""
    base, _host = _validate_endpoint(base_url)
    content = _fetch_models_response(base, api_key)
    models = _parse_models_payload(content)
    return ProbeResult(status="ok", detail=f"{len(models)} model ids", models=models)


def probe_connection(base_url: str, api_key: str | None) -> ProbeResult:
    """A lightweight reachability check: same endpoint, status-only verdict."""
    base, _host = _validate_endpoint(base_url)
    try:
        content = _fetch_models_response(base, api_key)
    except ProbeError as error:
        if error.code == "PROBE_AUTH_FAILED":
            # Reachable but unauthorized is still "the endpoint answered".
            return ProbeResult(
                status="reachable", detail="endpoint reachable; credential rejected",
            )
        return ProbeResult(status="unreachable", detail=error.code)
    return ProbeResult(
        status="reachable" if content else "unreachable", detail="endpoint answered",
    )


__all__ = [
    "MAX_MODEL_ENTRIES",
    "MAX_RESPONSE_BYTES",
    "ProbeError",
    "ProbeResult",
    "pull_models",
    "probe_connection",
]
