"""Only this plugin knows gateway/workspace/policy/SDK shapes.

No active-cluster lookup, automatic authentication refresh, credential creation,
image/default policy choice or service startup. Assembly injects an existing
authenticated SDK client and its same-authority generated stub explicitly.
"""
from dataclasses import dataclass
import posixpath
from collections.abc import Mapping

from google.protobuf.json_format import ParseDict
from openshell._proto import openshell_pb2 as pb
from ordessa_environments import EnvironmentRefused


@dataclass(frozen=True)
class OpenShellConfiguration:
    workspace: str
    file_root: str
    gateway_reference: str
    provider_id: str = 'openshell'
    file_helper: str | None = None
    timeout_seconds: float = 30.0
    # A reference only; resolver/SDK credentials stay in assembly memory.
    credential_reference: str | None = None

    def __post_init__(self):
        if not isinstance(self.workspace, str) or not self.workspace:
            raise EnvironmentRefused('OpenShell requires an explicit workspace')
        if (not isinstance(self.file_root, str) or not posixpath.isabs(self.file_root)
                or posixpath.normpath(self.file_root) != self.file_root or '\x00' in self.file_root):
            raise EnvironmentRefused('OpenShell file root must be a canonical absolute backend path')
        if not isinstance(self.gateway_reference,str) or not self.gateway_reference:
            raise EnvironmentRefused('OpenShell requires explicit gateway binding reference')
        if not self.provider_id or self.timeout_seconds <= 0:
            raise EnvironmentRefused('OpenShell provider ID and positive timeout required')
        if self.file_helper is not None and (not isinstance(self.file_helper, str) or not self.file_helper):
            raise EnvironmentRefused('file helper must be explicit executable or unavailable')


def create_spec(reference):
    if not isinstance(reference, Mapping):
        raise EnvironmentRefused('OpenShell create reference must be a mapping')
    if set(reference) != {'image', 'policy', 'main_command'}:
        raise EnvironmentRefused('create requires only explicit image, policy and independent main_command')
    image, command, policy = reference['image'], reference['main_command'], reference['policy']
    if not isinstance(image, str) or not image or not isinstance(policy, Mapping) or not policy:
        raise EnvironmentRefused('OpenShell image and non-empty backend policy required')
    if not isinstance(command, (list, tuple)) or not command or any(not isinstance(x, str) or not x for x in command):
        raise EnvironmentRefused('independent environment lifetime command required')
    # The gateway validates policy JSON with its own spellings; accept only the
    # values it admits so an unsupported policy is refused before any dispatch
    # instead of becoming an in-flight INVALID_ARGUMENT.
    landlock = policy.get('landlock')
    if landlock is not None:
        if not isinstance(landlock, Mapping):
            raise EnvironmentRefused('OpenShell landlock policy must be a mapping')
        compatibility = landlock.get('compatibility')
        if compatibility is not None and compatibility not in ('hard_requirement', 'best_effort'):
            raise EnvironmentRefused(
                'OpenShell landlock.compatibility must be hard_requirement or best_effort')
    filesystem = policy.get('filesystem')
    if filesystem is not None:
        if not isinstance(filesystem, Mapping):
            raise EnvironmentRefused('OpenShell filesystem policy must be a mapping')
        for key in ('read_only', 'read_write'):
            paths = filesystem.get(key)
            if paths is None:
                continue
            if (not isinstance(paths, (list, tuple))
                    or any(not isinstance(item, str) or not item.startswith('/') for item in paths)):
                raise EnvironmentRefused('OpenShell ' + key + ' must contain absolute backend paths')
    try:
        return ParseDict({'template': {'image': image}, 'policy': dict(policy),
            'command': list(command), 'tty': False}, pb.SandboxSpec(), ignore_unknown_fields=False)
    except Exception:
        raise EnvironmentRefused('unsupported OpenShell sandbox specification') from None
