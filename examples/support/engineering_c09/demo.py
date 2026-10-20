"""Explicit, synthetic C09 mechanism demo; never reads a product DID."""
from __future__ import annotations

from ordessa_engineering.adapters.execution.registry_sources import load_registry
from ordessa_engineering.adapters.execution.package_files import PackageFiles
from ordessa_engineering.adapters.execution.review_decision import select_review
from ordessa_engineering.adapters.persistence.sqlite.workflow_transactions import WorkflowTransactions
from ordessa_engineering.domain.artifacts.library_material_codec import material_ref_to_dict
import argparse
import json
from pathlib import Path

from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.application.orchestration.steps.workflow import EngineeringWorkflow
from examples.support.engineering_c09.fixtures import import_c09_methods, install_c09_materials


def absolute_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("path must be absolute")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True, type=absolute_path,
                        help="new isolated SQLite path; it must not already exist")
    parser.add_argument("--export-directory", required=True, type=absolute_path,
                        help="new output directory; it must not already exist")
    parser.add_argument("--method", choices=("source-first", "standard-first"),
                        default="source-first")
    parser.add_argument("--accept", action="store_true",
                        help="record explicit synthetic local acceptance and resume")
    parser.add_argument("--methods-directory", required=True, type=absolute_path,
                        help="explicit directory containing source-first.v1.json and standard-first.v1.json")
    args = parser.parse_args()

    library = EngineeringLibrary.create(args.library, library_id="prototype-c09-fixture")
    try:
        workflow = EngineeringWorkflow(library, load_registry=load_registry, files=PackageFiles(), transactions=WorkflowTransactions(library), select_review=select_review)
        methods = {name: json.loads((args.methods_directory / f"{name}.v1.json").read_text())
                   for name in ("source-first", "standard-first")}
        method = import_c09_methods(workflow, methods=methods)[args.method]
        materials = install_c09_materials(workflow, method_ref=method)
        refs = {key: material_ref_to_dict(value) for key, value in materials.items()
                if key != "source_maps"}
        refs["source_maps"] = [material_ref_to_dict(ref) for ref in materials["source_maps"]]
        result = workflow.start(run_id="synthetic-demo", method_ref=method,
            inputs={"refs": refs, "export_directory": str(args.export_directory)})
        if result["status"] == "WAITING_FOR_ACCEPTANCE" and args.accept:
            workflow.accept(run_id="synthetic-demo", operation_id="synthetic-demo:accept",
                            caller_kind="synthetic-local-explicit")
            result = workflow.resume("synthetic-demo")
        print(json.dumps({"run_id": "synthetic-demo", "status": result["status"],
                          "step_ids": [row["step_id"] for row in result["steps"]]},
                         indent=2, sort_keys=True))
        return 0 if result["status"] in {"WAITING_FOR_ACCEPTANCE", "SLICE_DONE"} else 2
    except EngineeringError as exc:
        print(json.dumps({"status": "REFUSED", "code": exc.code}, sort_keys=True))
        return 2
    finally:
        library.close()


if __name__ == "__main__":
    raise SystemExit(main())
