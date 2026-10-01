"""Harness-owned Codex managed authentication, not an OAuth implementation.

The supplied command MUST come from trusted asset verification. The dedicated
account directory is distinct from instance configuration directories. Native
Codex alone reads the keyring and refreshes credentials. No token export,
credential copying, external-token login, or implicit browser login occurs.
"""
from collections.abc import Sequence
import json
import os
from pathlib import Path
import selectors
import stat
import subprocess
from threading import RLock
import time


class ManagedAccountUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('CODEX_MANAGED_ACCOUNT_UNAVAILABLE')


class CodexManagedAccount:
    def __init__(self, *, command: Sequence[str], account_directory: Path, timeout=20):
        if (isinstance(command, (str, bytes)) or not command
                or any(type(part) is not str or not part or '\0' in part for part in command)
                or not Path(command[0]).is_absolute()
                or type(timeout) not in (int, float) or not 0 < timeout <= 30):
            raise ManagedAccountUnavailable()
        self._command = tuple(command)
        self._directory = Path(account_directory)
        self._timeout = timeout
        self._lock = RLock()

    def _validate_directory(self):
        directory = self._directory
        info = directory.lstat()
        if (not directory.is_absolute() or directory.resolve() != directory
                or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise ManagedAccountUnavailable()

    def read(self, *, refresh=False):
        """Safe projection; refresh delegates to native account/read only.

        Serialized for this account owner to avoid concurrent managed refresh
        calls. No caller-controlled account, token, model or RPC method exists.
        """
        with self._lock:
            return self._read(refresh=refresh)

    def _read(self, *, refresh):
        process = None
        try:
            if type(refresh) is not bool:
                raise ManagedAccountUnavailable()
            with self._lock:
                self._validate_directory()
                environment = dict(os.environ)
                for key in ('CODEX_API_KEY', 'OPENAI_API_KEY', 'CODEX_ACCESS_TOKEN', 'CODEX_AUTH_TOKEN'):
                    environment.pop(key, None)
                environment['CODEX_HOME'] = str(self._directory)
                process = subprocess.Popen((*self._command, '-c', 'cli_auth_credentials_store="keyring"',
                    'app-server'), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, env=environment)
                deadline = time.monotonic() + self._timeout
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    buffer = bytearray()
                    consumed = 0

                    def send(value):
                        process.stdin.write(json.dumps(value, separators=(',', ':')).encode() + b'\n')
                        process.stdin.flush()

                    def reply(request_id):
                        nonlocal consumed
                        while True:
                            if b'\n' not in buffer:
                                remaining = deadline - time.monotonic()
                                if remaining <= 0 or not selector.select(remaining):
                                    raise ManagedAccountUnavailable()
                                chunk = os.read(process.stdout.fileno(), 65536)
                                consumed += len(chunk)
                                if not chunk or consumed > 65536:
                                    raise ManagedAccountUnavailable()
                                buffer.extend(chunk)
                                continue
                            line, _, rest = buffer.partition(b'\n')
                            buffer[:] = rest
                            message = json.loads(line)
                            if not isinstance(message, dict):
                                raise ManagedAccountUnavailable()
                            if 'id' not in message:
                                continue  # Native notifications contain no response ID.
                            if message.get('id') != request_id or 'error' in message or 'method' in message:
                                raise ManagedAccountUnavailable()
                            result = message.get('result')
                            if not isinstance(result, dict):
                                raise ManagedAccountUnavailable()
                            return result

                    send({'id': 1, 'method': 'initialize', 'params': {
                        'clientInfo': {'name': 'ordessa-managed-account', 'version': '1'},
                        'capabilities': {'experimentalApi': False}}})
                    reply(1)
                    send({'method': 'initialized', 'params': {}})
                    send({'id': 2, 'method': 'account/read', 'params': {'refreshToken': refresh}})
                    result = reply(2)
                    account = result.get('account')
                    if ('account' not in result or type(result.get('requiresOpenaiAuth')) is not bool
                            or account is not None and (not isinstance(account, dict)
                                or not isinstance(account.get('type'), str))):
                        raise ManagedAccountUnavailable()
                    return {'authenticated': account is not None and account['type'] == 'chatgpt',
                            'method': 'chatgpt-managed'}
        except Exception:
            # Neither native output nor an OS/provider error enters diagnostics.
            raise ManagedAccountUnavailable() from None
        finally:
            if process is not None:
                try:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=3)
                finally:
                    try:
                        process.stdin.close()
                        process.stdout.close()
                    except Exception:
                        raise ManagedAccountUnavailable() from None
