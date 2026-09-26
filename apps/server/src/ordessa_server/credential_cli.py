"""Compatibility alias — the implementation moved to
`ordessa_server_compat.credential_cli` (core-cleanup stage 3). The console
script `ordessa-server-credential` keeps pointing here; no second
implementation."""
from ordessa_server_compat.credential_cli import (  # noqa: F401
    main,
    parser,
)
