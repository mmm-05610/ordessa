"""Public capture port for this brand's original registry/launch declarations.

Import reads nothing. Calling the port reads only this brand's packaged resources.
The caller selects products and order; declarations grant no runtime authority.
"""
from importlib.resources import files

from ordessa_execution_agents.harness.providers.declarations import RegistrationDeclarations


def registration_declarations() -> RegistrationDeclarations:
    """Capture this independent brand's two original byte fragments."""
    resources = files(__package__).joinpath("_registration_declarations")
    return RegistrationDeclarations(
        registry_toml=resources.joinpath("harness.toml").read_bytes(),
        launch_json=resources.joinpath("launch.json").read_bytes(),
    )
