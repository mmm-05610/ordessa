"""Original C09 receipt timestamp format shared by its application use cases."""
from datetime import datetime, timezone

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
