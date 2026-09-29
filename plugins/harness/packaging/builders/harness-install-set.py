"""Harness install-set producer: one deployment document for all families.

Work Order 46 stage A. Walks the registry's families, builds or verifies each
family's runtime artifact, and emits:

  <output>/deployment.json      one document installing every family
  <output>/install-set.json     the operator's map: artifacts, digests, mount
                                tokens, credential environment, native model
  <output>/models/<family>.json each family's model document

The deployment document is the single artifact a Server needs (zero host
paths: artifacts bind through `--mount` tokens, plugin sources through
`--plugin-root`). `install-set.json` additionally records the machine-local
mount bindings — it is the operator's map, not a deployment input.

usage: harness-install-set.py --output DIR
       [--artifact <family>=<path>]... [--worker-bundle DIR] [--json]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[2]  # the harness plugin root
PLUGIN = REPO
SCRIPT = "scripts/server-round1/harness-install-set.py"

#: Every family the install set must cover, in registry order.
FAMILIES = ("codex", "claude-code", "opencode", "hermes", "dsh", "kilo", "pi")

#: Families whose runtime artifact is a directory closure built by a builder
#: script; the remaining ones (opencode) pin a single-file binary instead.
CLOSURE_FAMILIES = ("codex", "claude-code", "hermes", "dsh", "kilo", "pi")

MODULE_NAMES = {
    "codex": "codex", "claude-code": "claude", "opencode": "opencode",
    "hermes": "hermes", "dsh": "dsh", "kilo": "kilo", "pi": "pi",
}

BUILDERS = {
    "codex": "build-codex-runtime-artifact.mjs",
    "claude-code": "build-claude-runtime-artifact.mjs",
    "hermes": "build-hermes-runtime-artifact.mjs",
    "dsh": "build-dsh-runtime-artifact.mjs",
    "kilo": "build-kilo-runtime-artifact.mjs",
    "pi": "build-pi-runtime-artifact.mjs",
}

#: Which `packaging/` directory holds the npm root a family's builder installs
#: from. The key is the *family* id, the value the *directory* name, and the two
#: are not the same string: `claude-code` owns `packaging/claude/` (the name the
#: builders and artifact gates already use). Every family with an npm root now
#: owns exactly one, because the shared Codex/Pi lock was split; a family
#: missing here (hermes, opencode) has no npm root at all.
NPM_ROOTS = {
    "codex": "codex", "pi": "pi",
    "claude-code": "claude",
    "dsh": "dsh", "kilo": "kilo",
}

REPORT: dict = {"script": SCRIPT}


def fail(code: str, message: str) -> None:
    REPORT["result"] = "HARNESS_INSTALL_SET_FAILED"
    REPORT["code"] = code
    REPORT["error"] = message
    destination = REPORT.get("reportPath")
    if destination is not None:
        Path(destination).write_text(json.dumps(REPORT, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({"result": REPORT["result"], "code": code, "error": message}), file=sys.stderr)
    raise SystemExit(1)


def sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def load_production(family: str):
    module = importlib.import_module(f"ordessa_harness.{MODULE_NAMES[family]}.production")
    return module


def moduleattr(module, *names, default=None):
    for name in names:
        if hasattr(module, name):
            return getattr(module, name)
    return default


def verify_artifact_tree(path: Path) -> str:
    from pacthold_runtime_compat.resource_contracts.runtime_artifacts import runtime_artifact_tree_digest

    return runtime_artifact_tree_digest(path)


def verify_binary(path: Path) -> str:
    return sha256(path.read_bytes())


def build_closure(family: str, builder: str, output: Path,
                  previous_digest: str | None = None) -> Path:
    # The closure builders require the family's npm dependencies to be
    # installed in its packaging npm root first; `NPM_ROOTS` is the one place
    # that says which, so no family silently skips `npm ci` on a name mismatch.
    # None of these is read by the run chain.
    npm_directory = NPM_ROOTS.get(family)
    npm_root = PLUGIN / "packaging" / npm_directory if npm_directory is not None else None
    if npm_root is not None and npm_root.is_dir() and not (npm_root / "node_modules").is_dir():
        ci = subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=npm_root,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=1800)
        if ci.returncode != 0:
            fail("HARNESS_INSTALL_SET_NPM_CI_FAILED",
                 f"{family}: npm ci failed: "
                 f"{' '.join(ci.stdout.decode('utf-8', 'replace')[-300:].split())}")
    target = output / "artifacts" / family
    if target.is_dir() and previous_digest:
        try:
            if verify_artifact_tree(target) == previous_digest:
                # Idempotent: the existing tree still matches the recorded
                # digest, so the npm/build pipeline is skipped entirely.
                return target
        except Exception:
            pass
    if target.is_dir():
        aside = output / "artifacts" / f"{family}.previous-{int(time.time())}"
        shutil.move(str(target), str(aside))
    if target.is_dir():
        # Idempotent rebuild: an existing tree is kept only when it still
        # matches its own recorded manifest; builders refuse existing outputs,
        # so a rebuild moves the old tree aside first.
        previous = target.with_name(f"{family}.previous")
        if previous.exists():
            shutil.rmtree(previous, ignore_errors=True)
        shutil.move(str(target), str(previous))
    run = ["node", str(REPO / "packaging" / "builders" / builder),
           "--output", str(target), "--json"]
    result = subprocess.run(run, cwd=REPO, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=3600)
    tail = result.stdout.decode("utf-8", "replace")[-600:]
    if result.returncode != 0:
        fail("HARNESS_INSTALL_SET_BUILD_FAILED",
             f"{family} builder failed ({result.returncode}): {tail}")
    if not target.is_dir():
        fail("HARNESS_INSTALL_SET_BUILD_FAILED",
             f"the {family} builder produced no artifact directory")
    return target


def family_entry(family: str, module, artifact_ref: dict) -> dict:
    """One family's deployment seat from its own production template."""
    if family == "opencode":
        document = module.deployment_document(
            binary_token=artifact_ref["token"], binary_digest=artifact_ref["digest"])
    else:
        document = module.deployment_document(
            artifact_token=artifact_ref["token"], tree_digest=artifact_ref["digest"])
    harnesses = document.get("harnesses") or []
    if len(harnesses) != 1:
        fail("HARNESS_INSTALL_SET_SEAT_INVALID",
             f"{family}: expected exactly one harness seat, got {len(harnesses)}")
    return harnesses[0]


