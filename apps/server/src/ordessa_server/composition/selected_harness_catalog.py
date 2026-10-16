"""First-edition public Pi declarations; other brands are not selected."""
from .harness_catalog import capture_harness_catalog
from ordessa_harness_pi.registration_declarations import registration_declarations as pi


def capture_selected_harness_catalog():
    capture = pi()
    return capture_harness_catalog((capture,), launch_declarations=(capture,))
