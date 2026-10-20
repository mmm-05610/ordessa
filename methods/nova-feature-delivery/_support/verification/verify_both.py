"""Offline coordinator verification of both method packages; no runtime execution.

Run with the existing nightly Python and -B. Capture current Engineering and
Infrastructure Python bytes before importing them. An import finder holds those
bytes in memory for every serial child, so concurrent edits cannot change the
core used between the Nova and GitLab cases. Only evidence in the two authorized
method directories is written. No catalog, store, DB, service, or Grant is built.
"""
from __future__ import annotations

import dataclasses
import hashlib
import importlib.abc
import importlib.util
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import traceback
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[4]
METHODS = [ROOT / "methods/nova-feature-delivery", ROOT / "methods/gitlab-product-change"]
CORE_ROOTS = [ROOT / "packages/engineering/src", ROOT / "packages/infrastructure/src"]


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def write_json(path, value):
    if not any(path.is_relative_to(p / "_support/verification") for p in METHODS):
        raise ValueError("evidence write outside authorized verification directories")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


CAPTURE = {}
CAPTURE_DIRS = {}
ARCHIVE = METHODS[0] / "_support/verification/core-sources.json"
if ARCHIVE.exists():
    archive = json.loads(ARCHIVE.read_text())
    source_files = {ROOT / path: content.encode("utf-8") for path, content in archive["source_utf8"].items()}
else:
    source_files = {path: path.read_bytes() for source_root in CORE_ROOTS for path in sorted(source_root.rglob("*.py"))}
for path, raw in source_files.items():
    source_root = next(p for p in CORE_ROOTS if path.is_relative_to(p))
    relative = path.relative_to(source_root)
    package = path.name == "__init__.py"
    parts = relative.parts[:-1] if package else (*relative.parts[:-1], path.stem)
    CAPTURE[".".join(parts)] = (path, raw, package)
    for length in range(1, len(relative.parts)):
        CAPTURE_DIRS[".".join(relative.parts[:length])] = source_root.joinpath(*relative.parts[:length])
CORE_INDEX = {str(p.relative_to(ROOT)): digest(raw) for p, raw, _ in CAPTURE.values()}
CORE_DIGEST = digest(canonical(CORE_INDEX))
if ARCHIVE.exists():
    if archive["core_index_sha256"] != CORE_DIGEST:
        raise RuntimeError("archived core source hashes mismatch; verification not performed")
else:
    prior = METHODS[0] / "_support/verification/core-snapshot.json"
    if prior.exists() and json.loads(prior.read_text())["core_index_sha256"] != CORE_DIGEST:
        raise RuntimeError("live core no longer matches first attempt; cannot reuse that core snapshot")
    if any(p.read_bytes() != raw for p, raw, _ in CAPTURE.values()):
        raise RuntimeError("core changed during initial capture; verification not performed")
    write_json(ARCHIVE, {"core_index_sha256": CORE_DIGEST,
                        "non_runtime_resource": True,
                        "source_utf8": {str(p.relative_to(ROOT)): raw.decode("utf-8") for p, raw, _ in CAPTURE.values()}})


