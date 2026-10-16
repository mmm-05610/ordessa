from ordessa_environments import ProviderDescriptor

DESCRIPTOR = ProviderDescriptor('openshell', '0.1.0', '0.1.3', {
    'resource-lifecycle': True, 'bidirectional-non-pty': True,
    'per-process-kill': False, 'process-reconnect': False,
    'use-isolation-boundary': False, 'files-require-helper-probe': True,
    'atomic-expected-id-mutation':False,
})
