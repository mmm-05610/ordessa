"""ACP v1 request and response schema validation."""

from acp import schema

REQUESTS = {
    "initialize": schema.InitializeRequest,
    "session/new": schema.NewSessionRequest,
    "session/load": schema.LoadSessionRequest,
    "session/prompt": schema.PromptRequest,
    "session/set_config_option": schema.SetSessionConfigOptionSelectRequest,
}
RESPONSES = {
    "initialize": schema.InitializeResponse,
    "session/new": schema.NewSessionResponse,
    "session/load": schema.LoadSessionResponse,
    "session/prompt": schema.PromptResponse,
    "session/set_config_option": schema.SetSessionConfigOptionResponse,
}


def validate_request(method, params):
    model = REQUESTS.get(method)
    if model is not None:
        model.model_validate(params)


def validate_response(method, result):
    model = RESPONSES.get(method)
    if model is not None:
        model.model_validate(result)
    # The SDK schema salvages malformed optional config entries. Keep strict
    # validation for each advertised option while retaining unknown fields.
    if isinstance(result, dict):
        for option in result.get("configOptions", []):
            option_model = (
                schema.SessionConfigOptionBoolean
                if option.get("type") == "boolean"
                else schema.SessionConfigOptionSelect
            )
            option_model.model_validate(option)