class CapturedCore(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if fullname not in CAPTURE:
            if fullname in CAPTURE_DIRS:
                spec = importlib.util.spec_from_loader(fullname, loader=None, is_package=True)
                spec.submodule_search_locations = [str(CAPTURE_DIRS[fullname])]
                return spec
            if fullname.startswith(("ordessa_engineering.", "ordessa_infrastructure.")):
                raise ImportError("module absent from the captured core: " + fullname)
            return None
        location, raw, package = CAPTURE[fullname]
        return importlib.util.spec_from_loader(fullname, self, origin=str(location), is_package=package)

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        location, raw, package = CAPTURE[module.__name__]
        module.__file__ = str(location)
        if package:
            module.__path__ = [str(location.parent)]
        exec(compile(raw, str(location), "exec"), module.__dict__)


if any(n.startswith(("ordessa_engineering", "ordessa_infrastructure")) for n in sys.modules):
    raise RuntimeError("core was imported before capture; use a fresh interpreter")
sys.meta_path.insert(0, CapturedCore())


def no_network(*args, **kwargs):
    raise RuntimeError("network forbidden during method verification")


def network_audit(event, args):
    if event in {"socket.connect", "socket.bind", "socket.getaddrinfo", "socket.sendto"}:
        no_network()


sys.addaudithook(network_audit)
socket.create_connection = no_network
socket.getaddrinfo = no_network

import yaml
from jsonschema import Draft202012Validator
from ordessa_engineering.methods import load_method, validate_method, compile_method
from ordessa_engineering.methods.definitions.models import MethodSource
from ordessa_engineering.methods.definitions.errors import MethodError, MethodFailure
from ordessa_engineering.methods.compilation.encoding import program_to_canonical
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.application.orchestration.method_bridge import command_capabilities, MethodBridge
from ordessa_engineering.domain.artifacts.codec import decode_payload, decode_provenance_fields

# Actual owner descriptions; no fabricated descriptor or fixture operation.
# registry_snapshot_ref remains None: this is not a production registry capture.
CAPABILITIES = command_capabilities()
assert CAPABILITIES.registry_snapshot_ref is None
DESCRIPTORS = {d.capability_id: d for d in CAPABILITIES.capabilities}


class RecordingReader:
    def __init__(self, root, replacements=None):
        self.reader = FileResourceReader()
        self.reads = []
        self.replacements = replacements or {}

    def read(self, source, relative_path, max_bytes):
        self.reads.append(relative_path)
        if relative_path in self.replacements:
            raw = self.replacements[relative_path]
            if len(raw) > max_bytes:
                raise MethodFailure(MethodError("RESOURCE_TOO_LARGE", "verification input too large"))
            return raw
        return self.reader.read(source, relative_path, max_bytes)


def inspect_method(root, case):
    bundle = root / "projection"
    manifest = yaml.safe_load((bundle / "method.yaml").read_bytes())
    workflow_decl = next(d for d in manifest["resources"] if d["kind"] == "workflow")
    path = workflow_decl["path"]
    workflow = yaml.safe_load((bundle / path).read_bytes())
    replacements = {}
    if case in ("unknown-operation", "cycle", "business-outcomes", "unsupported-control-node", "digest-mismatch"):
        operation = next(s for s in workflow["steps"] if s["kind"] == "operation")
        if case == "unknown-operation":
            operation["operation"] = "external.verification.unregistered_operation"
        elif case == "cycle":
            operation["outcomes"]["completed"] = {"next": operation["id"]}
        elif case == "business-outcomes":
            operation["outcomes"] = {k: {"stop": workflow["stop_outcomes"][0]}
                                     for k in ("approved", "no_spec", "rework", "deferred")}
        elif case == "unsupported-control-node":
            operation["kind"] = "parallel"
        raw = yaml.safe_dump(workflow, sort_keys=False, allow_unicode=True).encode()
        replacements[path] = raw + (b"\n# changed without digest update\n" if case == "digest-mismatch" else b"")
        if case != "digest-mismatch":
            workflow_decl["sha256"] = digest(raw)
            replacements["method.yaml"] = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True).encode()
    reader = RecordingReader(root, replacements)
    loaded = load_method(MethodSource(bundle), reader=reader)
    output = {"case": case, "loader_ok": loaded.ok, "reader_paths": reader.reads,
              "support_area_read": any(p.startswith("_support/") for p in reader.reads),
              "runtime_execution": "not_attempted", "production_activation": "not_attempted"}
    if not loaded.ok:
        output["loader_error"] = dataclasses.asdict(loaded.error)
        return output, 1
    report = validate_method(loaded.value, CAPABILITIES)
    compiled = compile_method(loaded.value, CAPABILITIES, "external-methods-offline/1")
    output.update({"validation_valid": report.valid,
                   "diagnostics": [dataclasses.asdict(d) for d in report.diagnostics],
                   "compiler_ok": compiled.ok})
    if compiled.error:
        output["compiler_error"] = dataclasses.asdict(compiled.error)
    if compiled.ok:
        program = program_to_canonical(compiled.value.program)
        output["program"] = program
        output["program_sha256"] = digest(canonical(program))
        output["declared_resource_hashes"] = {d["path"]: d["sha256"] for d in manifest["resources"]}
        output["requires_exact_actual_descriptors"] = all(
            r["capability_id"] in DESCRIPTORS and all(r[k] == getattr(DESCRIPTORS[r["capability_id"]], k)
            for k in ("kind", "interface_version", "contract_digest")) for r in manifest["requires"])
        inputs = next(s for s in workflow["steps"] if s["kind"] == "operation").get("inputs", {})
        descriptor = DESCRIPTORS[next(s for s in workflow["steps"] if s["kind"] == "operation")["operation"]]
        output["input_binding_names_match_required_parameters"] = set(descriptor.contract["input_schema"]["required"]).issubset(inputs)
        output["input_binding_names_are_actual_parameters"] = set(inputs).issubset(descriptor.contract["input_schema"]["properties"])
        output["schema_checks"] = []
        for declaration in manifest.get("documents", []):
            resource = loaded.value.resources[declaration["schema"]["resource"]]
            Draft202012Validator.check_schema(resource.value)
            # Absence of a complete report must fail; this is schema verification,
            # not an accepted Artifact command or a workflow execution.
            rejects_empty = not Draft202012Validator(resource.value).is_valid({})
            output["schema_checks"].append({"document_type": declaration["document_type"], "rejects_empty_report": rejects_empty})
        output["synthetic_report_checks"] = []
        declaration = manifest["documents"][0]
        resource = loaded.value.resources[declaration["schema"]["resource"]]
        schema = resource.value
        schema_validator = Draft202012Validator(schema)
        schema_declaration = next(d for d in manifest["resources"] if d["id"] == resource.declaration["id"])
        # This symbolic ref tests the public shape only. It is deliberately NOT
        # a released snapshot and is never supplied to a service/store/command.
        symbolic_ref = {"method_id": manifest["method_id"], "release_version": manifest["release_version"],
                        "schema_version": manifest["schema_version"],
                        "snapshot_digest": {"algorithm": "sha256", "hex": "a" * 64}}
        for example_path in sorted((root / "_support/design-traces").glob("*.report.json")):
            example = json.loads(example_path.read_bytes())
            errors = list(schema_validator.iter_errors(example))
            payload = {"media_type": "application/json", "schema_id": schema["$id"],
                       "content_kind": "method_content", "inline_value": {
                           "schema_ref": {"method_ref": symbolic_ref, "logical_path": schema_declaration["path"],
                                          "resource_digest": {"algorithm": "sha256", "hex": schema_declaration["sha256"]},
                                          "resource_id": schema_declaration["id"]},
                           "value": example, "rendered_body_ref": None}}
            decoded = decode_payload(payload)
            provenance = decode_provenance_fields({"sources": [], "claims": [], "evidence_links": [],
                                                  "method_refs": [symbolic_ref], "generation_origin": None})
            parameters = {"kind": "evidence", "initial": payload, "method_refs": [symbolic_ref]}
            node = next(s for s in workflow["steps"] if s["kind"] == "operation")
            slots = {slot: parameters[name] for name, slot in node["inputs"].items()}
            bridged = MethodBridge().operation_inputs(compiled.value.program, node["id"], slots)
            result = {"path": str(example_path.relative_to(root)), "sha256": digest(example_path.read_bytes()),
                      "schema_valid": not errors,
                      "schema_errors": [{"path": list(e.path), "message": e.message} for e in errors],
                      "actual_payload_codec_ok": decoded.content.schema_ref.method_ref == provenance["method_refs"][0],
                      "actual_command_input_schema_valid": Draft202012Validator(descriptor.contract["input_schema"]).is_valid(parameters),
                      "actual_method_bridge_input_mapping_ok": bridged == parameters,
                      "authority": "synthetic report and symbolic UNRELEASED MethodRef; no command invoked"}
            output["synthetic_report_checks"].append(result)
        if (output["support_area_read"] or not output["requires_exact_actual_descriptors"]
                or not output["input_binding_names_match_required_parameters"]
                or not output["input_binding_names_are_actual_parameters"]
                or not all(c["rejects_empty_report"] for c in output["schema_checks"])
                or len(output["synthetic_report_checks"]) < 3
                or not all(c["schema_valid"] and c["actual_payload_codec_ok"] and c["actual_command_input_schema_valid"] and c["actual_method_bridge_input_mapping_ok"]
                           for c in output["synthetic_report_checks"])):
            return output, 2
    return output, 0 if report.valid and compiled.ok else 1


