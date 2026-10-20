"""Start the long-lived HTTP Server; `ordessa` remains the separate registry CLI."""
from ordessa_server.entrypoints.http import (
    DEFAULT_PORT, PortAllocationFailed, HttpCompositionUnavailable,
    bind_loopback_socket, business_flags, parser, resolved_data_root,
    serving_origin, main,
)

if __name__ == '__main__':
    raise SystemExit(main())
