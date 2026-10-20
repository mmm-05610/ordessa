"""Host selection of independent brand-owned pure native model policies."""
from ordessa_harness_pi import model_policy as pi_policy
from ordessa_harness_codex import model_policy as codex_policy
from ordessa_harness_claude_code import model_policy as claude_policy


def capture_selected_native_model_ports():
    ports = (pi_policy, codex_policy, claude_policy)
    ids = tuple(port.harness_id for port in ports)
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate selected native model provider')
    return ports
