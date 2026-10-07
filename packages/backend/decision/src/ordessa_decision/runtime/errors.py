"""Safe runtime errors never carry provider response or exception bodies."""
class RuntimeFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

class BudgetExhausted(RuntimeFailure):
    def __init__(self, dimension):
        self.dimension = dimension
        super().__init__('budget_exhausted')

class EvidenceUnknown(RuntimeFailure):
    """The reader is authoritative; no trusted terminal can be returned."""
    def __init__(self, run_id=None):
        self._run_id = run_id
        super().__init__('evidence_unknown')

    @property
    def run_id(self):
        """Safe opaque query key; never grants evidence read authority."""
        return self._run_id

class ExplicitCancellation(RuntimeFailure):
    def __init__(self):
        super().__init__('cancelled')
