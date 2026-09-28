"""Controlled E2 infrastructure for the model-provider real application chain
(014 PB-3/PB-5; evidence level E2 per ``docs/design/model-provider/verification.md``).

Three pieces:

- :class:`FakeEndpoint` — a loopback HTTP server standing in for the upstream
  provider (openai-chat / openai-responses / anthropic-messages). It records
  every request's path, model and whether an auth header was PRESENT (never
  its value) — this is the downstream-routing evidence the verification matrix
  demands (``option ack``/config-file reads alone are not effect evidence).
- :class:`BrandInstance` — the controlled "native brand agent": a config-driven
  process simulation that reads its own generation files on every prompt and
  routes to whatever endpoint/model those files resolve, exactly like the real
  CLI reads its config. It supports session/new, controlled restart-resume
  (same native session id) and the session/new-impersonation negative.
- :class:`ControlledBrandRuntime` — the C4 ``ControlledRuntime`` behind one
  brand: capture/activate_generation/observe over a real harness
  ``ConfigurationApplicationService`` composition (build_runtime product host
  + the adapters plugin declared in ``ordessa_model_provider_adapters.plugin``).

Zero real-model calls, zero credentials: the fake endpoint never leaves
loopback and secrets travel as ``ref://`` references only (E3 stays forbidden).
"""
from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

from ordessa_harness_api import (
    AdapterContext, ApplicationTarget, Installation, TargetDescriptor,
    TargetHandle, VersionRange,
)
from ordessa_harness.application import (
    NativeActivationReceipt, NativeReadback, OperationJournal, RuntimeSnapshot,
)
from ordessa_harness.materialization import MergeAuthority, TargetAuthority

from ordessa_model_provider_adapters import bridge
from ordessa_model_provider_adapters.plugin import ModelProviderAdaptersPlugin

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.12 venv has tomllib
    import tomli as tomllib

#: Pinned native versions (t00-freeze §5; conformance SUPPORTED_VERSIONS).
NATIVE_VERSIONS = {"pi": (0, 5, 0), "codex": (1, 1, 14), "claude-code": (0, 81, 2)}

RESOURCE = {"pi": ("models.json",), "codex": ("config.toml",), "claude-code": ("settings.json",)}
CODEC = {"pi": "json", "codex": "toml", "claude-code": "json"}

ENV_HANDLE_SUFFIX = ".env"


