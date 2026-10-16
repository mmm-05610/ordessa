"""Optional captured build evidence. Parsed mappings are defensive views."""
from dataclasses import dataclass
from .sources import ParsedContent

@dataclass(frozen=True)
class VerificationInputs:
    bundle_lock: ParsedContent | None = None
    compiled_golden: ParsedContent | None = None
    def __post_init__(self):
        if any(v is not None and type(v) is not ParsedContent for v in (self.bundle_lock, self.compiled_golden)):
            raise TypeError("verification evidence requires captured immutable parsed views")
    @property
    def lock(self): return self.bundle_lock.value if self.bundle_lock else None
    @property
    def golden(self): return self.compiled_golden.value if self.compiled_golden else None
