"""An independent root method uses the same captured-source compiler path."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from ordessa_engineering.methods import compile_method, load_method, validate_method
from ordessa_engineering.methods.compilation.encoding import program_to_canonical
from ordessa_engineering.methods.definitions.models import (
    CapabilityDescriptor,
    CompilationCapabilities,
    MethodSource,
)
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader


REPO_ROOT = Path(__file__).resolve().parents[4]
ALTERNATE_METHOD = REPO_ROOT / "methods/incremental-engineering/examples/alternate-method"


def _fixture_capabilities() -> CompilationCapabilities:
    """Use only the explicitly fixture-only descriptors shipped with this method."""
    catalog = json.loads((ALTERNATE_METHOD / "catalog.json").read_bytes())
    assert catalog["fixture_only"] is True
    descriptors = tuple(CapabilityDescriptor(**item) for item in catalog["capabilities"])
    return CompilationCapabilities(
        descriptors,
        registry_snapshot_ref="fixture:alternate-method",
        trust_class="fixture",
    )


def test_alternate_root_method_loads_validates_and_compiles_without_method_id_branch():
    loaded_result = load_method(MethodSource(ALTERNATE_METHOD), reader=FileResourceReader())
    assert loaded_result.ok and loaded_result.value is not None
    loaded = loaded_result.value

    capabilities = _fixture_capabilities()
    report = validate_method(loaded, capabilities)
    assert report.valid, report.diagnostics
    assert any(item.code == "FIXTURE_CAPABILITIES_ONLY" for item in report.diagnostics)

    compiled_result = compile_method(loaded, capabilities, "test.compiler/1")
    assert compiled_result.ok and compiled_result.value is not None, compiled_result.error
    program = program_to_canonical(compiled_result.value.program)
    assert program["workflow"]["workflow_id"] == "alternate-note-review"
    assert [item["document_type"] for item in program["documents"]] == ["maintenance-note"]
    assert [item["standard_id"] for item in program["standards"]] == ["bounded-note"]
    assert {item["capability_id"] for item in program["capability_bindings"]} == {
        "engineering.reviews.request",
        "ordessa.schema.validate",
    }


def test_alternate_method_compiler_rebuilds_from_captured_bytes():
    loaded_result = load_method(MethodSource(ALTERNATE_METHOD), reader=FileResourceReader())
    assert loaded_result.ok and loaded_result.value is not None
    loaded = loaded_result.value
    capabilities = _fixture_capabilities()

    # A caller cannot replace the captured workflow while retaining the original
    # parsed projection and expect the compiler to accept the modified bytes.
    resource = next(item for item in loaded.source_bundle.resources if item.resource_id == "workflow.note")
    forged_capture = replace(
        resource,
        captured=replace(resource.captured, data=resource.captured.data + b"\n# forged"),
    )
    forged_bundle = replace(loaded.source_bundle, resources=tuple(
        forged_capture if item.resource_id == resource.resource_id else item
        for item in loaded.source_bundle.resources
    ))
    object.__setattr__(loaded, "source_bundle", forged_bundle)

    result = compile_method(loaded, capabilities, "test.compiler/1")
    assert not result.ok and result.error is not None
    assert result.error.code in {
        "CAPTURED_RESOURCE_DECLARATION_MISMATCH",
        "LOADED_PROJECTION_INVALID",
    }
