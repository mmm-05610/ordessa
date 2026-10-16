"""Wheel build: relocate native imports to installed peer distributions.

Source modules use the workspace layout. Wheel modules use the ordinary
site-packages peer layout. No runtime source-tree lookup/fallback is shipped.
"""
import os
from pathlib import Path
import re

from setuptools import setup
from setuptools.command.build_py import build_py


class NativeBuild(build_py):
    def run(self):
        super().run()
        root = Path(self.build_lib)
        pattern = re.compile(r'''(["'])(?:\.\./)+infrastructure/src/ordessa_infrastructure/([^"']+)\1''')
        for module in (root / 'ordessa_execution_agents').rglob('*'):
            if module.suffix not in ('.js', '.mjs'):
                continue
            def relocate(match):
                relative = Path(match[2])
                if relative.is_absolute() or '..' in relative.parts:
                    raise ValueError('Invalid native Infrastructure dependency path')
                target = root / 'ordessa_infrastructure' / relative
                path = os.path.relpath(target, module.parent).replace(os.sep, '/')
                return match[1] + path + match[1]
            text = module.read_text()
            module.write_text(pattern.sub(relocate, text))


setup(cmdclass={'build_py': NativeBuild})
