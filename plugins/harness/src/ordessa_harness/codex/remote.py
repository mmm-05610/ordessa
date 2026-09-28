"""Codex-owned plan, decoder, continuation, and native-state classification for WSL."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from pacthold_runtime_compat.resource_contracts import (
    AgentBoxProfileV1,
    CredentialRefV1,
    PromptFragmentV1,
    WorkspaceV1,
)
from pacthold.work_core import (
    ExecutionStartReceipt,
    ExecutionStartRequest,
    ProviderDescriptor,
)

from .contracts import CodexContinuationV1


MAX_PROMPT_BYTES = 4 * 1024
MAX_EVENT_LINE_BYTES = 256 * 1024
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
_SESSION_PATH = re.compile(r"^sessions(?:/[A-Za-z0-9._-]+)+\.jsonl$")
_DEEPSEEK_API_KEY = re.compile(rb"^sk-[A-Za-z0-9_-]{8,248}$")
_DEEPSEEK_MODELS = frozenset({"deepseek-flash"})
_DEEPSEEK_CATALOG_PATH = Path(__file__).with_name("deepseek-models.json")
_DEEPSEEK_SIDECAR_CONFIG_PATH = Path(__file__).with_name("deepseek-sidecar-config.toml")
_DEEPSEEK_CATALOG_CANONICAL_SHA256 = "738ac1b92a557273ab0c128b286967e54cd993c9e901f93869f7e73581d591fa"


def _deepseek_model_catalog() -> bytes:
    """Return the exact official 1.3.0 catalog from the checked-in asset."""
    content = _DEEPSEEK_CATALOG_PATH.read_bytes()
    catalog = json.loads(content)
    if {item.get("slug") for item in catalog.get("models", [])} != {"deepseek-flash", "deepseek-v4-pro"}:
        raise ValueError("CODEX_DEEPSEEK_CATALOG_INVALID")
    canonical = json.dumps(catalog, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    if hashlib.sha256(canonical).hexdigest() != _DEEPSEEK_CATALOG_CANONICAL_SHA256:
        raise ValueError("CODEX_DEEPSEEK_CATALOG_DIGEST_MISMATCH")
    return content


@dataclass(frozen=True)
class RemoteCodexPlan:
    command: tuple[str, ...]
    environment: Mapping[str, str]
    stdin: bytes = field(repr=False)
    model: str
    provider: str
    continuation_thread_id: str | None
    timeout_ms: int = 120_000


@dataclass(frozen=True)
class RemoteCodexCredentialProjection:
    target: str
    content: bytes = field(repr=False)
    view_files: Mapping[str, bytes] = field(default_factory=dict, repr=False)


def build_acp_sidecar_projection(catalog_path: str) -> RemoteCodexCredentialProjection:
    """Build the non-sensitive DeepSeek config for the production ACP sidecar.

    The catalog is mounted separately as an ordinary read-only view.  This
    interface deliberately accepts no credential material and never emits the
    legacy bearer-token setting used by the exec projection.
    """
    if catalog_path != "/tmp/agentbox-home/models.json":
        raise ValueError("CODEX_CATALOG_PATH_INVALID")
    path = Path(catalog_path)
    if (not path.is_absolute() or str(path) != catalog_path
            or any(part in {"", ".", ".."} for part in path.parts)):
        raise ValueError("CODEX_CATALOG_PATH_INVALID")
    config = _DEEPSEEK_SIDECAR_CONFIG_PATH.read_bytes()
    return RemoteCodexCredentialProjection(
        "/tmp/agentbox-home/config.toml", config, {"models.json": _deepseek_model_catalog()},
    )


@dataclass(frozen=True)
class CodexDecodedResult:
    thread_id: str | None
    messages: tuple[str, ...]
    completed: bool
    error_code: str | None
    usage: Mapping[str, int]


def validate_remote_configuration(value: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping) or set(value) - {"model", "provider", "reasoning_effort"}:
        raise ValueError("CODEX_REMOTE_CONFIGURATION_INVALID")
    model = value.get("model")
    if not isinstance(model, str) or not _MODEL.fullmatch(model):
        raise ValueError("CODEX_MODEL_REQUIRED")
    effort = value.get("reasoning_effort", "low")
    if effort not in _EFFORTS:
        raise ValueError("CODEX_REASONING_EFFORT_INVALID")
    provider = value.get("provider", "openai")
    if provider not in {"openai", "deepseek"}:
        raise ValueError("CODEX_PROVIDER_INVALID")
    if provider == "deepseek":
        if model not in _DEEPSEEK_MODELS:
            raise ValueError("CODEX_DEEPSEEK_MODEL_INVALID")
        if effort not in {"low", "high", "max"}:
            raise ValueError("CODEX_DEEPSEEK_REASONING_EFFORT_INVALID")


def build_remote_plan(
    configuration: Mapping[str, Any], prompt: str,
    continuation: CodexContinuationV1 | None,
) -> RemoteCodexPlan:
    validate_remote_configuration(configuration)
    encoded = prompt.encode("utf-8")
    if not encoded or len(encoded) > MAX_PROMPT_BYTES:
        raise ValueError("CODEX_PROMPT_OUTSIDE_BOUND")
    model = str(configuration["model"])
    effort = str(configuration.get("reasoning_effort", "low"))
    provider = str(configuration.get("provider", "openai"))
    config_isolation = () if provider == "deepseek" else ("--ignore-user-config",)
    common = (
        "--json", "--skip-git-repo-check", *config_isolation,
        "-m", model, "-c", f'model_reasoning_effort="{effort}"', "-",
    )
    if continuation is None:
        command = ("/runtime/bin/codex", "exec", "--color", "never", *common)
    else:
        command = (
            "/runtime/bin/codex", "exec", "resume", continuation.thread_id,
            *common,
        )
    return RemoteCodexPlan(
        command=command,
        environment={
            "HOME": "/runtime/home",
            "CODEX_HOME": "/runtime/home",
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
        },
        stdin=encoded,
        model=model,
        provider=provider,
        continuation_thread_id=(continuation.thread_id if continuation else None),
    )


def materialize_remote_credential(
    plan: RemoteCodexPlan, material: bytes,
) -> RemoteCodexCredentialProjection:
    """Convert opaque Windows secret bytes into Codex-owned guest files."""
    if not isinstance(material, bytes) or not material:
        raise ValueError("CODEX_CREDENTIAL_INVALID")
    if plan.provider == "openai":
        return RemoteCodexCredentialProjection("/runtime/home/auth.json", material)
    if plan.provider != "deepseek":
        raise ValueError("CODEX_PROVIDER_INVALID")
    token = material.rstrip(b"\r\n")
    if not _DEEPSEEK_API_KEY.fullmatch(token):
        raise ValueError("CODEX_DEEPSEEK_API_KEY_INVALID")
    model = plan.model
    config = (
        f'model = "{model}"\n'
        'model_provider = "deepseek"\n'
        'preferred_auth_method = "apikey"\n'
        'forced_login_method = "api"\n'
        'model_reasoning_effort = "high"\n'
        'web_search = "disabled"\n'
        'model_catalog_json = "/runtime/home/models.json"\n'
        '[model_providers.deepseek]\n'
        'name = "deepseek"\n'
        'base_url = "https://api.deepseek.com/"\n'
        'wire_api = "responses"\n'
        f'experimental_bearer_token = "{token.decode("ascii")}"\n'
    ).encode()
    return RemoteCodexCredentialProjection(
        "/runtime/home/config.toml", config,
        {"models.json": _deepseek_model_catalog()},
    )


def decode_codex_jsonl(content: bytes) -> CodexDecodedResult:
    thread_id = None
    messages: list[str] = []
    completed = False
    error_code = None
    usage: dict[str, int] = {}
    for raw in content.splitlines():
        if not raw:
            continue
        if len(raw) > MAX_EVENT_LINE_BYTES:
            raise ValueError("CODEX_EVENT_LINE_TOO_LARGE")
        try:
            event = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("CODEX_EVENT_INVALID") from exc
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise ValueError("CODEX_EVENT_INVALID")
        kind = event["type"]
        if kind == "thread.started":
            candidate = event.get("thread_id")
            if not isinstance(candidate, str) or not candidate.strip():
                raise ValueError("CODEX_THREAD_ID_MISSING")
            if thread_id is not None and thread_id != candidate:
                raise ValueError("CODEX_THREAD_ID_CONFLICT")
            thread_id = candidate
        elif kind in {"item.completed", "item.updated"}:
            item = event.get("item") or {}
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                text = item["text"]
                if text and (not messages or messages[-1] != text):
                    messages.append(text)
        elif kind == "turn.completed":
            completed = True
            raw_usage = event.get("usage") or {}
            usage = {
                key: int(value)
                for key, value in raw_usage.items()
                if isinstance(key, str) and isinstance(value, int) and value >= 0
            }
        elif kind in {"turn.failed", "error"}:
            raw_error = event.get("error") or {}
            error_code = str(raw_error.get("code") or kind)[:128]
    return CodexDecodedResult(thread_id, tuple(messages), completed, error_code, usage)


def classify_native_session_path(path: str, thread_id: str) -> bool:
    """Classify by path only; callers must run this before fetching bytes."""
    if not isinstance(path, str) or not isinstance(thread_id, str):
        return False
    filename = path.rsplit("/", 1)[-1]
    return bool(_SESSION_PATH.fullmatch(path) and thread_id in filename)


class AttemptStarter(Protocol):
    def start_codex_attempt(
        self, *, request: ExecutionStartRequest, workspace: WorkspaceV1,
        profile: AgentBoxProfileV1, credential: CredentialRefV1,
        continuation: CodexContinuationV1 | None, plan: RemoteCodexPlan,
    ) -> object: ...


class RemoteCodexExecutionProvider:
    """Core ExecutionProvider whose native behavior remains in the Codex plugin."""

    provider_id = "codex-remote-exec"

    def __init__(
        self, *, profile_loader: Callable[[str], Mapping[str, Any]],
        attempt_starter: AttemptStarter,
    ) -> None:
        self._profile_loader = profile_loader
        self._attempt_starter = attempt_starter
        self._handles: dict[str, object] = {}

    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(self.provider_id, "Codex remote exec", "1")

    def capabilities(self) -> Mapping[str, str]:
        return {
            "start": "supported", "observe": "supported",
            "native-resume": "supported", "stream": "captured-jsonl",
        }

    def input_limits(self) -> Mapping[str, tuple[int, int | None]]:
        return {
            WorkspaceV1.contract_id: (1, 1),
            PromptFragmentV1.contract_id: (1, 1),
            AgentBoxProfileV1.contract_id: (1, 1),
            CredentialRefV1.contract_id: (1, 1),
            CodexContinuationV1.contract_id: (0, 1),
        }

    @staticmethod
    def _one(request: ExecutionStartRequest, contract: str) -> object:
        values = request.inputs.get(contract, ())
        if len(values) != 1:
            raise ValueError(f"exactly one {contract} input is required")
        return values[0]

    def start(self, request: ExecutionStartRequest) -> ExecutionStartReceipt:
        workspace = self._one(request, WorkspaceV1.contract_id)
        prompt = self._one(request, PromptFragmentV1.contract_id)
        profile = self._one(request, AgentBoxProfileV1.contract_id)
        credential = self._one(request, CredentialRefV1.contract_id)
        continuation_values = request.inputs.get(CodexContinuationV1.contract_id, ())
        continuation = continuation_values[0] if continuation_values else None
        if not isinstance(workspace, WorkspaceV1) or not isinstance(prompt, PromptFragmentV1):
            raise TypeError("Codex workspace/prompt contract mismatch")
        if not isinstance(profile, AgentBoxProfileV1) or profile.agent_type != "codex":
            raise TypeError("Codex profile contract mismatch")
        if not isinstance(credential, CredentialRefV1) or credential.harness_scope != "codex":
            raise TypeError("Codex credential contract mismatch")
        if continuation is not None and not isinstance(continuation, CodexContinuationV1):
            raise TypeError("Codex continuation contract mismatch")
        configuration = self._profile_loader(profile.digest)
        plan = build_remote_plan(configuration, prompt.content, continuation)
        handle = self._attempt_starter.start_codex_attempt(
            request=request, workspace=workspace, profile=profile,
            credential=credential, continuation=continuation, plan=plan,
        )
        self._handles[request.dispatch_id] = handle
        return ExecutionStartReceipt(
            request.execution_id, request.dispatch_id, request.inputs_digest,
            runtime_handle=handle,
        )

    def get_handle(self, dispatch_id: str) -> object:
        return self._handles[dispatch_id]

    def release_handle(self, dispatch_id: str) -> None:
        self._handles.pop(dispatch_id, None)

    def observe(self, native_ref: object) -> object:
        return native_ref
