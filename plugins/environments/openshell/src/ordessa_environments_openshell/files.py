"""Bounded file operations execute inside the sandbox using an explicit helper.

The SDK has no FileArea port. The configured image must supply Python 3; a real
helper probe precedes capability advertisement. No local filesystem bypass or
implicit host dependency. OpenShell policy remains the security boundary.
"""
import json
import posixpath
import uuid

from openshell._proto import datamodel_pb2, openshell_pb2 as pb
from ordessa_environments import EnvironmentRefused, EnvironmentOperationUnknown

_LIMIT = 1024 * 1024
_SCRIPT = '''import sys,json,pathlib,os
v=json.loads(sys.argv[1]); root=pathlib.Path(v['root']); target=root/v.get('relative','.')
physical_root=root.resolve(); physical_target=target.resolve()
if not physical_target.is_relative_to(physical_root): raise ValueError('outside area')
op=v['op']
if op=='probe':
 if not root.is_dir(): raise ValueError('root absent')
 result=True
elif op=='ensure': target.mkdir(parents=True,exist_ok=True); result=str(target)
elif op=='exists': result=target.exists()
elif op=='read':
 with target.open('rb') as f: content=f.read(1048577)
 if len(content)>1048576: raise ValueError('too large')
 result=content.decode('utf-8')
elif op=='write': target.write_text(v['content'],encoding='utf-8'); result=None
elif op=='list':
 result=[]
 for directory,dirs,files in os.walk(root,followlinks=False):
  for name in sorted(files):
   result.append(str((pathlib.Path(directory)/name).relative_to(root)))
   if len(result)>10000: raise ValueError('too many entries')
 result.sort()
else: raise ValueError('unsupported')
sys.stdout.write(json.dumps(result,ensure_ascii=False))
'''


class OpenShellFileArea:
    def __init__(self, rpc, *, configuration, sandbox_name, validate=None):
        self._rpc, self._configuration, self._name = rpc, configuration, sandbox_name
        self._validate = validate

    def root(self):
        return self._configuration.file_root

    def path(self, relative):
        if not isinstance(relative, str) or not relative or '\x00' in relative or posixpath.isabs(relative):
            raise EnvironmentRefused('backend file path must be nonempty relative path')
        root = self.root()
        target = posixpath.normpath(posixpath.join(root, relative))
        if target != root and not target.startswith(root.rstrip('/') + '/'):
            raise EnvironmentRefused('backend file path escapes configured root')
        return target

    def _call(self, operation, relative='.', content=None):
        if self._validate is not None:
            self._validate()
        self.path(relative)
        helper = self._configuration.file_helper
        if helper is None:
            raise EnvironmentRefused('OpenShell file helper is not configured')
        args = {'op':operation,'root':self.root(),'relative':relative}
        if content is not None:
            if not isinstance(content,str) or len(content.encode('utf-8')) > _LIMIT:
                raise EnvironmentRefused('file content exceeds bounded UTF-8 limit')
            args['content'] = content
        request_id = str(uuid.uuid4())
        request = pb.ExecSandboxRequest(
            workspace_scope=datamodel_pb2.WorkspaceSelector(workspace=self._configuration.workspace),
            sandbox=self._name, command=[helper,'-c',_SCRIPT,json.dumps(args)],
            workdir='/', tty=False, no_login_shell=True, request_id=request_id)
        data, code = bytearray(), None
        try:
            for event in self._rpc.ExecSandbox(request, timeout=self._configuration.timeout_seconds):
                kind = event.WhichOneof('payload')
                if kind == 'stdout':
                    data.extend(event.stdout.data)
                    if len(data) > 8 * _LIMIT:
                        raise EnvironmentOperationUnknown('file reply exceeded bounded transport; outcome unknown', identity=request_id)
                elif kind == 'exit':
                    code = int(event.exit.exit_code)
        except EnvironmentOperationUnknown:
            raise
        except Exception:
            raise EnvironmentOperationUnknown('file RPC has no confirmed result',identity=request_id) from None
        if code is None:
            raise EnvironmentOperationUnknown('file helper ended without exit receipt',identity=request_id)
        if code != 0:
            raise EnvironmentRefused('backend file helper failed or policy refused access')
        try:
            return json.loads(data.decode('utf-8'))
        except (ValueError, UnicodeError):
            raise EnvironmentOperationUnknown('file helper result is unverifiable',identity=request_id) from None

    def probe(self):
        if self._call('probe') is not True:
            raise EnvironmentRefused('backend file helper probe failed')

    def ensure(self, relative):
        result = self._call('ensure',relative)
        if result != self.path(relative):
            raise EnvironmentRefused('backend helper returned unexpected path')
        return result

    def exists(self, relative):
        return self._call('exists',relative)

    def read_text(self, relative):
        result = self._call('read',relative)
        if not isinstance(result, str) or len(result.encode('utf-8')) > _LIMIT:
            raise EnvironmentRefused('backend helper returned invalid text')
        return result

    def write_text(self, relative, content):
        self._call('write',relative,content)

    def list(self):
        result = self._call('list')
        if not isinstance(result,list) or any(not isinstance(x,str) for x in result):
            raise EnvironmentRefused('backend helper returned invalid listing')
        for entry in result:
            self.path(entry)
        return tuple(result)
