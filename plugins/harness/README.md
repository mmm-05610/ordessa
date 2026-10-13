# Harness provider leaves

`plugins/harness/` contains 15 independently packaged brand providers. There is
no current aggregate `ordessa-harness` distribution or single multi-brand
provider package. Each leaf keeps its own distribution identity and brand
implementation; the Server product selects providers explicitly.

Current leaf distributions (from each leaf's `pyproject.toml`):

| Source leaf | Distribution |
| --- | --- |
| `claude-code` | `ordessa-harness-claude-code` |
| `codex` | `ordessa-harness-codex` |
| `copilot` | `ordessa-harness-copilot` |
| `dsh` | `ordessa-harness-dsh` |
| `gemini_cli` | `ordessa-harness-gemini-cli` |
| `goose` | `ordessa-harness-goose` |
| `grok-build` | `ordessa-harness-grok-build` |
| `hermes` | `ordessa-harness-hermes` |
| `kilo` | `ordessa-harness-kilo` |
| `kimi` | `ordessa-harness-kimi` |
| `opencode` | `ordessa-harness-opencode` |
| `pi` | `ordessa-harness-pi` |
| `qoder` | `ordessa-harness-qoder` |
| `qwen` | `ordessa-harness-qwen` |
| `vibe` | `ordessa-harness-vibe` |

The public host-independent execution and Harness contracts are owned by
`packages/interfaces/execution/c1-api` (`ordessa_execution_api.harness`).
Selected brand declarations are captured by
`apps/server/src/ordessa_server/composition/selected_harness_catalog.py`; the
Server product composes selected providers from
`apps/server/deployment/default-product/src/ordessa_server_product/composition.py`. A brand leaf is
not itself the aggregate registry or Server host.

Some leaves publish `registration_declarations` resources consumed by the
selected-catalog path; other brand distributions retain their own declared
capability and registration surface. Do not infer that every leaf is selected
by the default product or that every adapter is live-tested.

## Historical material

The complete previous README is preserved in the [2026-09-24 aggregate README archive](../../docs/archive/harness-aggregate-readme-20260924.md). It records the former consolidated `agent-box-harness` package, aliases, sidecar, checkout/build commands and Web workspace. That archived text is historical evidence and **must not be executed or used as current install/build/registration instructions**. The active source, distribution, contract and product-selection owners are described on this page. Historical extension IDs and wire formats are not changed by this source-owner clarification.


## Brand-owned deployment resources

Each Harness leaf owns its native deployment templates and any offline gate
resources under `src/ordessa_harness_<brand>/deployment/`. The leaf package
includes these files explicitly as package data, so production template reads
work from both the source checkout and an installed wheel. Hermes also reads its
bootstrap and `sitecustomize.py` overlay from its own package resource directory
when building the Hermes artifact.

The `projectionFiles[].source` and Hermes artifact-manifest `source` values such
as `deploy/pi/models.json` and `deploy/hermes/bootstrap.py` are retained historical
provenance identifiers. They do not name the current filesystem path; the owning
brand package resolves the resource bytes. Offline loopback/egress guards remain
gate-only assets and are not added to production deployment projections.
