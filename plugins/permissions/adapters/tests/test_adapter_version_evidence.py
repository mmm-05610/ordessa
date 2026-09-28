"""T020 — the declared `adapter_versions` pin must be a backed version fact.

Measurement (full evidence: `specs/011-q5-safety/evidence/t020-red-*.txt`):
`Installation.adapter_version` is supplied by
`RuntimeAdapter.describe_installation()`
(`plugins/harness/api/src/ordessa_harness_api/contracts.py:385-388`); the C4
admission consults `descriptor.adapter_versions.contains(installation.adapter_version)`
(`plugins/harness/src/ordessa_harness/application/configuration_service.py:153`).
This tree ships NO production `describe_installation` implementer: the only
Installation ever observed in-tree is the controlled fixture
(`plugins/harness/tests/fixtures/external_adapter/src/ordessa_test_external_adapter/__init__.py:69`,
`adapter_version=(1, 0, 0)`, harness `test-external`). Therefore an unbounded
minimum-only range like the former `VersionRange((1, 0, 0))` (= `[1.0.0, ∞)`)
was a self-declared widening: nothing in this tree observed any runtime
adapter at 1.0.0 or promised compatibility with every future one. The only
version fact this package can back is its own release pin —
`version = "0.1.0"`, `plugins/permissions/adapters/pyproject.toml:7` — which
is the same class of fact the Sandbox facet pins for itself
(`plugins/assets/sandbox/adapters/src/ordessa_sandbox_adapters/points.py:66`).

These tests pin the declaration to that measured fact; moving the release
version without moving the claim (or re-widening the range) is red here.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from ordessa_harness_api import VersionRange

from ordessa_permissions_adapters.contribution import (
    _ADAPTER_VERSION,
    default_configuration_descriptors,
)

PKG_DIR = Path(__file__).resolve().parents[1]


def _release_pin() -> tuple[int, int, int]:
    """The distribution's own release version, read from its pyproject."""
    data = tomllib.loads((PKG_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    core = data["project"]["version"].split("-", 1)[0].split("+", 1)[0]
    parts = [int(segment) for segment in core.split(".") if segment != ""]
    parts += [0] * (3 - len(parts))
    return tuple(parts[:3])


def test_adapter_version_pin_is_exact_and_backed_by_the_release_fact() -> None:
    pin = _release_pin()
    assert _ADAPTER_VERSION.minimum == pin, (
        "the declared adapter pin must equal this distribution's release "
        f"version fact (pyproject.toml, got {pin})")
    assert _ADAPTER_VERSION.maximum == pin, (
        "adapter_versions must stay an exact measured pin: an unbounded "
        "maximum is a widening no observation in this tree backs")


def test_every_default_descriptor_carries_the_backed_pin() -> None:
    for descriptor in default_configuration_descriptors():
        assert descriptor.adapter_versions == _ADAPTER_VERSION, (
            f"{descriptor.adapter_id} must publish the backed pin, never a "
            "per-brand self-declared range")
        assert isinstance(descriptor.adapter_versions, VersionRange)
