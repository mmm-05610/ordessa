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
    policy = resources.files("pacthold.harness_kit").joinpath(
        "_deployment", "native-artifact-policy.mjs")
    if policy.is_file():
        with resources.as_file(policy) as file:
            yield node, file
        return
    # Source checkout (032): the policy stays with the harness group runtime
    # assets; the kernel package carries only the verifier.
    module = Path(__file__).resolve()
    for parent in module.parents:
        candidate = parent / "plugins" / "harness" / "runtime" / "native-artifact-policy.mjs"
        if candidate.is_file():
            yield node, candidate
            return
    raise RuntimeError("NATIVE_VERIFIER_POLICY_MISSING")
