"""Named model input from an approved existing product configuration file.

No issuer, spawn, auth file, RPC endpoint, global environment inheritance or
credential persistence. Trusted composition supplies the original start check
and exact admitted launch after fixed Profile materialization.
"""
from pathlib import Path
import os
import re

from ordessa_environments import EnvironmentRefused

APPROVED_OPENCODE_SOURCES = frozenset({
    '/home/maoqh/projects/ordessa/.env',
    '/home/maoqh/projects/ordessa/worktree/nightly-restructure-20261009/.env',
})


class ExistingOpenCodeInput:
    """Only the explicitly user-approved sources; compatibility is local parsing."""
    def __init__(self, source, *, variable_name='OPENCODE_API_KEY'):
        self.source = str(Path(source).absolute())
        if self.source not in APPROVED_OPENCODE_SOURCES:
            raise EnvironmentRefused('Model capability source was not selected by the product')
        if (type(variable_name) is not str
                or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', variable_name) is None):
            raise EnvironmentRefused('An explicit model input variable name is required')
        self.variable_name = variable_name

    def __repr__(self):
        return '<ExistingOpenCodeInput value=unread>'

    def read(self):
        try:
            fd = os.open(self.source, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, 'rb') as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError()
            text = raw.decode('utf-8-sig').strip()
            fields, unnamed = {}, []
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                match = re.fullmatch(r'(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*(.*)', line)
                if match:
                    name, value = match.groups()
                    if name in fields:
                        raise ValueError()
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                        value = value[1:-1]
                    fields[name] = value
                else:
                    unnamed.append(line)
            # Unnamed historical entries are never selected by their position.
            # A unique explicit name is the only usable input in a mixed file.
            if self.variable_name not in fields:
                raise ValueError()
            value = fields[self.variable_name]
            if not value or len(value) > 16384 or any(ord(c) < 33 or ord(c) > 126 for c in value):
                raise ValueError()
            return bytearray(value.encode('ascii'))
        except Exception:
            raise EnvironmentRefused('Approved local model input is unavailable or ambiguous') from None
