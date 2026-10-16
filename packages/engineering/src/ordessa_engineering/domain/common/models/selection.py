"""Pure bounded byte/JSON-pointer selectors on supplied content."""
from dataclasses import dataclass
import re
from ..outcomes.diagnostics import ReferenceError
MAX_CONTENT_BYTES = 16 * 1024 * 1024

@dataclass(frozen=True)
class ContentSelector:
    """v1 byte range, whole capture, or canonical JSON value at a pointer."""
    kind: str
    start: int | None = None
    end: int | None = None
    pointer: str | None = None
    schema_version: int = 1

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ReferenceError('INVALID_SELECTOR')
        if self.kind == 'whole_capture':
            valid = self.start is None and self.end is None and self.pointer is None
        elif self.kind == 'byte_range':
            valid = (type(self.start) is int and type(self.end) is int
                     and 0 <= self.start <= self.end <= MAX_CONTENT_BYTES and self.pointer is None)
        elif self.kind == 'json_pointer':
            valid = (self.start is None and self.end is None and type(self.pointer) is str
                     and len(self.pointer) <= 16384 and (not self.pointer or self.pointer.startswith('/'))
                     and not re.search(r'~(?![01])', self.pointer) and '\x00' not in self.pointer)
        else:
            valid = False
        if not valid:
            raise ReferenceError('INVALID_SELECTOR')
