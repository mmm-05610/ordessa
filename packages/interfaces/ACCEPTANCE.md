# Generic interface host acceptance

Current convergence checkout: `packages-convergence-20261019`. All processes use
its `.venv-convergence/bin/python`; no nightly interpreter fallback is allowed.

```text
apps/server entrypoint → generic channel/host → capability handler → owner service/provider
```

The generic host imports no concrete owner. Application composition supplies the
owner bindings. The old typed environment host and temporary capability_host/
cli_generic paths have been physically removed, without forwarding aliases.

Run from this checkout:

```bash
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 .venv-convergence/bin/python -m pytest packages/interfaces/tests packages/interfaces/contracts/tests -q -p no:cacheprovider
.venv-convergence/bin/python tests/integration/packages_convergence/cli_acceptance.py --entrypoint installed
```

Actual controlled results: **90 tests passed**, installed real CLI **14/14 passed**.
The latter covers providers/create/list/inspect, raw echo, piped stdin, nonzero child
exit, command refusal before acquisition, file write/read, lifecycle refusals,
timeout cleanup, zero active Uses after completion, and user file retention.

CLI behavioral tests retain all 23 original scenario identities (one boundary test
renamed for application assembly). [The assertion mapping](../../docs/implementation/packages-convergence-20261019/TYPED-HOST-RETIREMENT.md)
records F1 envelope/error vocabulary and human display changes. No assertion was
removed to disguise a failure. Stronger boundary tests scan every host module.

Script declaration: `apps/server/pyproject.toml` owns `ordessa`; interfaces declares
none. Offline local editable installation uses `--no-index --no-deps
--no-build-isolation`; install interfaces before server because the previous
interface distribution's script removal can otherwise remove the shared name.
No external dependency approval is inferred from this local metadata rebuild.

Evidence: [installed CLI receipt](../../docs/implementation/packages-convergence-20261019/evidence/new-cli-installed.json).
Scope excludes complete Agent Manager reliability, engineering/Units retirement,
remote OpenShell authentication, real model/JEV calls and full server dependencies.
Neutral existing wire Scope/grant schemas remain original server contracts;
they are not silently mapped onto new capability authorization.
