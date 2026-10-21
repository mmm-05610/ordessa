"""Explicit selected installation ports; caller supplies the same captured catalog."""
from functools import partial
from ..harness_catalog import CapturedHarnessCatalog
from ordessa_agents.harness.providers.declarations.capability_claims import capability_claims

def captured_installation_recipes(catalog: CapturedHarnessCatalog, *, build_files_for):
    if type(catalog) is not CapturedHarnessCatalog:
        raise TypeError("explicit CapturedHarnessCatalog required")
    if not callable(build_files_for):
        raise TypeError("explicit build-files callback required")
    from ordessa_harness_codex.installation_declarations import installation_declaration as p0, installation_owner_id as i0, installation_requires_npm as n0
    from ordessa_harness_claude_code.installation_declarations import installation_declaration as p1, installation_owner_id as i1, installation_requires_npm as n1
    from ordessa_harness_opencode.installation_declarations import installation_declaration as p2, installation_owner_id as i2, installation_requires_npm as n2
    from ordessa_harness_hermes.installation_declarations import installation_declaration as p3, installation_owner_id as i3, installation_requires_npm as n3
    from ordessa_harness_dsh.installation_declarations import installation_declaration as p4, installation_owner_id as i4, installation_requires_npm as n4
    from ordessa_harness_kilo.installation_declarations import installation_declaration as p5, installation_owner_id as i5, installation_requires_npm as n5
    from ordessa_harness_pi.installation_declarations import installation_declaration as p6, installation_owner_id as i6, installation_requires_npm as n6
    capabilities_for = partial(capability_claims, catalog.registry)
    return tuple(port(capabilities_for=capabilities_for,
                      build_files=build_files_for(identity(), requires_npm=npm()))
                 for port, identity, npm in ((p0,i0,n0),(p1,i1,n1),(p2,i2,n2),
                                            (p3,i3,n3),(p4,i4,n4),(p5,i5,n5),(p6,i6,n6)))
