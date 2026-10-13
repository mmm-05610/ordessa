"""Brand-owned initial native model dialect; output contains private launch facts."""
from ordessa_execution_agents.harness.configuration.validation.initial_params import build_initial_model_params

def initial_model_params(payload, operation_id, *, credential=None, models=None):
    return build_initial_model_params(payload, operation_id,
        protocol='openai-chat', provider_id=None, api='openai-completions', catalogue=True, credential=credential, models=models)
