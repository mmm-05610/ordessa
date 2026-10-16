"""Value validation only; no IO implementation or event-loop dependency."""
import math
from .errors import EnvironmentRefused


def validate_timeout(value):
    if value is None:
        return None
    if type(value) not in (int,float) or not math.isfinite(value) or value < 0:
        raise EnvironmentRefused('timeout must be finite nonnegative seconds or None')
    return float(value)


def validate_read_size(value):
    if type(value) is not int or value <= 0:
        raise EnvironmentRefused('max_bytes must be a positive integer')
    return value
