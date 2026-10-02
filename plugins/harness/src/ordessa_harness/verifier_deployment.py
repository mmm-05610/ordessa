"""Locate Harness verifier code and the deployment-selected Node interpreter."""
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
import shutil


@contextmanager
def installed_verifier():
    """Use packaged policy bytes, or the explicit development source layout.

    The package build copies the canonical JS policy without transforming it.
    No caller-supplied policy or alternate verifier is accepted. PATH selection
    matches the native access-entry composition's interpreter selection.
    """
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("NATIVE_VERIFIER_NODE_MISSING")
    policy = resources.files("ordessa_harness").joinpath(
        "_deployment", "native-artifact-policy.mjs")
    if policy.is_file():
        with resources.as_file(policy) as file:
            yield node, file
        return
    module = Path(__file__).resolve()
    source = module.parent.parent
    root = source.parent
    if (source.name != "src" or module.parent.name != "ordessa_harness"
            or not (root / "pyproject.toml").is_file()):
        raise RuntimeError("NATIVE_VERIFIER_POLICY_MISSING")
    source_policy = root / "runtime" / "native-artifact-policy.mjs"
    if not source_policy.is_file():
        raise RuntimeError("NATIVE_VERIFIER_POLICY_MISSING")
    yield node, source_policy
