#!/usr/bin/env python3
"""Validate a relocated Ordessa artifact without borrowing the checkout.

This is an artifact acceptance runner, not a source-tree test. Pass the root
directory produced by unpacking a deb (the directory containing ``opt/``).
All product Python is loaded by the interpreter shipped inside that artifact;
the process runs from a fresh temporary directory with developer Python and
Node environment overrides removed.

The JSON report deliberately distinguishes an unavailable/unsupported
product path from a successful controlled round. In particular, a healthy
``server.hello`` is only a runtime/wire probe; it does not imply that the
Agent submission owner and managed Harness can complete two rounds.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any


# This is the product's declared Python closure plus the required persistence
# and Agent packages from the 026 shipping/recovery contracts. A missing
# distribution is an acceptance failure even when unrelated import paths make
# a shallow host probe appear healthy.
REQUIRED_DISTRIBUTIONS = (
    "ordessa-environment-api",
    "pacthold",
    "ordessa-server-plugin-api",
    "ordessa-harness-api",
    "pacthold-runtime-compat",
    "ordessa-sandbox-api",
    "ordessa-sandbox-backend",
    "ordessa-sandbox-adapters",
    "ordessa-permissions-api",
    "ordessa-permissions-backend",
    "ordessa-permissions-adapters",
    "ordessa-workspace",
    "ordessa-harness",
    "ordessa-server",
    "ordessa-server-compat",
    "ordessa-model-provider",
    "ordessa-model-provider-profile",
    "ordessa-profile",
    "ordessa-skills",
    "ordessa-server-product",
    "ordessa-agent",
    "ordessa-persistence-sqlite",
)

REQUIRED_IMPORTS = (
    "ordessa_harness_api",
    "ordessa_model_provider_profile",
    "ordessa_environment_api",
    "pacthold",
    "server_plugin_api",
    "ordessa_harness",
    "pacthold_runtime_compat",
    "ordessa_sandbox_api",
    "ordessa_sandbox_backend",
    "ordessa_sandbox_adapters",
    "ordessa_permissions_api",
    "ordessa_permissions_backend",
    "ordessa_permissions_adapters",
    "ordessa_workspace",
    "ordessa_server",
    "ordessa_server_compat",
    "ordessa_model_provider",
    "ordessa_profile",
    "ordessa_skills",
    "ordessa_server_product",
    "ordessa_agent",
    "ordessa_persistence_sqlite",
)


# The driver is passed to the artifact's own interpreter via ``-c``. It never
# imports from the checkout. The isolated data roots are supplied as argv.
_ARTIFACT_DRIVER = r'''import importlib
import importlib.util
import importlib.metadata as metadata
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import shutil
import subprocess
import sys
import tempfile
import traceback

prefix = Path(sys.argv[1]).resolve()
data_root = Path(sys.argv[2]).resolve()
required_distributions = json.loads(sys.argv[3])
required_imports = json.loads(sys.argv[4])
repo_markers = [str(Path(p).resolve()) for p in json.loads(sys.argv[5]) if p]
controlled_fixture = Path(sys.argv[6]).resolve(strict=True)

def under(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (OSError, ValueError):
        return False

def under_repo_marker(path):
    return any(marker and under(path, marker) for marker in repo_markers)

report = {
    "interpreter": sys.executable,
    "prefix": str(prefix),
    "sysPath": list(sys.path),
    "environment": {key: os.environ.get(key) for key in (
        "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "NODE_PATH", "NODE_OPTIONS",
        "ORDESSA_DATA_ROOT", "ORDESSA_BUNDLED_ROOT")},
    "distributions": {},
    "imports": {},
    "sourceFree": {"status": "pass", "violations": []},
    "productVariants": {},
    "f5Consumers": {},
    "uiComponentsDI": {"status": "fail", "checks": {}, "missing": []},
}

for entry in sys.path:
    if not entry:
        report["sourceFree"]["violations"].append("empty sys.path entry")
        continue
    if not under(entry, prefix):
        report["sourceFree"]["violations"].append("sys.path outside artifact: " + entry)
    if under_repo_marker(entry):
        report["sourceFree"]["violations"].append("repository path in sys.path: " + entry)

installed = {}
for dist in metadata.distributions():
    name = (dist.metadata.get("Name") or "").lower().replace("_", "-")
    if not name:
        continue
    try:
        location = str(Path(dist.locate_file("")).resolve())
    except OSError:
        location = "unknown"
    direct_url = dist.read_text("direct_url.json")
    editable = False
    if direct_url:
        try:
            editable = bool(json.loads(direct_url).get("dir_info", {}).get("editable"))
        except (ValueError, TypeError):
            report["sourceFree"]["violations"].append("unreadable direct_url.json for " + name)
    installed[name] = {"version": dist.version, "location": location, "editable": editable}
    if editable:
        report["sourceFree"]["violations"].append("editable distribution: " + name)

for name in required_distributions:
    item = installed.get(name.lower().replace("_", "-"))
    report["distributions"][name] = item or {"status": "missing"}
    if item is None:
        report.setdefault("missingRequired", []).append("distribution:" + name)
    elif not under(item["location"], prefix):
        report["sourceFree"]["violations"].append("distribution outside artifact: " + name + " at " + item["location"])

for name in required_imports:
    try:
        module = importlib.import_module(name)
        origin = getattr(module, "__file__", None)
        if origin is None:
            spec = getattr(module, "__spec__", None)
            origin = getattr(spec, "origin", None)
        namespace_paths = getattr(module, "__path__", None)
        resolved_namespace_paths = []
        if namespace_paths is not None:
            try:
                resolved_namespace_paths = [str(Path(item).resolve()) for item in namespace_paths]
            except (OSError, TypeError, ValueError):
                resolved_namespace_paths = []
        is_namespace_package = origin is None and bool(resolved_namespace_paths)
        record = {"status": "imported", "origin": origin}
        if is_namespace_package:
            record["namespacePaths"] = resolved_namespace_paths
        origin_in_artifact = bool(origin and origin not in ("built-in", "frozen") and under(origin, prefix))
        namespace_in_artifact = (is_namespace_package and all(
            under(path, prefix) and not under_repo_marker(path) for path in resolved_namespace_paths
        ))
        if not (origin_in_artifact or namespace_in_artifact):
            record["status"] = "outside-artifact"
            report["sourceFree"]["violations"].append(
                "import outside artifact: " + name + " at " + str(origin)
                + (" namespacePaths=" + repr(resolved_namespace_paths) if resolved_namespace_paths else "")
            )
        elif origin_in_artifact and under_repo_marker(origin):
            record["status"] = "outside-artifact"
            report["sourceFree"]["violations"].append("import from repository path: " + name + " at " + str(origin))
    except BaseException as exc:
        record = {"status": "failed", "error": type(exc).__name__ + ": " + str(exc)}
        report.setdefault("missingRequired", []).append("import:" + name)
    report["imports"][name] = record

if report["sourceFree"]["violations"]:
    report["sourceFree"]["status"] = "fail"

# Product/runtime checks below import only from the artifact. F5 is tested by
# the separate `closeout-f5-consumers.mjs` artifact consumer runner.
app_root = prefix / "app"
dist_root = app_root / "dist"
extension_root = dist_root / "extensions"
renderer_root = dist_root / "renderer"

def text_at(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

ui_manifest = extension_root / "ordessa.ui-components" / "manifest.json"
ui_entry = extension_root / "ordessa.ui-components" / "entry.js"
contracts_bundle = extension_root / "ordessa.contracts" / "contract.js"
product_manifest_path = dist_root / "extensions.json"
shared_root = renderer_root / "shared"
shared_api = shared_root / "api.js"
shared_ui_api = shared_root / "ui-components-api.js"
host_bundle = dist_root / "electron-main.cjs"
product_manifest = {}
try:
    product_manifest = json.loads(product_manifest_path.read_text(encoding="utf-8"))
except (OSError, ValueError):
    pass

di_checks = {
    "productEnabled": "ordessa.ui-components" in product_manifest.get("enabled", []),
    "providerEntry": ui_entry.is_file(),
    "providerManifest": False,
    "contractCarrier": contracts_bundle.is_file(),
    "sharedExtensionApi": shared_api.is_file(),
    "sharedUiApi": shared_ui_api.is_file(),
    "hostImportMap": False,
    "singleUiTokenConstruction": bool(re.search(
        r'Token\s*\(\s*["\']ordessa\.ui-components\.v1["\']\s*\)', text_at(shared_ui_api)
    )),
    "carrierUsesSharedApi": '@ordessa/ui-components/api' in text_at(contracts_bundle),
    "sharedApiExportsTokenType": bool(re.search(r"\bToken\b", text_at(shared_api))),
    "runtimeIdentity": False,
}
try:
    di_checks["providerManifest"] = json.loads(ui_manifest.read_text(encoding="utf-8")).get("id") == "ordessa.ui-components"
except (OSError, ValueError):
    pass
host_text = text_at(host_bundle)
di_checks["hostImportMap"] = ('@ordessa/ui-components/api' in host_text
                               and '/shared/ui-components-api.js' in host_text)
missing_di_prerequisites = [
    name for name, passed in di_checks.items() if name != "runtimeIdentity" and not passed
]
if not missing_di_prerequisites:
    # Evaluate the built carrier and shared public module through the shipped
    # Electron/V8 runtime. Copies live only in the isolated temp root; bare
    # package imports are redirected to the artifact's own shared files.
    electron = app_root / "electron"
    try:
        with tempfile.TemporaryDirectory(prefix="ordessa-f5-di-") as module_tmp:
            module_root = Path(module_tmp)
            copied_shared = module_root / "shared"
            copied_contract = module_root / "contracts" / "contract.js"
            shutil.copytree(shared_root, copied_shared)
            copied_contract.parent.mkdir(parents=True)
            shutil.copytree(contracts_bundle.parent, copied_contract.parent, dirs_exist_ok=True)
            contract_text = text_at(contracts_bundle)
            contract_text = contract_text.replace(
                '"@ordessa/extension-api"', json.dumps((copied_shared / "api.js").as_uri())
            ).replace(
                '"@ordessa/ui-components/api"', json.dumps((copied_shared / "ui-components-api.js").as_uri())
            )
            copied_contract.write_text(contract_text, encoding="utf-8")
            (module_root / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
            node_probe = r"""const { pathToFileURL } = await import("node:url");
