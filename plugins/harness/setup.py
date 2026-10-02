"""Carry the canonical Harness JS verifier into non-editable distributions."""
from pathlib import Path
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py


class HarnessBuildPy(build_py):
    def run(self):
        super().run()
        source = Path(__file__).parent / "runtime" / "native-artifact-policy.mjs"
        if not source.is_file():
            raise RuntimeError("NATIVE_VERIFIER_POLICY_MISSING")
        destination = Path(self.build_lib) / "ordessa_harness" / "_deployment"
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination / source.name)


setup(cmdclass={"build_py": HarnessBuildPy})
