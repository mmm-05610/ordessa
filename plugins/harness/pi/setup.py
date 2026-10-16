"""Relocate native imports into the installed Python wheel peer layout."""
import os
from pathlib import Path
import re

from setuptools import setup
from setuptools.command.build_py import build_py


class NativeBuild(build_py):
    def run(self):
        super().run()
        root = Path(self.build_lib)
        pattern = re.compile(r'''(["'])(?:\.\./)+packages/execution/agents/src/ordessa_execution_agents/([^"']+)\1''')
        for module in (root / 'ordessa_harness_pi').rglob('*'):
            if module.suffix not in ('.js', '.mjs'):
                continue
            def relocate(match):
                relative = Path(match[2])
                if relative.is_absolute() or '..' in relative.parts:
                    raise ValueError('Invalid native Execution dependency path')
                target = root / 'ordessa_execution_agents' / relative
                path = os.path.relpath(target, module.parent).replace(os.sep, '/')
                return match[1] + path + match[1]
            module.write_text(pattern.sub(relocate, module.read_text()))


setup(cmdclass={'build_py': NativeBuild})
