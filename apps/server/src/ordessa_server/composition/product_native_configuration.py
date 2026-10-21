"""Read the reviewed Pi/OpenCode model metadata for the fixed preview-free case.

The receipt and Pi executable are independently pinned to the approved
preflight. This reads no credential and executes no native process. All other
provider inputs remain explicit inputs to the original Product lifecycle
constructor.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
from types import MappingProxyType

from ordessa_agents.harness.providers.registry import (
    HarnessDefinitionDeclaration,
    HarnessDefinitionDescriptor,
    HarnessInstallationObservation,
)
from ordessa_units.definitions.admission_identity import AdmissionNamespace
from ordessa_infrastructure.encoding import decode_json

from .product_native_provider import construct_product_native_provider_inputs


_RECEIPT_RELATIVE_PATH = Path(
    "docs/implementation/packages-convergence-20261012/execution/real-validation/pi/"
    "STEP-5-PREVIEW-FREE-METADATA.json"
)
_RECEIPT_SHA256 = "e0baa6d915948e250be3270c73fea8f367b3a927970ab60ea5d35a56bf282643"
_PI_EXECUTABLE_LINK = Path("/home/maoqh/.local/bin/pi")
_PI_EXECUTABLE_TARGET = Path("/home/maoqh/.pi/agent/bin/pi")
_PI_EXECUTABLE_SHA256 = "99142ef3d4cd5ce154cc568c6e915930632808dd7010666e514551c1430ffd3d"
_BRIDGE_EXECUTABLE = Path("/tmp/ordessa-unit-live-acp-20261012-reproduced")
_BRIDGE_SHA256 = "5a2f8f008fdf6fdf274d99f358c37477d8bcf8c4bfacf8cefef2630ef12d1c84"
_MAX_RECEIPT_BYTES = 16_384
_MAX_PI_EXECUTABLE_BYTES = 16 * 1024 * 1024
_MAX_BRIDGE_BYTES = 16 * 1024 * 1024
_PROVIDER = "opencode"
_MODEL = "step-5-preview-free"
_PI_NATIVE_VERSION = "0.86.1"


class NativeConfigurationUnavailable(ValueError):
    """A pinned metadata/executable pair is absent or no longer matches."""


@dataclass(frozen=True)
class PiModelFacts:
    catalogue: tuple[str, ...]
    native_model_definition: Mapping[str, object]


def _read_pinned_file(path: Path, *, expected_path: Path, limit: int) -> bytes:
    try:
        if path != expected_path or path.is_symlink():
            raise NativeConfigurationUnavailable("pinned native input path differs")
        info = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
            raise NativeConfigurationUnavailable("pinned native input is not a bounded regular file")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            opened = os.fstat(fd)
            if (not stat.S_ISREG(opened.st_mode)
                    or (opened.st_dev, opened.st_ino, opened.st_size)
                       != (info.st_dev, info.st_ino, info.st_size)):
                raise NativeConfigurationUnavailable("pinned native input changed while opening")
            chunks = []
            size = 0
            while size <= limit:
                chunk = os.read(fd, min(65536, limit + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            if size != info.st_size or size > limit:
                raise NativeConfigurationUnavailable("pinned native input changed or exceeds limit")
            return b"".join(chunks)
        finally:
            os.close(fd)
    except NativeConfigurationUnavailable:
        raise
    except (OSError, ValueError):
        raise NativeConfigurationUnavailable("pinned native input is unavailable") from None


def _repository_root(value) -> Path:
    try:
        root = Path(value)
        if not root.is_absolute() or root.resolve(strict=True) != root:
            raise NativeConfigurationUnavailable("canonical repository root required")
        receipt = root / _RECEIPT_RELATIVE_PATH
        if receipt.is_symlink() or not receipt.is_file():
            raise NativeConfigurationUnavailable("reviewed Pi model receipt is unavailable")
        return root
    except NativeConfigurationUnavailable:
        raise
    except (OSError, TypeError, ValueError):
        raise NativeConfigurationUnavailable("canonical repository root required") from None


def _verify_pi_executable(path) -> Path:
    try:
        candidate = Path(path)
        if candidate != _PI_EXECUTABLE_LINK:
            raise NativeConfigurationUnavailable("selected Pi executable path differs from preflight")
        target = candidate.resolve(strict=True)
        if target != _PI_EXECUTABLE_TARGET:
            raise NativeConfigurationUnavailable("selected Pi executable target differs from preflight")
        raw = _read_pinned_file(
            target, expected_path=_PI_EXECUTABLE_TARGET,
            limit=_MAX_PI_EXECUTABLE_BYTES,
        )
        if hashlib.sha256(raw).hexdigest() != _PI_EXECUTABLE_SHA256:
            raise NativeConfigurationUnavailable("selected Pi executable digest differs from preflight")
        return candidate
    except NativeConfigurationUnavailable:
        raise
    except (OSError, TypeError, ValueError):
        raise NativeConfigurationUnavailable("selected Pi executable is unavailable") from None


def _verify_bridge_executable(path) -> Path:
    try:
        candidate = Path(path)
        if candidate != _BRIDGE_EXECUTABLE:
            raise NativeConfigurationUnavailable("selected Pi ACP bridge path differs from preflight")
        raw = _read_pinned_file(
            candidate, expected_path=_BRIDGE_EXECUTABLE,
            limit=_MAX_BRIDGE_BYTES,
        )
        if hashlib.sha256(raw).hexdigest() != _BRIDGE_SHA256:
            raise NativeConfigurationUnavailable("selected Pi ACP bridge digest differs from preflight")
        return candidate
    except NativeConfigurationUnavailable:
        raise
    except (OSError, TypeError, ValueError):
        raise NativeConfigurationUnavailable("selected Pi ACP bridge is unavailable") from None


def read_step5_preview_free_model_facts(*, repository_root, pi_executable) -> PiModelFacts:
    """Read the exact reviewed metadata source and verify its Pi binary pairing.

    The metadata path is fixed relative to a trusted repository root. Both its
    content digest and the actual selected Pi executable bytes must match the
    preflight pins before any model fields are returned.
    """
    root = _repository_root(repository_root)
    receipt_path = root / _RECEIPT_RELATIVE_PATH
    raw = _read_pinned_file(
        receipt_path, expected_path=receipt_path, limit=_MAX_RECEIPT_BYTES,
    )
    if hashlib.sha256(raw).hexdigest() != _RECEIPT_SHA256:
        raise NativeConfigurationUnavailable("reviewed Pi model receipt digest differs")
    _verify_pi_executable(pi_executable)
    try:
        document = decode_json(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, ValueError, TypeError):
        raise NativeConfigurationUnavailable("reviewed Pi model receipt is invalid UTF-8 JSON") from None
    if (type(document) is not dict
            or set(document) != {"credentialReference", "installedPi", "nativeModelDefinition",
                                "retrievedOn", "schema", "source"}
            or document.get("schema") != "ordessa.pi.native-model-fixture-receipt/1"
            or document.get("retrievedOn") != "2026-10-12"
            or document.get("credentialReference") != "$OPENCODE_API_KEY"):
        raise NativeConfigurationUnavailable("reviewed Pi model receipt schema differs")
    installed = document["installedPi"]
    if (type(installed) is not dict
            or set(installed) != {"package", "publicCompatibilityCatalogueCount",
                                  "selectedModelPresentInStaticCatalogue", "version"}
            or installed.get("package") != "@earendil-works/pi-ai"
            or installed.get("version") != "0.86.1"
            or type(installed.get("publicCompatibilityCatalogueCount")) is not int
            or installed.get("selectedModelPresentInStaticCatalogue") is not False):
        raise NativeConfigurationUnavailable("reviewed Pi installation metadata differs")
    row = document["nativeModelDefinition"]
    expected_fields = {
        "api", "baseUrl", "compat", "contextWindow", "cost", "id", "input",
        "maxTokens", "name", "provider", "reasoning", "thinkingLevelMap",
    }
    if (type(row) is not dict or set(row) != expected_fields
            or row.get("provider") != _PROVIDER or row.get("id") != _MODEL
            or row.get("api") != "openai-completions"
            or row.get("baseUrl") != "https://opencode.ai/zen/v1"):
        raise NativeConfigurationUnavailable("reviewed native Pi Model row differs")
    return PiModelFacts((_MODEL,), MappingProxyType(dict(row)))


def construct_step5_preview_free_provider_inputs(
    runtime, *, repository_root, pi_executable, **trusted_inputs,
):
    """Use the pinned real model facts with the existing Product lifecycle builder.

    Declaration, protected fingerprint, credential source, grants, Profile and
    Environment roots stay explicit trusted inputs; this function produces
    none of them.
    """
    if ({"provider", "model", "model_catalogue", "native_model_definition", "pi_executable"}
            & set(trusted_inputs)):
        raise NativeConfigurationUnavailable("model facts and executable cannot be overridden")
    facts = read_step5_preview_free_model_facts(
        repository_root=repository_root, pi_executable=pi_executable,
    )
    return construct_product_native_provider_inputs(
        runtime,
        provider=_PROVIDER,
        model=_MODEL,
        model_catalogue=facts.catalogue,
        native_model_definition=facts.native_model_definition,
        pi_executable=str(pi_executable),
        **trusted_inputs,
    )


def construct_step5_preview_free_harness_declaration(
    runtime, *, repository_root, bridge_executable, pi_executable,
):
    """Bind the reviewed Go bridge and Pi binary to this runtime's namespace.

    Observation is read-time only: it rechecks the exact bridge, Pi executable
    and reviewed metadata bytes, and reports ``unknown`` if any fact differs.
    """
    context = getattr(getattr(runtime, "unit_runtime", None), "context", None)
    namespace = getattr(context, "environment_namespace", None)
    try:
        AdmissionNamespace(namespace)
        if getattr(runtime, "started", None) is not False:
            raise NativeConfigurationUnavailable("declaration requires the current unstarted runtime")
        _verify_bridge_executable(bridge_executable)
        _verify_pi_executable(pi_executable)
        facts = read_step5_preview_free_model_facts(
            repository_root=repository_root, pi_executable=pi_executable,
        )
        if facts.native_model_definition.get("provider") != _PROVIDER:
            raise NativeConfigurationUnavailable("reviewed model route does not match Pi preparation")
    except NativeConfigurationUnavailable:
        raise
    except Exception:
        raise NativeConfigurationUnavailable("same-runtime Unit namespace is unavailable") from None

    declaration = construct_pi_harness_declaration(
        runtime, bridge_executable=bridge_executable, pi_executable=pi_executable,
    )

    def observe(expected_ref):
        current = declaration.installation_observer(expected_ref)
        if current.state != "present":
            return HarnessInstallationObservation("unknown")
        try:
            root = _repository_root(repository_root)
            receipt_path = root / _RECEIPT_RELATIVE_PATH
            receipt = _read_pinned_file(
                receipt_path, expected_path=receipt_path, limit=_MAX_RECEIPT_BYTES,
            )
            if hashlib.sha256(receipt).hexdigest() != _RECEIPT_SHA256:
                return HarnessInstallationObservation("unknown")
            refreshed = read_step5_preview_free_model_facts(
                repository_root=root, pi_executable=pi_executable,
            )
            if refreshed.native_model_definition.get("id") != _MODEL:
                return HarnessInstallationObservation("unknown")
            return HarnessInstallationObservation(
                "present", native_version=_PI_NATIVE_VERSION,
                version_verified=True,
                evidence_ref="sha256:" + hashlib.sha256(
                    (_BRIDGE_SHA256 + _PI_EXECUTABLE_SHA256 + _RECEIPT_SHA256).encode("ascii")
                ).hexdigest(),
            )
        except Exception:
            return HarnessInstallationObservation("unknown")

    return HarnessDefinitionDeclaration(declaration.descriptor, observe)


def construct_pi_harness_declaration(runtime, *, bridge_executable, pi_executable,
                                    reviewed_bridge_sha256=None):
    """Declare the pinned Pi/ACP implementation without choosing a model.

    The caller binds model/provider facts separately through the fixed Profile
    and Pi's ``native_model_definition`` materialization path. This constructor
    owns only the existing binary pins, runtime namespace, descriptor and
    binary installation observation.
    """
    context = getattr(getattr(runtime, "unit_runtime", None), "context", None)
    namespace = getattr(context, "environment_namespace", None)
    try:
        AdmissionNamespace(namespace)
        if getattr(runtime, "started", None) is not False:
            raise NativeConfigurationUnavailable("declaration requires the current unstarted runtime")
        if reviewed_bridge_sha256 is None:
            bridge = _verify_bridge_executable(bridge_executable)
            bridge_digest = _BRIDGE_SHA256
            bridge_path = _BRIDGE_EXECUTABLE
        else:
            # Trusted product selection pins an explicitly reviewed build.
            # Never change the historical default or infer a digest from disk.
            bridge = Path(bridge_executable)
            if (type(reviewed_bridge_sha256) is not str
                    or len(reviewed_bridge_sha256) != 64
                    or any(c not in '0123456789abcdef' for c in reviewed_bridge_sha256)
                    or not bridge.is_absolute() or bridge.resolve(strict=True) != bridge):
                raise NativeConfigurationUnavailable('reviewed bridge pin is invalid')
            bridge_digest, bridge_path = reviewed_bridge_sha256, bridge
            raw = _read_pinned_file(bridge, expected_path=bridge_path, limit=_MAX_BRIDGE_BYTES)
            if hashlib.sha256(raw).hexdigest() != bridge_digest:
                raise NativeConfigurationUnavailable('reviewed bridge digest differs')
        _verify_pi_executable(pi_executable)
    except NativeConfigurationUnavailable:
        raise
    except Exception:
        raise NativeConfigurationUnavailable("same-runtime Unit namespace is unavailable") from None

    descriptor = HarnessDefinitionDescriptor(
        provider_id="pi",
        definition_ref={
            "environmentNamespace": namespace,
            "definitionId": "pi",
            "revision": "2.0",
        },
        implementation_digest="sha256:" + bridge_digest,
        protocol_id="acp/v1",
        adapter_version="pi-acp/0.86.1",
        backend_version=_PI_NATIVE_VERSION,
        capabilities=("existingChannel",),
    )

    def observe(expected_ref):
        if (not isinstance(expected_ref, Mapping)
                or dict(expected_ref) != dict(descriptor.definition_ref)):
            return HarnessInstallationObservation("unknown")
        try:
            bridge_bytes = _read_pinned_file(
                bridge, expected_path=bridge_path, limit=_MAX_BRIDGE_BYTES,
            )
            pi_bytes = _read_pinned_file(
                _PI_EXECUTABLE_TARGET, expected_path=_PI_EXECUTABLE_TARGET,
                limit=_MAX_PI_EXECUTABLE_BYTES,
            )
            if (hashlib.sha256(bridge_bytes).hexdigest() != bridge_digest
                    or hashlib.sha256(pi_bytes).hexdigest() != _PI_EXECUTABLE_SHA256):
                return HarnessInstallationObservation("unknown")
            evidence = hashlib.sha256(
                (bridge_digest + _PI_EXECUTABLE_SHA256).encode("ascii")
            ).hexdigest()
            return HarnessInstallationObservation(
                "present", native_version=_PI_NATIVE_VERSION,
                version_verified=True, evidence_ref="sha256:" + evidence,
            )
        except Exception:
            return HarnessInstallationObservation("unknown")

    return HarnessDefinitionDeclaration(descriptor, observe)


__all__ = [
    "NativeConfigurationUnavailable",
    "PiModelFacts",
    "construct_pi_harness_declaration",
    "construct_step5_preview_free_harness_declaration",
    "construct_step5_preview_free_provider_inputs",
    "read_step5_preview_free_model_facts",
]
