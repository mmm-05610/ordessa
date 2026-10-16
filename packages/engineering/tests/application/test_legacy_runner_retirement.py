"""Retirement boundary: the old DID runner is history, not a callable path."""
import importlib.util


def test_old_runner_module_paths_are_absent():
    for name in (
        "ordessa_engineering.workflow",
        "ordessa_engineering.application.orchestration.runs",
        "ordessa_engineering.application.orchestration.steps.workflow",
        "ordessa_engineering.application.orchestration.steps.inputs",
        "ordessa_engineering.application.usecases.reviews.workflow",
        "ordessa_engineering.application.usecases.packages.service",
        "ordessa_engineering.application.usecases.changes.acceptance",
    ):
        assert importlib.util.find_spec(name) is None