const shared = process.env.ORDESSA_F5_SHARED;
const carrier = process.env.ORDESSA_F5_CARRIER;
const [api, ui, contracts] = await Promise.all([
  import(pathToFileURL(shared + "/api.js").href),
  import(pathToFileURL(shared + "/ui-components-api.js").href),
  import(pathToFileURL(carrier).href),
]);
if (typeof api.Token !== "function") throw new Error("shared Token export unavailable");
if (!(ui.UiComponentsToken instanceof api.Token)) throw new Error("public UI token uses a different Token constructor");
if (contracts.UiComponentsToken !== ui.UiComponentsToken) throw new Error("extension carrier constructed a second UI token");
if (ui.UiComponentsToken.name !== "ordessa.ui-components.v1") throw new Error("public UI token identity changed");
console.log(JSON.stringify({ status: "pass", sameToken: true, sharedTokenType: true }));"""
            home = module_root / "home"
            home.mkdir()
            child_env = {
                "ELECTRON_RUN_AS_NODE": "1",
                "HOME": str(home),
                "PATH": os.defpath,
                "ORDESSA_F5_SHARED": str(copied_shared),
                "ORDESSA_F5_CARRIER": str(copied_contract),
            }
            executed = subprocess.run([str(electron), "-e", node_probe], cwd=module_root,
                                      env=child_env, text=True, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, timeout=20, check=False)
            if executed.returncode == 0:
                identity = json.loads(executed.stdout.splitlines()[-1])
                di_checks["runtimeIdentity"] = identity.get("status") == "pass"
            else:
                report["uiComponentsDI"]["runtimeError"] = {
                    "returnCode": executed.returncode,
                    "stderr": executed.stderr[-4000:],
                    "stdout": executed.stdout[-4000:],
                }
    except BaseException as exc:
        report["uiComponentsDI"]["runtimeError"] = {
            "type": type(exc).__name__, "message": str(exc),
        }
missing_di = [name for name, passed in di_checks.items() if not passed]
report["uiComponentsDI"] = {
    **report["uiComponentsDI"],
    "status": "pass" if not missing_di else "fail",
    "checks": di_checks,
    "missing": missing_di,
}

def wire_result(runtime, method, params):
    try:
        return {"status": "returned", "value": runtime.wire.dispatch(method, params)}
    except BaseException as exc:
        details = getattr(exc, "details", None)
        code = getattr(exc, "code", None)
        return {"status": "refused", "type": type(exc).__name__, "code": code,
                "message": str(exc), "details": details}

fixture_spec = importlib.util.spec_from_file_location("ordessa_closeout_controlled_fixture", controlled_fixture)
if fixture_spec is None or fixture_spec.loader is None:
    raise RuntimeError("controlled native fixture could not be loaded")
fixture_module = importlib.util.module_from_spec(fixture_spec)
sys.modules[fixture_spec.name] = fixture_module
fixture_spec.loader.exec_module(fixture_module)

DRAFT_LOCATION = {
    "kind": "draft", "connectionId": "controlled-connection",
    "draftId": "controlled-draft-1",
}
ATTACHMENT_ID = "attachment-controlled-1"
ATTACHMENT_BYTES = b"immutable controlled native attachment\\x00bytes"

def require_wire(runtime, method, params):
    outcome = wire_result(runtime, method, params)
    if outcome["status"] != "returned":
        raise RuntimeError(method + " refused: " + json.dumps(outcome, sort_keys=True, default=str))
    return outcome["value"]

def config_operation(runtime, target, patch):
    outcome = require_wire(runtime, "agent.config.submitOperation", {
        "target": target, "patch": patch, "sourceRef": "controlled-closeout-profile-intent"})
    if outcome.get("state") != "pending" or not outcome.get("operationId"):
        raise RuntimeError("Agent config operation did not enter pending state: " + repr(outcome))
    return outcome["operationId"]

def capture_conditions(runtime, target, mode):
    return require_wire(runtime, "agent.submission.capture.read", {
        "target": target, "mode": mode,
    })

def capture(submission_id, revision, text, operation_id, mode, expected_conditions):
    return {
        "submissionId": submission_id,
        "draft": {"draftId": DRAFT_LOCATION["draftId"], "draftRevision": revision,
                  "text": text, "attachmentIds": [ATTACHMENT_ID]},
        "configOperationIds": [operation_id], "schema": "agent-input/v1", "mode": mode,
        "expectedConditions": expected_conditions,
    }

def submit(runtime, target, captured):
    return require_wire(runtime, "agent.submitInput", {
        "target": target, "draftRevision": captured["draft"]["draftRevision"],
        "capture": captured,
    })

def query(runtime, target, submission_id):
    return require_wire(runtime, "agent.submission.query", {
        "target": target, "submissionId": submission_id,
    })

def make_runtime(data_path, effects_path, *, include_profile, mode):
    native = fixture_module.ControlledNativeFixture(
        effects_path, mode=mode, attachment_bytes={ATTACHMENT_ID: ATTACHMENT_BYTES})
    composition = fixture_module.controlled_product_composition(
        native_submit_port=native,
        fingerprint_port=fixture_module.test_protected_fingerprint(),
        submission_policy=fixture_module.controlled_submission_policy(),
    )
    runtime = composition.default_runtime(data_path, include_profile=include_profile)
    return runtime, native

def run_variant(name, include_profile, root, native_effects_path):
    result = {
        "status": "fail", "profileIncluded": include_profile, "rounds": [],
        "wireSubmissionRounds": [],
        "agentSubmission": {"status": "not-run"},
        "controlledHarness": {"status": "not-run"},
        "twoRoundHistory": {"status": "not-run"},
    }
    runtime = None
    try:
        runtime, native = make_runtime(root, native_effects_path,
                                      include_profile=include_profile, mode="createWithConfig")
        runtime.start()
        plugin_ids = [plugin.descriptor().id for plugin in runtime.plugin_selection]
        if (("ordessa.profile" in plugin_ids) is not include_profile):
            raise RuntimeError("product composition selected an unexpected Profile variant: " + repr(plugin_ids))
        hello = wire_result(runtime, "server.hello", {
            "clientVersions": ["wire/1"], "clientPresentationSupports": []})
        result["rounds"].append({"round": 1, "started": bool(runtime.started), "hello": hello})
        if hello["status"] != "returned":
            raise RuntimeError("server.hello failed before controlled submission")

        resolved = require_wire(runtime, "agent.session.resolve", {"location": DRAFT_LOCATION})
        target = resolved.get("target")
        if not isinstance(target, str) or not target:
            raise RuntimeError("Agent did not return a backend-minted target")
        native.bind_backend_target(target)

        first_operation = config_operation(runtime, target, {
            "model": "M1", "general.prompt": "Preserve this prompt"})
        first_config = require_wire(runtime, "agent.config.read", {"target": target})
        if first_config.get("revision") != 1:
            raise RuntimeError("first config revision is not 1: " + repr(first_config))
        native.set_mode("createWithConfig")
        first_conditions = capture_conditions(runtime, target, "createWithConfig")
        first_capture = capture("controlled-submission-1", 1, "first prompt",
                                first_operation, "createWithConfig", first_conditions)
        first = submit(runtime, target, first_capture)
        if first.get("outcome") != "accepted" or first.get("stage") != "completed":
            raise RuntimeError("first controlled native submission was not accepted/completed: " + repr(first))
        result["wireSubmissionRounds"].append({
            "round": 1, "submissionId": first.get("submissionId"),
            "outcome": first.get("outcome"), "stage": first.get("stage"),
        })
        result["agentSubmission"] = {"status": "partial", "submissions": [first]}
        if first.get("configApply") != {"outcome": "applied", "operationIds": [first_operation]}:
            raise RuntimeError("first config result was not separately settled: " + repr(first))

        second_operation = config_operation(runtime, target, {"model": "M2"})
        native.set_mode("existing")
        second_conditions = capture_conditions(runtime, target, "existing")
        second_capture = capture("controlled-submission-2", 2, "second prompt",
                                 second_operation, "existing", second_conditions)
        second = submit(runtime, target, second_capture)
        if second.get("outcome") != "accepted" or second.get("stage") != "completed":
            raise RuntimeError("second controlled native submission was not accepted/completed: " + repr(second))
        result["wireSubmissionRounds"].append({
            "round": 2, "submissionId": second.get("submissionId"),
            "outcome": second.get("outcome"), "stage": second.get("stage"),
        })
        final_config = require_wire(runtime, "agent.config.read", {"target": target})
        if (final_config.get("resolved") != {"model": "M2", "general.prompt": "Preserve this prompt"}
                or final_config.get("revision") != 4):
            raise RuntimeError("config owner did not settle both operations: " + repr(final_config))

        history_before = [query(runtime, target, submission_id) for submission_id in (
            "controlled-submission-1", "controlled-submission-2")]
        if any(item.get("outcome") != "accepted" or item.get("resend") is not False
               for item in history_before):
            raise RuntimeError("submission history was not queryable before restart: " + repr(history_before))
        sessions_before = require_wire(runtime, "agent.session.list", {"target": target})
        if sessions_before.get("source") != "native-query" or len(sessions_before.get("items", ())) != 1:
            raise RuntimeError("native session history was not queried: " + repr(sessions_before))
        counts_before = native.all_effect_counts()
        if len(counts_before) != 2 or set(counts_before.values()) != {1}:
            raise RuntimeError("native fixture did not record exactly one effect per round: " + repr(counts_before))
        result["rounds"][0].update({"target": target, "configRevision": final_config["revision"],
                                    "submissions": [first, second]})
        result["agentSubmission"] = {"status": "pass", "outcomes": [first["outcome"], second["outcome"]],
                                     "stages": [first["stage"], second["stage"]],
                                     "wireRounds": result["wireSubmissionRounds"]}
        result["controlledHarness"] = {"status": "pass", "modeDispatches": [
            "createWithConfig", "existing"], "effectCounts": sorted(counts_before.values()),
            "attachmentFixture": "immutable-bytes-in-isolated-test-root"}
        runtime.stop()
        runtime = None

        # New runtime, new domain journal object, and new controlled native
        # adapter over a separate effects database. Recovery is query-only.
        restarted, native_reopened = make_runtime(
            root, native_effects_path, include_profile=include_profile, mode="existing")
        runtime = restarted
        runtime.start()
        second_hello = wire_result(runtime, "server.hello", {
            "clientVersions": ["wire/1"], "clientPresentationSupports": []})
        result["rounds"].append({"round": 2, "started": bool(runtime.started), "hello": second_hello})
        if second_hello["status"] != "returned":
            raise RuntimeError("server.hello failed after restart")
        resolved_again = require_wire(runtime, "agent.session.resolve", {"location": DRAFT_LOCATION})
        if resolved_again.get("target") != target:
            raise RuntimeError("backend-minted target changed across restart")
        native_reopened.bind_backend_target(target)
        history_after = [query(runtime, target, submission_id) for submission_id in (
            "controlled-submission-1", "controlled-submission-2")]
        if any(item.get("outcome") != "accepted" or item.get("resend") is not False
               for item in history_after):
            raise RuntimeError("submission recovery query was incomplete or suggested resend: " + repr(history_after))
        sessions_after = require_wire(runtime, "agent.session.list", {"target": target})
        if sessions_after.get("source") != "native-query" or len(sessions_after.get("items", ())) != 1:
            raise RuntimeError("native session history was not verified after restart: " + repr(sessions_after))
        replay = submit(runtime, target, second_capture)
        counts_after = native_reopened.all_effect_counts()
        if (replay.get("replayed") is not True or replay.get("resend") is not False
                or counts_after != counts_before):
            raise RuntimeError("recovery replay changed native effect counts: " + repr({
                "replay": replay, "before": counts_before, "after": counts_after}))

        with sqlite3.connect(native_effects_path) as connection:
            rows = connection.execute(
                "SELECT payload FROM native_effect_events ORDER BY event_id").fetchall()
        payloads = [json.loads(row[0]) for row in rows]
        if len(payloads) != 2 or {item["mode"] for item in payloads} != {"existing", "createWithConfig"}:
            raise RuntimeError("independent native effect journal does not prove both dispatch modes")
        attachment_digest = hashlib.sha256(ATTACHMENT_BYTES).hexdigest()
        if any(item.get("attachmentSha256") != {ATTACHMENT_ID: attachment_digest}
               for item in payloads):
            raise RuntimeError("native effect log did not prove captured attachment bytes")
        if any(not all(key in item for key in ("configApply", "inputAcceptance", "runResult"))
               for item in payloads):
            raise RuntimeError("native effect log omitted a separately tracked result dimension")
        result["controlledHarness"]["attachmentSha256"] = attachment_digest
        result["controlledHarness"]["separateResults"] = [
            "configApply", "inputAcceptance", "runResult"]
        result["twoRoundHistory"] = {
            "status": "pass", "submissionQueries": len(history_after),
            "sessionHistorySource": sessions_after["source"],
            "targetStableAcrossRestart": True, "replayDidNotRedispatch": True,
            "nativeEffectCounts": sorted(counts_after.values()),
        }
        result["agentSubmission"]["status"] = "pass"
        result["status"] = "pass"
    except BaseException as exc:
        result["failure"] = {"type": type(exc).__name__, "message": str(exc),
                             "traceback": traceback.format_exc(limit=10)}
    finally:
        if runtime is not None:
            try:
                if runtime.started:
                    runtime.stop()
            except BaseException as exc:
                result.setdefault("cleanupErrors", []).append(type(exc).__name__ + ": " + str(exc))
                result["status"] = "fail"
                result.setdefault("failure", {
                    "type": type(exc).__name__, "message": "runtime cleanup failed after controlled run",
                })
    return result

try:
    from ordessa_server.bootstrap import _resolve_product_composition
    product = _resolve_product_composition()
    selected_plugins = tuple(product.default_plugins())
    selected_ids = [plugin.descriptor().id for plugin in selected_plugins]
    report["productSelection"] = {"status": "resolved", "pluginIds": selected_ids,
                                  "composition": type(product).__name__}
    if "ordessa.profile" not in selected_ids:
        raise RuntimeError("installed default product does not include ordessa.profile")
    report["productVariants"]["withProfile"] = run_variant(
        "withProfile", True, data_root / "withProfile", data_root / "native" / "withProfile.sqlite")
    report["productVariants"]["withoutProfile"] = run_variant(
        "withoutProfile", False, data_root / "withoutProfile",
        data_root / "native" / "withoutProfile.sqlite")
    report["controlledFixture"] = {
        "status": "pass", "name": "controlled_native_fixture.py",
        "isolatedPath": str(controlled_fixture),
        "effectStores": "separate SQLite files from product Environment and Agent journal",
    }
except BaseException as exc:
    report["productSelection"] = {"status": "fail", "type": type(exc).__name__, "message": str(exc),
                                   "traceback": traceback.format_exc(limit=10)}

print(json.dumps(report, sort_keys=True, default=str))
'''


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _run_f5_consumers(artifact_root: Path, work: Path, home: Path,
                      timeout: float) -> dict[str, Any]:
    """Run the independent packaged F5 consumer and preserve its JSON evidence."""
    runner = Path(__file__).with_name("closeout-f5-consumers.mjs")
    node = shutil.which("node")
    if not runner.is_file() or node is None:
        evidence = {
            "status": "fail",
            "reason": "independent F5 runner or Node runtime is unavailable",
            "runnerPresent": runner.is_file(),
            "nodePresent": node is not None,
        }
        return {
            "f5_react_consumer": evidence,
            "f5_nonreact_consumer": evidence,
            "f5ConsumerEvidence": evidence,
        }
    tmp = work / "f5-consumer-tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    env = {
        "HOME": str(home),
        "PATH": os.defpath,
        "TMPDIR": str(tmp),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
    }
    command = [node, str(runner), "--artifact-root", str(artifact_root)]
    virtual_display = shutil.which("xvfb-run")
    if virtual_display:
        # An owned, temporary QA display; never reuse user display credentials.
        command = [virtual_display, "-a", "--server-args=-screen 0 1440x900x24", *command]
    try:
        completed = subprocess.run(
            command,
            cwd=work, env=env, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=min(timeout, 180.0), check=False,
        )
    except subprocess.TimeoutExpired as exc:
        evidence = {
            "status": "fail", "reason": "independent F5 consumer timed out",
            "stdout": str(exc.stdout or "")[-5000:], "stderr": str(exc.stderr or "")[-5000:],
        }
        return {
            "f5_react_consumer": evidence,
            "f5_nonreact_consumer": evidence,
            "f5ConsumerEvidence": evidence,
        }
    except BaseException as exc:
        evidence = {
            "status": "fail", "reason": "independent F5 consumer could not execute",
            "type": type(exc).__name__, "message": str(exc),
        }
        return {
            "f5_react_consumer": evidence,
            "f5_nonreact_consumer": evidence,
            "f5ConsumerEvidence": evidence,
        }
    records: list[dict[str, Any]] = []
    parse_errors: list[str] = []
    for line in completed.stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            if line.strip():
                parse_errors.append(line[-1000:])
            continue
        if isinstance(value, dict) and "name" in value and "ok" in value:
            records.append(value)
    by_name = {record.get("name"): record for record in records}
    react = by_name.get("artifact-react-consumer")
    nonreact = by_name.get("artifact-api-consumers")
    process_ok = completed.returncode == 0 and not parse_errors

    def scene(record: dict[str, Any] | None, explanation: str) -> dict[str, Any]:
        passed = process_ok and record is not None and record.get("ok") is True
        return {
            "status": "pass" if passed else "fail",
            "consumer": record,
            "reason": None if passed else explanation,
        }

    evidence = {
        "status": "pass" if process_ok and react and react.get("ok") is True
        and nonreact and nonreact.get("ok") is True else "fail",
        "runner": str(runner.name),
        "node": str(Path(node).resolve()),
        "nodeDependency": "external QA tool, not a shipped runtime requirement",
        "display": "owned temporary Xvfb" if virtual_display else "absent; GUI evidence cannot pass",
        "returnCode": completed.returncode,
        "records": records,
        "parseErrors": parse_errors,
        "stderr": completed.stderr[-5000:],
    }
    return {
        "f5_react_consumer": scene(
            react,
            "independent packaged React consumer did not emit successful JSON evidence"),
        "f5_nonreact_consumer": scene(
            nonreact,
            "independent packaged non-React selection consumer did not emit successful JSON evidence"),
        "f5ConsumerEvidence": evidence,
    }


def _run(artifact_root: Path, timeout: float) -> dict[str, Any]:
    root = artifact_root.resolve(strict=True)
    prefix = root / "opt" / "ordessa"
    if not prefix.is_dir():
        raise ValueError(f"artifact root has no opt/ordessa: {root}")
    python = prefix / "python" / "bin" / "python3.12"
    if not python.exists() or not python.is_file():
        raise ValueError(f"artifact interpreter missing: {python}")
    resolved_python = python.resolve(strict=True)
    if not _within(resolved_python, prefix):
        raise ValueError(f"artifact interpreter escapes prefix: {python} -> {resolved_python}")

    required_files = (prefix / "bin" / "ordessa", prefix / "bin" / "acp",
                      prefix / "app" / "electron")
    missing_files = [str(path.relative_to(root)) for path in required_files if not path.exists()]
    report: dict[str, Any] = {
        "schema": "ordessa.closeout-controlled.v1",
        "artifactRoot": str(root),
        "interpreter": str(resolved_python),
        "requiredFiles": {str(path.relative_to(root)): path.exists() for path in required_files},
        "scenes": {},
    }
    if missing_files:
        report["scenes"]["runtime_files"] = {"status": "fail", "missing": missing_files}
        return report
    report["scenes"]["runtime_files"] = {"status": "pass"}

    with tempfile.TemporaryDirectory(prefix="ordessa-closeout-") as tmp:
        tmp_path = Path(tmp)
        home = tmp_path / "home"
        data_root = tmp_path / "data"
        work = tmp_path / "cwd"
        for path in (home, data_root, work):
            path.mkdir(parents=True, exist_ok=True)
        env = {
            "HOME": str(home),
            "PATH": os.pathsep.join((str(prefix / "bin"), "/usr/bin", "/bin")),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONNOUSERSITE": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "ORDESSA_BUNDLED_ROOT": str(prefix),
            "ORDESSA_DATA_ROOT": str(data_root),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
        }
        for path in (env["XDG_CONFIG_HOME"], env["XDG_CACHE_HOME"], env["XDG_DATA_HOME"]):
            Path(path).mkdir(parents=True, exist_ok=True)
        # Do not inherit developer path overrides, secrets, provider tokens, or
        # service endpoints. The controlled fixture supplies only an
        # in-memory fake fingerprint key and isolated native-effect database.
        repo_candidates = [str(Path.cwd().resolve()), str(Path(__file__).resolve().parents[2])]
        fixture_source = Path(__file__).with_name("controlled_native_fixture.py")
        if not fixture_source.is_file():
            report["scenes"]["controlled_fixture"] = {
                "status": "fail", "reason": "controlled native fixture is missing",
                "path": str(fixture_source),
            }
            return report
        fixture_copy = tmp_path / "controlled_native_fixture.py"
        shutil.copy2(fixture_source, fixture_copy)
        command = [
            str(resolved_python), "-I", "-c", _ARTIFACT_DRIVER,
            str(prefix), str(data_root), json.dumps(REQUIRED_DISTRIBUTIONS),
            json.dumps(REQUIRED_IMPORTS), json.dumps(repo_candidates), str(fixture_copy),
        ]
        try:
            completed = subprocess.run(command, cwd=work, env=env, text=True,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            report["scenes"]["artifact_runtime"] = {
                "status": "fail", "reason": "artifact interpreter timed out",
                "timeoutSeconds": timeout, "stdout": exc.stdout, "stderr": exc.stderr,
            }
            return report
        report["process"] = {"returnCode": completed.returncode, "stderr": completed.stderr[-12000:]}
        try:
            probe = json.loads(completed.stdout.splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            report["scenes"]["artifact_runtime"] = {
                "status": "fail", "reason": "artifact interpreter returned no JSON report",
                "stdout": completed.stdout[-12000:],
            }
            return report
        report["probe"] = probe
        report["scenes"]["controlled_fixture"] = probe.get("controlledFixture", {
            "status": "fail", "reason": "artifact driver did not load controlled native fixture"})
        required_missing = probe.get("missingRequired", [])
        source_free = probe.get("sourceFree", {})
        report["scenes"]["required_python_closure"] = {
            "status": "pass" if not required_missing else "fail",
            "missing": required_missing,
        }
        report["scenes"]["source_free_imports"] = {
            "status": source_free.get("status", "fail"),
            "violations": source_free.get("violations", []),
        }
        report["scenes"]["ui_components_di"] = probe.get("uiComponentsDI", {
            "status": "fail", "reason": "artifact probe did not inspect the UI Components DI closure"})
        product_variants = probe.get("productVariants", {})
        for name in ("withProfile", "withoutProfile"):
            variant = product_variants.get(name)
            if variant is None:
                report["scenes"][name] = {"status": "fail", "reason": "variant was not constructed"}
                continue
            rounds = variant.get("rounds", [])
            runtime_ok = (variant.get("status") == "pass" and len(rounds) == 2 and all(
                item.get("started") and item.get("hello", {}).get("status") == "returned"
                for item in rounds))
            report["scenes"][name] = {
                "status": "pass" if runtime_ok else "fail",
                "rounds": rounds,
                "failure": variant.get("failure"),
                "wireSubmissionRounds": variant.get("wireSubmissionRounds", []),
                "agentSubmission": variant.get("agentSubmission"),
                "controlledHarness": variant.get("controlledHarness"),
                "twoRoundHistory": variant.get("twoRoundHistory"),
            }
        # The independent F5 consumer runner emits one JSON object per real
        # artifact scene. Parse those outcomes rather than looking for source
        # call markers in minified bundles.
        f5_report = _run_f5_consumers(prefix, work, home, timeout)
        report["f5ConsumerEvidence"] = f5_report.pop("f5ConsumerEvidence")
        report["scenes"].update(f5_report)
        if "probe" in report:
            report["probe"]["f5Consumers"] = report.get("f5ConsumerEvidence", {})
        report["scenes"]["agent_harness_two_rounds_history"] = {
            "status": "pass" if all(
                product_variants.get(name, {}).get("status") == "pass"
                and product_variants.get(name, {}).get("twoRoundHistory", {}).get("status") == "pass"
                for name in ("withProfile", "withoutProfile")) else "fail",
            "withProfile": product_variants.get("withProfile", {}).get("twoRoundHistory"),
            "withoutProfile": product_variants.get("withoutProfile", {}).get("twoRoundHistory"),
            "agentSubmission": {
                name: product_variants.get(name, {}).get("agentSubmission")
                for name in ("withProfile", "withoutProfile")},
            "controlledHarness": {
                name: product_variants.get(name, {}).get("controlledHarness")
                for name in ("withProfile", "withoutProfile")},
            "reason": None if all(product_variants.get(name, {}).get("status") == "pass"
                                  for name in ("withProfile", "withoutProfile")) else
                "both Profile variants must prove two actual wire submissions and restart history",
        }
        report["scenes"]["artifact_runtime"] = {
            "status": "pass" if completed.returncode == 0 else "fail",
            "returnCode": completed.returncode,
            "stderr": completed.stderr[-4000:],
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_root", type=Path,
                        help="unpacked deb root containing opt/ordessa (not the repository)")
    parser.add_argument("--timeout", type=float, default=120.0,
                        help="maximum seconds for the isolated artifact probe (default: 120)")
    parser.add_argument("--json-out", type=Path,
                        help="also write the machine-readable report to this path")
    args = parser.parse_args()
    try:
        report = _run(args.artifact_root, args.timeout)
    except BaseException as exc:
        report = {
            "schema": "ordessa.closeout-controlled.v1",
            "scenes": {"artifact_setup": {"status": "fail", "type": type(exc).__name__,
                                          "reason": str(exc)}},
        }
    serialized = json.dumps(report, indent=2, sort_keys=True, default=str)
    print(serialized)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(serialized + "\n", encoding="utf-8")
    statuses = [scene.get("status") for scene in report.get("scenes", {}).values()]
    return 0 if statuses and all(status == "pass" for status in statuses) else 1


if __name__ == "__main__":
    raise SystemExit(main())