class FakeEndpoint:
    """Loopback stand-in for the upstream provider; records routing facts."""

    def __init__(self):
        self.requests: list[dict[str, object]] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._make_handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def _make_handler(self):
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - http.server API
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                try:
                    payload = json.loads(body) if body else {}
                except ValueError:
                    payload = {}
                endpoint.requests.append({
                    "path": self.path,
                    "model": payload.get("model"),
                    "auth_present": bool(self.headers.get("Authorization")
                                         or self.headers.get("x-api-key")),
                })
                response = json.dumps({"id": "fake", "model": payload.get("model"),
                                       "output": [], "choices": []}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

            def log_message(self, *args):  # silence the test console
                pass

        return Handler


def initial_generation(brand: str, endpoint_url: str) -> dict:
    """The base config a fresh controlled instance boots with: the ``acme``
    provider config already provisioned on the fake endpoint (the honest E2
    setup for session-local semantics — the choice switches the session onto
    it), currently routed to ``legacy``/``m0``."""
    if brand == "pi":
        return {"providers": {"legacy": {"baseUrl": endpoint_url, "api": "openai-completions"},
                              "acme": {"baseUrl": endpoint_url, "api": "openai-completions"}},
                "session": {"model": "legacy/m0"}}
    if brand == "codex":
        return {"model_provider": "legacy", "model": "m0",
                "model_providers": {"legacy": {"name": "legacy", "base_url": endpoint_url,
                                               "wire_api": "chat", "env_key": "CODEX_API_KEY"},
                                    "acme": {"name": "acme", "base_url": endpoint_url,
                                             "wire_api": "chat", "env_key": "CODEX_API_KEY"}}}
    return {"env": {"ANTHROPIC_BASE_URL": endpoint_url}, "session": {"model": "legacy"}}


class BrandInstance:
    """The controlled native brand agent (config in → routed requests out)."""

    def __init__(self, brand: str, endpoint_url: str):
        self.brand = brand
        self.native_session_id = f"native-{brand}-{uuid4().hex[:8]}"
        self.files = {RESOURCE[brand][0]: _dump(brand, initial_generation(brand, endpoint_url))}
        self.generation_count = 0

    # -- the native lifecycle -------------------------------------------------

    def restart_onto(self, files: dict[str, bytes]) -> str:
        """Controlled restart onto a new private generation, resuming the SAME
        native session id (the MP-06 happy path)."""
        self.generation_count += 1
        self.files = dict(files)
        return self.native_session_id

    def session_new(self) -> str:
        """The MP-06 negative: a session/new must never impersonate resume —
        it mints a fresh native identity, which verify must refuse."""
        self.generation_count += 1
        self.native_session_id = f"native-{self.brand}-{uuid4().hex[:8]}"
        return self.native_session_id

    # -- config reading (what the real CLI does on every request) --------------

    def readback(self) -> dict[str, object]:
        doc = _parse(self.brand, self.files[RESOURCE[self.brand][0]])
        if self.brand == "pi":
            model = doc["session"]["model"]
            provider = model.split("/", 1)[0]
            return {"model": model, "provider": provider,
                    "endpoint": doc["providers"][provider]["baseUrl"]}
        if self.brand == "codex":
            provider = doc["model_provider"]
            return {"model": doc["model"], "provider": provider,
                    "endpoint": doc["model_providers"][provider]["base_url"]}
        return {"model": doc["session"]["model"], "provider": "anthropic",
                "endpoint": doc["env"]["ANTHROPIC_BASE_URL"]}

    def prompt(self, text: str) -> dict[str, object]:
        """One turn: resolve the CURRENT config and actually hit the endpoint."""
        state = self.readback()
        path = {"openai-chat": "/v1/chat/completions",
                "openai-responses": "/v1/responses",
                "anthropic-messages": "/v1/messages"}[self._protocol_of(state)]
        import urllib.request

        request = urllib.request.Request(
            state["endpoint"] + path,
            data=json.dumps({"model": _wire_model(self.brand, state), "prompt": text}).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer controlled-no-secret"},
            method="POST")
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
        return {"routed_model": state["model"], "routed_provider": state["provider"],
                "endpoint": state["endpoint"]}

    def _protocol_of(self, state: dict[str, object]) -> str:
        if self.brand == "pi":
            return "openai-chat"
        if self.brand == "codex":
            return "openai-responses"
        return "anthropic-messages"


def _dump(brand: str, doc: dict) -> bytes:
    if CODEC[brand] == "toml":
        import tomli_w
        return tomli_w.dumps(doc).encode("utf-8")
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _parse(brand: str, data: bytes) -> dict:
    if CODEC[brand] == "toml":
        return tomllib.loads(data.decode("utf-8"))
    return json.loads(data.decode("utf-8"))


def _wire_model(brand: str, state: dict[str, object]) -> str:
    model = str(state["model"])
    return model.split("/", 1)[1] if brand == "pi" and "/" in model else model


class ControlledBrandRuntime:
    """The C4 ControlledRuntime for one brand instance (capture/activate/observe)."""

    def __init__(self, brand: str, instance: BrandInstance, generation_root: Path):
        self.brand = brand
        self.instance = instance
        self.generation_root = generation_root
        self.generation_root.mkdir(parents=True)
        self.generation_root.chmod(0o700)
        self.revision = "base-0"
        self.apply_count = 0
        self.fail_after_effect = False
        self._last_receipt = None
        self._expected_session_id = instance.native_session_id
        file_handle = TargetHandle(bridge.HANDLE_IDS[brand], 7)
        env_handle = TargetHandle(bridge.HANDLE_IDS[brand] + ENV_HANDLE_SUFFIX, 7)
        self.file_descriptor = TargetDescriptor(
            file_handle, "file", CODEC[brand], "instance", self._allowed_fields(brand))
        self.env_descriptor = TargetDescriptor(
            env_handle, "environment", "environment", "instance",
            ((bridge.SECRET_SLOTS[brand],),))
        self.array_fields = {"pi": (("providers",),), "codex": (("model_providers",),),
                             "claude-code": ()}[brand]

    @staticmethod
    def _allowed_fields(brand: str) -> tuple[tuple[str, ...], ...]:
        if brand == "pi":
            return (("session", "model"), ("providers",))
        if brand == "codex":
            return (("model",), ("model_provider",), ("model_providers",))
        return (("session", "model"), ("env", "ANTHROPIC_BASE_URL"))

    # -- C4 ControlledRuntime protocol ----------------------------------------

    def capture(self, target: ApplicationTarget) -> RuntimeSnapshot:
        self._expected_session_id = self.instance.native_session_id
        resource = RESOURCE[self.brand]
        files = {resource: self.instance.files[resource[0]]}
        context = AdapterContext(
            (self.file_descriptor, self.env_descriptor),
            Installation(self.brand, NATIVE_VERSIONS[self.brand],
                         bridge.ADAPTER_VERSION, "controlled:installed"),
            bridge.ENTRY, "instance", "controlled:capability")
        authority = MergeAuthority((
            TargetAuthority(self.file_descriptor, resource, self.array_fields),
            TargetAuthority(self.env_descriptor, ("env",)),
        ))
        return RuntimeSnapshot(target, context, authority, files, {},
                               self.generation_root, _parse(self.brand, files[resource]),
                               self.revision, f"controlled:{self.brand}@"
                               + ".".join(map(str, NATIVE_VERSIONS[self.brand])),
                               1, "auth-1", "secret-ref-1")

    def activate_generation(self, operation_id, target, lease, manifest_digest):
        resource = RESOURCE[self.brand]
        files = {resource[0]: lease.read_bytes(resource)}
        if self.fail_after_effect:
            self.instance.files = files
            self.revision = f"applied-{self.instance.generation_count}"
            raise OSError("controlled endpoint lost acknowledgement after effect")
        session_id = self.instance.restart_onto(files)
        self.apply_count += 1
        self.revision = f"applied-{self.instance.generation_count}"
        receipt = NativeActivationReceipt(operation_id, target, manifest_digest, session_id,
                                          self.revision,
                                          f"controlled:native-owner:{operation_id}")
        self._last_receipt = receipt
        return receipt

    def observe(self, target: ApplicationTarget) -> NativeReadback:
        resource = RESOURCE[self.brand]
        data = self.instance.files[resource[0]]
        state = self.instance.readback()
        observed = {"readback": {"model": state["model"], "provider": state["provider"]},
                    "desired_model": _desired_model(self.brand, data),
                    "native_session_id": self.instance.native_session_id,
                    "expected_native_session_id": self._expected_session_id}
        digest = hashlib.sha256(data).hexdigest()
        return NativeReadback(target, self.instance.native_session_id, self.revision,
                              observed, ((resource, digest),),
                              f"controlled:readback:{digest}", ("private-generation",),
                              self._last_receipt)


def _desired_model(brand: str, data: bytes) -> object:
    doc = _parse(brand, data)
    if brand == "codex":
        return doc["model"]
    return doc["session"]["model"]


class ControlledPermit:
    """One-use signed permit minted per operation key; records every verify."""

    def __init__(self, principal="controlled"):
        self.principal = principal
        self.minted: dict[str, str] = {}
        self.verified: list[str] = []
        self.expired_keys: set[str] = set()

    def mint(self, operation_key: str) -> str:
        permit = f"signed:controlled:{operation_key}"
        self.minted[operation_key] = permit
        return permit

    def expire(self, operation_key: str) -> None:
        self.expired_keys.add(operation_key)

    def verify(self, principal, target, plan, operation_key, permit) -> bool:
        self.verified.append(operation_key)
        if operation_key in self.expired_keys:
            return False
        return (principal == self.principal
                and self.minted.get(operation_key) == permit)


TARGET = ApplicationTarget("test-server", "e2e-session", "test-channel", 7)


class ControlledComposition:
    """One brand's full controlled application chain (host/adapters/runtime/C4)."""

    def __init__(self, brand: str, tmp_path: Path):
        from ordessa_server.bootstrap import build_runtime

        self.brand = brand
        self.product = build_runtime(tmp_path / "product")
        self.host = self.product.plugin_host
        self.host.activate(ModelProviderAdaptersPlugin())
        self.endpoint = FakeEndpoint()
        self.endpoint.start()
        self.instance = BrandInstance(brand, self.endpoint.url)
        self.runtime = ControlledBrandRuntime(
            brand, self.instance, tmp_path / "generations" / brand)
        self.permit = ControlledPermit()
        operations = tmp_path / "operations" / brand
        operations.mkdir(parents=True)
        self.journal = OperationJournal(operations / "operations.sqlite")
        from ordessa_harness.application import ConfigurationApplicationService

        self.service = ConfigurationApplicationService(
            principal="controlled", target=TARGET, carrier=self.host,
            runtime=self.runtime, permits=self.permit, journal=self.journal)
        self.base = self.instance.readback()

    def stop(self) -> None:
        self.endpoint.stop()
        self.product.stop()

    # -- helpers --------------------------------------------------------------

    def choice_payload(self, provider="acme", model="m1", protocol=None,
                       endpoint=None, credential_ref=None, brand_fields=None) -> dict:
        protocols = {"pi": "openai-chat", "codex": "openai-responses",
                     "claude-code": "anthropic-messages"}
        if self.brand == "pi":
            model = model if "/" in model else f"{provider}/{model}"
        payload = {
            "provider": provider, "model": model,
            "endpoint": endpoint if endpoint is not None else self.endpoint.url,
            "protocol": protocol or protocols[self.brand],
            "credentialRef": credential_ref,
        }
        if brand_fields:
            payload["brandFields"] = brand_fields
        return payload

    def restart_resumed(self, payload: dict) -> bool:
        return bridge.reconfiguration_for(self.brand, payload) == "restart-resume"

    def prompt_route(self, text="hello") -> dict[str, object]:
        return self.instance.prompt(text)