def child_case(root, case):
    # Children inherit the exact captured bytes/catalog, and run serially.
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            value, code = inspect_method(root, case)
        except Exception:
            value, code = {"case": case, "exception": traceback.format_exc()}, 2
        with os.fdopen(write_fd, "wb") as stream:
            stream.write(canonical(value))
        os._exit(code)
    os.close(write_fd)
    with os.fdopen(read_fd, "rb") as stream:
        raw = stream.read()
    _, status = os.waitpid(pid, 0)
    value = json.loads(raw)
    value["process_exit_code"] = os.waitstatus_to_exitcode(status)
    return value


def main():
    head = git("rev-parse", "HEAD")
    core_status = git("status", "--short", "--", "packages/engineering", "packages/infrastructure")
    snapshot = {"captured_at": datetime.now(timezone.utc).isoformat(), "git_head": head,
                "python": sys.version, "python_executable": sys.executable,
                "existing_dependency_versions": {n: importlib.metadata.version(n) for n in ("PyYAML", "jsonschema", "referencing")},
                "core_capture": "immutable Python bytes held in memory, imported through CapturedCore",
                "archived_core_source": str(ARCHIVE.relative_to(ROOT)),
                "core_index_sha256": CORE_DIGEST, "file_sha256": CORE_INDEX,
                "core_worktree_status": core_status,
                "descriptor_source": "command_capabilities() from captured actual owner source",
                "registry_snapshot_ref": None, "production_catalog": False,
                "command_descriptors": [{k: getattr(d, k) for k in
                    ("capability_id", "kind", "interface_version", "contract_digest")}
                    for d in CAPABILITIES.capabilities],
                "selected_actual_descriptor": dataclasses.asdict(DESCRIPTORS["engineering.artifacts.create"]),
                "network": "audit hook refuses socket connect/bind/sendto/getaddrinfo; create_connection/getaddrinfo also refuse",
                "writes": "only the two methods' _support/verification areas", "runtime_execution": "not_attempted"}
    all_ok = True
    results = []
    for root in METHODS:
        cases = [child_case(root, c) for c in ("baseline", "unknown-operation", "business-outcomes", "unsupported-control-node", "cycle", "digest-mismatch")]
        expected = {"baseline": (0, None), "unknown-operation": (1, "UNKNOWN_CAPABILITY"),
                    "business-outcomes": (1, "UNHANDLED_OUTCOME"),
                    "unsupported-control-node": (1, "METHOD_STRUCTURE_INVALID"),
                    "cycle": (1, "UNSUPPORTED_FLOW_CYCLE"), "digest-mismatch": (1, "RESOURCE_DIGEST_MISMATCH")}
        for value in cases:
            code, diagnostic = expected[value["case"]]
            codes = {d["code"] for d in value.get("diagnostics", [])}
            codes.add(value.get("loader_error", {}).get("code"))
            value["expected_refusal_observed"] = value["process_exit_code"] == code and (diagnostic is None or diagnostic in codes)
        passed = all(v["expected_refusal_observed"] for v in cases)
        all_ok &= passed
        evidence = {"method_root": str(root.relative_to(ROOT)), "core_index_sha256": CORE_DIGEST,
                    "compiled_bundle_root": str((root / "projection").relative_to(ROOT)),
                    "cases": cases, "verification_expectations_passed": passed,
                    "process_exit_code": 0 if passed else 1,
                    "runtime_execution": "not_attempted", "complete_external_flow_execution": "not_supported"}
        write_json(root / "_support/verification/results.json", evidence)
        write_json(root / "_support/verification/core-snapshot.json", snapshot)
        results.append({"method": root.name, "passed": passed, "exit_codes": {v["case"]:v["process_exit_code"] for v in cases}})
    changed = [str(p.relative_to(ROOT)) for p, raw, _ in CAPTURE.values() if not p.exists() or p.read_bytes() != raw]
    for root in METHODS:
        write_json(root / "_support/verification/capture-stability.json", {
            "core_index_sha256": CORE_DIGEST, "live_core_files_changed_after_capture": changed,
            "same_captured_core_used_for_both_methods": True,
            "runtime_state_or_product_services_touched": False})
    print(json.dumps({"core_index_sha256": CORE_DIGEST, "results": results,
                      "live_core_changed_since_capture": changed, "exit_code": 0 if all_ok else 1}, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
