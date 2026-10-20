"""Original shared loopback Host/Origin rule; no domain or auth state."""
def _loopback_authority(value: str) -> bool:
    host = value.rsplit(":", 1)[0].lower() if not value.startswith("[") else value.split("]", 1)[0] + "]"
    return host in {"127.0.0.1", "localhost", "[::1]"}
