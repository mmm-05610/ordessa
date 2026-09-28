"""Numeric caps for one definition library (spec FR01/FR10, gate G04).

Each bound is its own named constant so a refusal says which one tripped. No
value here may be raised by a definition payload, an import document or a
caller-supplied mapping: the caps are the domain's, not the content's.
"""
from __future__ import annotations

import re

MAX_DEFINITION_ID_CHARS = 128
MAX_SLUG_CHARS = 64
MAX_DISPLAY_NAME_CHARS = 128
MAX_DESCRIPTION_CHARS = 160        # legacy MAX_SUBAGENT_DESCRIPTION_CHARS parity
MAX_ROLE_BODY_BYTES = 32 * 1024
MAX_SOURCE_REF_CHARS = 512
MAX_PRINCIPAL_CHARS = 128
MAX_OPERATION_KEY_CHARS = 200

MAX_REF_ID_CHARS = 128
MAX_MODEL_REFS = 1
MAX_TOOL_REFS = 64
MAX_MCP_REFS = 64
MAX_SKILL_REFS = 64

MAX_ISOLATION_KEYS = 8
MAX_LIMIT_KEYS = 16
MAX_RETAINED_NATIVE_FIELDS = 32
MAX_RETAINED_NATIVE_BYTES = 8 * 1024

#: An enabled library is bounded as a whole: descriptions reach the harness
#: agent directory, so the aggregate is checked before anything is applied.
MAX_ENABLED_DEFINITIONS = 64
MAX_AGGREGATE_DESCRIPTION_BYTES = 8 * 1024
MAX_AGGREGATE_ROLE_BODY_BYTES = 4 * 1024 * 1024

#: One import source: a small directory of definition documents, not a disk.
MAX_IMPORT_FILES = 64
MAX_IMPORT_FILE_BYTES = MAX_ROLE_BODY_BYTES
MAX_IMPORT_TOTAL_BYTES = 256 * 1024
MAX_IMPORT_DEPTH = 4

_SLUG_RE = re.compile(r"\A[a-z0-9][a-z0-9._-]*\Z")
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
_GIT_PIN_RE = re.compile(r"\A[0-9a-f]{40}\Z")
