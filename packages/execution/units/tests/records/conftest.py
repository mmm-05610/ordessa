"""Reuse the existing controlled shared fixture without a product import shim.

Cross-package fixture consumers still point at Agents' support root. Moving
that shared path requires the coordinating owner to update those consumers.
"""
from pathlib import Path
import sys

SUPPORT = Path(__file__).resolve().parents[3] / 'agents/tests/support'
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
