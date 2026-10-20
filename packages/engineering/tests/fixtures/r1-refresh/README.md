The r101 fixtures are the original R1 review inputs. The r102 fixtures are the
actual post-transition artifacts from commit `dd47fd7323`, extracted at their
original Engineering registry paths. The r102 registry SHA256 is
`41fdb6b777a0d90ff0b988c85589dfcb3470654ecf394bf6add074158656ad30`.

The historical tool at
`docs/implementation/packages-convergence-20261012/engineering/refresh_owned_registry.py`
is retained byte for byte from the preserved nightly source. Its original
101-to-102 locks, allowlists and dependency/content guards remain unchanged.
`test_owned_registry_refresh.py` replays that tool against these historical
inputs and outputs; it does not reinterpret today's source as the approved R1
hashes. Current registry closure and the explicit 126-to-127 transition are
verified by `test_current_registry_closure.py` and
`test_current_registry_refresh.py` respectively.