def models_document_for(module, family: str) -> dict:
    if hasattr(module, "models_document"):
        return module.models_document()
    return {
        "productModelId": module.PRODUCT_MODEL_ID,
        "officialBaseUrl": str(module.OFFICIAL_BASE_URL),
        "credentialEnvironment": module.CREDENTIAL_ENVIRONMENT,
        "note": "this family declares no separate model catalogue module; "
                "the deployment template's own model resolution applies",
    }


def native_model_value(module):
    return moduleattr(module, "NATIVE_MODEL_VALUE", "NATIVE_MODEL_ID",
                      "NATIVE_MODEL_SELECTION")


def adapter_summary(module):
    command = moduleattr(module, "ADAPTER_COMMAND", default="/usr/bin/node")
    args = list(moduleattr(module, "ADAPTER_ARGS", default=()))
    entry = moduleattr(module, "ADAPTER_ARTIFACT_ENTRY", default=None)
    binary_target = moduleattr(module, "BINARY_TARGET", default=None)
    return {
        "command": command,
        "args": args,
        "adapterEntry": entry,
        "binaryTarget": binary_target,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/home/maoqh/.agentbox-all-harnesses"))
    parser.add_argument("--artifact", action="append", default=[],
                        metavar="FAMILY=PATH",
                        help="reuse an existing verified artifact for one family")
    parser.add_argument("--skip-builds", action="store_true",
                        help="only reuse --artifact families; record the rest as missing")
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args()

    output = options.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    REPORT["output"] = str(output)

    reuse: dict[str, Path] = {}
    for item in options.artifact:
        token, _, path = item.partition("=")
        if token not in FAMILIES or not path:
            fail("HARNESS_INSTALL_SET_ARTIFACT_ARG_INVALID", f"bad --artifact {item!r}")
        reuse[token] = Path(path).resolve()

    (output / "models").mkdir(parents=True, exist_ok=True)
    previous_install_set: dict = {}
    previous_file = output / "install-set.json"
    if previous_file.is_file():
        try:
            previous_install_set = json.loads(previous_file.read_text(encoding="utf-8"))
        except ValueError:
            previous_install_set = {}

    install_set: dict[str, Any] = {
        "schemaVersion": 1,
        "families": {},
        "mountBindings": {},
        "pluginRoot": str(PLUGIN),
    }
    deployment_seats = []
    manifest_paths = {}

    for family in FAMILIES:
        module = load_production(family)
        artifact_target = moduleattr(module, "ARTIFACT_TARGET",
                                     default=moduleattr(module, "BINARY_TARGET"))
        artifact_name = moduleattr(module, "ARTIFACT_NAME",
                                   default=moduleattr(module, "BINARY_NAME", default=family))
        token = f"{artifact_name}"
        digest = None
        facts: dict[str, Any] = {"family": family}

        if family in reuse:
            source = reuse[family]
            if source.is_dir():
                digest = verify_artifact_tree(source)
            elif source.is_file():
                digest = verify_binary(source)
            else:
                fail("HARNESS_INSTALL_SET_ARTIFACT_MISSING",
                     f"--artifact {family}={source} does not exist")
            facts["artifact"] = {"path": str(source), "treeDigest": digest,
                                 "reused": True, "source": "operator"}
            manifest_paths[f"{token}-artifact"] = str(source)
        elif family in CLOSURE_FAMILIES:
            previous_facts = (previous_install_set.get("families") or {}).get(family) or {}
            source = build_closure(family, BUILDERS[family], output,
                                   previous_digest=previous_facts.get("treeDigest"))
            digest = verify_artifact_tree(source)
            facts["artifact"] = {"path": str(source), "treeDigest": digest,
                                 "reused": False, "built": True}
            manifest_paths[f"{token}-artifact"] = str(source)
        else:
            facts["artifact"] = {
                "missing": True,
                "note": "no builder and no --artifact given; the seat is emitted "
                        "but the install set records it as not provisioned",
            }
            digest = None

        if family == "opencode":
            binary = None
            for candidate in (Path(os.environ.get("AGENTBOX_OPENCODE_BINARY", "")),
                              output / "binaries" / "opencode"):
                if candidate.is_file():
                    binary = candidate
                    break
            if binary is None:
                fail("HARNESS_INSTALL_SET_BINARY_MISSING",
                     "opencode needs its pinned single-file binary "
                     "(AGENTBOX_OPENCODE_BINARY or --artifact opencode=<path>)")
            digest = verify_binary(binary)
            facts["binary"] = {"path": str(binary), "digest": digest}
            manifest_paths[f"{family}-binary"] = str(binary)

        if digest is None:
            install_set["families"][family] = facts
            continue

        if family == "opencode":
            binary = None
            for candidate in (Path(os.environ.get("AGENTBOX_OPENCODE_BINARY", "")),
                              output / "binaries" / "opencode"):
                if candidate.is_file():
                    binary = candidate
                    break
            if binary is None:
                fail("HARNESS_INSTALL_SET_BINARY_MISSING",
                     "opencode needs its pinned single-file binary "
                     "(AGENTBOX_OPENCODE_BINARY or --artifact opencode=<path>)")
            digest = verify_binary(binary)
            artifact_ref = {"token": f"{family}-binary", "digest": digest}
            facts["binary"] = {"path": str(binary), "digest": digest}
            facts["treeDigest"] = digest
            manifest_paths[f"{family}-binary"] = str(binary)
        else:
            artifact_ref = {"token": token, "digest": digest}

        entry = family_entry(family, module, artifact_ref)
        entry["id"] = family
        deployment_seats.append(entry)
        install_set["mountBindings"][artifact_ref["token"]] = (
            str(source) if family in reuse else
            str((output / "artifacts" / family).resolve())
            if family != "opencode" else str(binary))

        models_doc = models_document_for(module, family)
        (output / "models" / f"{family}.json").write_text(
            json.dumps(models_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        facts.update({
            "mountToken": artifact_ref["token"],
            "artifactTarget": str(artifact_target),
            "credentialEnvironment": module.CREDENTIAL_ENVIRONMENT,
            "credentialKind": module.CREDENTIAL_KIND,
            "productModelId": module.PRODUCT_MODEL_ID,
            "nativeModelValue": native_model_value(module),
            "adapter": adapter_summary(module),
            "stateProjectionTarget": moduleattr(module, "STATE_TARGET"),
            "modelsDocument": f"models/{family}.json",
            "treeDigest": digest,
        })
        install_set["families"][family] = facts

    deployment = {"schemaVersion": 1, "harnesses": deployment_seats}
    deployment_bytes = json.dumps(deployment, indent=2, sort_keys=True).encode()
    (output / "deployment.json").write_bytes(deployment_bytes)
    install_set["deploymentSha256"] = sha256(deployment_bytes)
    install_set["deploymentFamilies"] = [seat["id"] for seat in deployment_seats]
    install_set["realModelCalls"] = 0

    REPORT.update({
        "result": "HARNESS_INSTALL_SET_OK",
        "output": str(output),
        "deploymentSha256": install_set["deploymentSha256"],
        "deploymentFamilies": install_set["deploymentFamilies"],
        "families": install_set["families"],
        "model": {"realModelCalls": 0, "note": "the producer builds/verifies "
                                               "artifacts; it never calls a model"},
        "cost": {"authorizedRealModelCalls": 0, "estimatedCny": 0},
    })
    (output / "install-set.json").write_text(
        json.dumps(install_set, indent=1, sort_keys=True), encoding="utf-8")
    destination = REPORT.get("reportPath")
    if destination is not None:
        Path(destination).write_text(json.dumps(REPORT, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({"result": REPORT["result"], "output": str(output),
                      "families": install_set["deploymentFamilies"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
