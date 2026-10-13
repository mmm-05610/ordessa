"""Bounded selection and digest checks on supplied bytes; no fetching or trust verdict."""
import hashlib
import re

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.domain.common.models.selection import (ContentSelector, MAX_CONTENT_BYTES)
from ..models.values import Digest
from ..outcomes.diagnostics import ReferenceError

def select_bytes(raw, selector):
    if type(raw) is not bytes or len(raw) > MAX_CONTENT_BYTES or type(selector) is not ContentSelector:
        raise ReferenceError('INVALID_SELECTOR')
    if selector.kind == 'whole_capture':
        return raw
    if selector.kind == 'byte_range':
        if selector.end > len(raw):
            raise ReferenceError('SELECTOR_OUT_OF_RANGE')
        return raw[selector.start:selector.end]
    try:
        value = decode_json(raw)
        for token in selector.pointer.split('/')[1:] if selector.pointer else ():
            token = token.replace('~1', '/').replace('~0', '~')
            if type(value) is list:
                if not re.fullmatch(r'0|[1-9][0-9]*', token) or len(token) > 10:
                    raise ReferenceError('INVALID_SELECTOR')
                value = value[int(token)]
            elif type(value) is dict:
                value = value[token]
            else:
                raise ReferenceError('SELECTOR_OUT_OF_RANGE')
        return canonical_bytes(value)
    except (ValueError, TypeError, KeyError, IndexError, RecursionError, OverflowError):
        raise ReferenceError('SELECTOR_OUT_OF_RANGE') from None

def verify_selection(raw, selector, expected):
    selected = select_bytes(raw, selector)
    if type(expected) is not Digest or hashlib.sha256(selected).hexdigest() != expected.hex:
        raise ReferenceError('STATEMENT_DIGEST_MISMATCH')
    return selected

class SelectorChecks:
    """Bound pure selection/hash work; cache only within one resolution."""
    def __init__(self):
        self.work = 0
        self.inputs = {}
        self.digests = {}
        self.selected = {}

    def check(self, raw, selector, expected=None):
        key = (id(raw), selector)
        if key not in self.digests:
            self.work += len(raw)
            if self.work > 64 * 1024 * 1024:
                raise ReferenceError('SELECTOR_WORK_LIMIT')
            selected = select_bytes(raw, selector)
            self.work += len(selected)
            if self.work > 64 * 1024 * 1024:
                raise ReferenceError('SELECTOR_WORK_LIMIT')
            self.inputs[id(raw)] = raw  # prevent an id being reused after GC
            self.digests[key] = hashlib.sha256(selected).hexdigest()
            self.selected[key] = selected
        if expected is not None and (type(expected) is not Digest or self.digests[key] != expected.hex):
            raise ReferenceError('STATEMENT_DIGEST_MISMATCH')
        return self.selected[key]
