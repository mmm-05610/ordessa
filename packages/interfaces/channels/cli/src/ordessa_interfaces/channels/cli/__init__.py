"""Generic ``ordessa`` call channel: one envelope, declarative CLI metadata.

Grammar::

    ordessa [global options] list|describe ...
    ordessa [global options] call <operation-id> --input <file|-> ...
    ordessa [global options] <command path...> <operation> [declarative args...] --
        [operands...]

``command`` metadata may name a multi-level path (``agents profiles``); the
longest exact command path wins and a repeated path is refused before
publication. Global options are ``--json``, ``--request-id``, ``--timeout``,
``--save-result`` and ``--help``; the same option set is reused by entity
commands and by the generic ``call`` form.

The channel never imports an owner: it receives a built host and an
``authenticate`` callable from the application assembly, plus a read-only
metadata sequence so ``--help``/``list``/``describe`` need no host, database or
brand runtime.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Callable

from ordessa_interfaces_contracts import ContractError, exit_code

from ...system_access.operations import RequestContext
from ...system_access.projections import project

MAX_INPUT_BYTES = 1 << 20
MAX_TIMEOUT_SECONDS = 3600
DEFAULT_DEADLINE_SECONDS = 30
_JSON_POINTER = re.compile(r'^(?:/(?:[^~/]|~[01])*)+$')


def _refused_envelope(command: str, request_id: str, code: str, message: str) -> dict:
    return {'apiVersion': 'agent-tools/1', 'requestId': request_id, 'command': command,
            'status': 'refused', 'data': None,
            'error': {'code': code, 'message': message, 'retryable': False},
            'operationRef': None, 'evidenceRefs': []}


def _command_path(value: str) -> tuple[str, ...]:
    tokens = tuple(value.split())
    if not tokens or any(not token for token in tokens):
        raise ContractError('INVALID_INPUT', f'CLI command metadata is invalid: {value!r}')
    return tokens


def _cli_index(descriptors) -> dict[tuple[str, ...], str]:
    """Map ``(command..., operation)`` to the owning operation id."""
    index: dict[tuple[str, ...], str] = {}
    for descriptor in descriptors:
        cli = descriptor.cli
        if cli is None:
            continue
        path = _command_path(cli['command'])
        key = path + (cli['operation'],)
        if key in index:
            raise ContractError('INVALID_INPUT', f'CLI metadata repeats: {" ".join(key)}')
        index[key] = descriptor.id
    return index


def _match(argv: Sequence[str], index) -> tuple[str, str, list[str]] | None:
    """Longest exact command path then its operation; never a partial guess."""
    for size in range(min(len(argv) - 1, 4), 0, -1):
        path = tuple(argv[:size])
        key = path + (argv[size],)
        if key in index:
            return ' '.join(path), index[key], list(argv[size + 1:])
    return None


def _split(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    if '--' in argv:
        index = list(argv).index('--')
        return list(argv[:index]), list(argv[index + 1:])
    return list(argv), []


def _select_field(document: Any, pointer: str) -> Any:
    cursor = document
    for segment in pointer.split('/')[1:]:
        token = segment.replace('~1', '/').replace('~0', '~')
        if isinstance(cursor, Mapping):
            if token not in cursor:
                raise ContractError('INVALID_INPUT', 'field reference does not exist')
            cursor = cursor[token]
        elif isinstance(cursor, list):
            if not token.isdigit() or int(token) >= len(cursor):
                raise ContractError('INVALID_INPUT', 'field reference does not exist')
            cursor = cursor[int(token)]
        else:
            raise ContractError('INVALID_INPUT', 'field reference has no container')
    return cursor


def _read_json_file(value: str, *, stdin) -> Any:
    pointer = None
    if value == '-':
        raw = stdin.read()
    else:
        if '#' in value:
            path, pointer = value.rsplit('#', 1)
            if pointer and not _JSON_POINTER.match(pointer):
                raise ContractError('INVALID_INPUT', 'field reference pointer is invalid')
        else:
            path = value
        try:
            with open(path, 'rb') as stream:
                raw = stream.read(MAX_INPUT_BYTES + 1)
        except OSError:
            raise ContractError('INVALID_INPUT', 'input file cannot be read') from None
        if len(raw) > MAX_INPUT_BYTES:
            raise ContractError('INVALID_INPUT', 'input file exceeds the bounded size')
    try:
        document = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ContractError('INVALID_INPUT', 'json-file argument is not JSON') from None
    if pointer:
        return _select_field(document, pointer)
    return document


def _convert(value: str, arg_type: str, *, stdin) -> Any:
    if arg_type == 'string':
        return value
    if arg_type == 'integer':
        try:
            return int(value)
        except ValueError:
            raise ContractError('INVALID_INPUT', f'argument is not an integer: {arg_type}') from None
    if arg_type == 'number':
        try:
            return float(value)
        except ValueError:
            raise ContractError('INVALID_INPUT', 'argument is not a number') from None
    if arg_type == 'boolean':
        return value.lower() in ('1', 'true', 'yes', 'on')
    if arg_type == 'json-file':
        return _read_json_file(value, stdin=stdin)
    raise ContractError('INVALID_INPUT', f'unsupported argument type: {arg_type}')


def _set_path(target: dict, dotted: str, value: Any) -> None:
    parts = dotted.split('.')
    cursor = target
    for part in parts[:-1]:
        nested = cursor.get(part)
        if nested is None:
            nested = cursor[part] = {}
        if not isinstance(nested, dict):
            raise ContractError('INVALID_INPUT', 'jsonPath collides with another value')
        cursor = nested
    cursor[parts[-1]] = value


def _build_request(descriptor, tokens: list[str], operands=(), *, stdin) -> dict:
    """Map declarative CLI metadata onto the operation request.

    Flags consume the token that follows them (``nargs`` may widen that to
    ``?``/``*``/``+``/``REMAINDER``); a ``boolean`` flag without ``nargs`` is a
    switch. Arguments without flags are positional and are filled in
    declaration order from the remaining tokens and from the operands after
    ``--``. ``required`` falls back to the operation schema so an owner must
    not repeat it in CLI metadata.
    """
    request: dict[str, Any] = {}
    cli = descriptor.cli or {}
    args = cli.get('args', ())
    flags: dict[str, dict] = {}
    for spec in args:
        for flag in spec.get('flags') or ():
            flags[flag] = spec
    schema_required = set((descriptor.input_schema or {}).get('required') or ())
    values: dict[str, Any] = {}
    positional: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        spec = flags.get(token)
        if spec is None:
            positional.append(token)
            index += 1
            continue
        name, nargs = spec['name'], spec.get('nargs')
        index += 1
        if spec['type'] == 'boolean' and nargs is None:
            values[name] = True
        elif nargs in ('*', '+', 'REMAINDER'):
            collected = []
            while index < len(tokens) and tokens[index] not in flags:
                collected.append(tokens[index])
                index += 1
            if not collected and operands:
                collected = list(operands)
                operands = []
            if nargs != '*' and not collected:
                raise ContractError('INVALID_INPUT', f'argument needs at least one value: {name}')
            values[name] = [_convert(value, spec['type'], stdin=stdin) for value in collected]
        elif nargs == '?':
            if index < len(tokens) and tokens[index] not in flags:
                values[name] = _convert(tokens[index], spec['type'], stdin=stdin)
                index += 1
        else:
            if index >= len(tokens) or tokens[index] in flags:
                raise ContractError('INVALID_INPUT', f'missing value for argument: {name}')
            values[name] = _convert(tokens[index], spec['type'], stdin=stdin)
            index += 1
    positional.extend(operands)
    for spec in args:
        name, nargs = spec['name'], spec.get('nargs')
        destination = spec.get('jsonPath', name)
        if name in values:
            _set_path(request, destination, values[name])
            continue
        required = name in schema_required or spec.get('required') is True
        if spec.get('flags'):
            if 'default' in spec:
                _set_path(request, destination, spec['default'])
            elif required:
                raise ContractError('INVALID_INPUT', f'missing required argument: {name}')
            continue
        if nargs in ('*', '+', 'REMAINDER'):
            if nargs != '*' and not positional:
                raise ContractError('INVALID_INPUT', f'argument needs at least one value: {name}')
            _set_path(request, destination,
                      [_convert(value, spec['type'], stdin=stdin) for value in positional])
            positional = []
            continue
        if positional:
            _set_path(request, destination, _convert(positional.pop(0), spec['type'], stdin=stdin))
        elif 'default' in spec:
            _set_path(request, destination, spec['default'])
        elif required:
            raise ContractError('INVALID_INPUT', f'missing required argument: {name}')
    if positional:
        raise ContractError('INVALID_INPUT', 'unexpected arguments: ' + ' '.join(positional))
    return request


def _process_render(descriptor) -> bool:
    cli = descriptor.cli or {}
    render = cli.get('render') or {}
    return render.get('kind') == 'process'


def _attach_stdin(request: dict, descriptor, stdin) -> dict:
    """Forward piped stdin to a declared ``stdin`` request property."""
    properties = (descriptor.input_schema or {}).get('properties') or {}
    if 'stdin' not in properties or 'stdin' in request:
        return request
    probe = getattr(stdin, 'isatty', None)
    try:
        if callable(probe) and probe():
            return request
    except (OSError, ValueError):
        pass
    try:
        raw = stdin.read()
    except (OSError, ValueError):
        raise ContractError('INVALID_INPUT', 'stdin cannot be read') from None
    if not raw:
        return request
    try:
        text = raw.decode('utf-8') if isinstance(raw, (bytes, bytearray)) else str(raw)
    except UnicodeDecodeError:
        raise ContractError('INVALID_INPUT', 'stdin is not valid UTF-8') from None
    limit = (properties.get('stdin') or {}).get('maxLength')
    if type(limit) is int and len(text) > limit:
        raise ContractError('INVALID_INPUT', 'stdin exceeds the declared limit')
    return {**request, 'stdin': text}


def _print(stdout, *, as_json: bool, envelope: dict, descriptor=None, data=None,
           stderr=None, request_id: str | None = None) -> None:
    if as_json:
        stdout.write(json.dumps(envelope, ensure_ascii=False) + '\n')
        return
    error = envelope['error']
    if error is not None:
        (stderr or stdout).write(f"ordessa: {error['message']}\n")
        return
    if request_id:
        stdout.write(f'requestId: {request_id}\n')
    if descriptor is not None and data is not None:
        try:
            shown = project(descriptor, data)
        except ContractError:
            shown = data
        stdout.write(json.dumps(shown, ensure_ascii=False, sort_keys=True) + '\n')
        return
    stdout.write(envelope['status'] + '\n')


def _prepare_save_result(path: str) -> str:
    if type(path) is not str or not path:
        raise ContractError('INVALID_INPUT', '--save-result needs a path')
    target = os.path.abspath(path)
    if os.path.lexists(target):
        raise ContractError('CONFLICT', '--save-result target already exists')
    parent = os.path.dirname(target) or '.'
    if not os.path.isdir(parent):
        raise ContractError('INVALID_INPUT', '--save-result directory does not exist')
    if not os.access(parent, os.W_OK | os.X_OK):
        raise ContractError('INVALID_INPUT', '--save-result directory is not writable')
    return target


def _save_envelope(target: str, envelope: dict) -> None:
    """Create the result file exactly once, private and atomic; never overwrite."""
    body = (json.dumps(envelope, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')
    directory = os.path.dirname(target) or '.'
    fd, temporary = tempfile.mkstemp(prefix='.ordessa-result-', dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


class _Globals:
    __slots__ = ('json', 'request_id', 'timeout', 'save_result', 'help', 'argv')

    def __init__(self):
        self.json = False
        self.request_id = None
        self.timeout = None
        self.save_result = None
        self.help = False
        self.argv: list[str] = []


def _parse_globals(argv: Sequence[str]) -> _Globals:
    """Extract the shared global options; ``--`` only separates operands.

    ``--json`` and the other global options keep their established meaning even
    when they appear after ``--`` (the original channel contract); command
    tokens are never evaluated by a shell and operands stay ordered.
    """
    options = _Globals()
    tokens = list(argv)
    result = []
    index = 0
    seen_command = False
    while index < len(tokens):
        token = tokens[index]
        if token not in ('--json', '--help', '-h', '--request-id', '--timeout',
                         '--save-result', '--') and not token.startswith('--'):
            seen_command = True
        if token == '--timeout' and seen_command:
            # A command's own metadata may own ``--timeout`` (environments exec).
            # Keep the pair here; dispatch drops it only when no such argument
            # exists, in which case it is the bounded global deadline.
            result.append(token)
            index += 1
            continue
        if token == '--json':
            options.json = True
            index += 1
            continue
        if token in ('--help', '-h'):
            options.help = True
            index += 1
            continue
        if token in ('--request-id', '--timeout', '--save-result'):
            if index + 1 >= len(tokens):
                raise ContractError('INVALID_INPUT', f'{token} needs a value')
            value = tokens[index + 1]
            if token == '--request-id':
                if (type(value) is not str or not value or len(value) > 512
                        or any(ord(c) < 32 for c in value)):
                    raise ContractError('INVALID_INPUT', '--request-id must be a bounded stable id')
                options.request_id = value
            elif token == '--timeout':
                try:
                    seconds = float(value)
                except ValueError:
                    raise ContractError('INVALID_INPUT', '--timeout must be a number of seconds') from None
                if not 0 < seconds <= MAX_TIMEOUT_SECONDS:
                    raise ContractError('INVALID_INPUT', '--timeout is out of the bounded range')
                options.timeout = seconds
            else:
                options.save_result = value
            index += 2
            continue
        result.append(token)
        index += 1
    options.argv = result
    return options


def _strip_timeout(tokens, options):
    """Consume an unconsumed trailing ``--timeout`` pair as the global bound."""
    result = []
    index = 0
    while index < len(tokens):
        if tokens[index] == '--timeout':
            if index + 1 >= len(tokens):
                raise ContractError('INVALID_INPUT', '--timeout needs a value')
            try:
                seconds = float(tokens[index + 1])
            except ValueError:
                raise ContractError('INVALID_INPUT', '--timeout must be a number of seconds') from None
            if not 0 < seconds <= MAX_TIMEOUT_SECONDS:
                raise ContractError('INVALID_INPUT', '--timeout is out of the bounded range')
            options.timeout = seconds
            index += 2
            continue
        result.append(tokens[index])
        index += 1
    return result


def _descriptor_takes_timeout(descriptor):
    for spec in ((descriptor.cli or {}).get('args') or ()):
        if spec.get('name') == 'timeout' or '--timeout' in (spec.get('flags') or ()):
            return True
    return False


def _metadata_descriptors(metadata, host):
    if metadata:
        return list(metadata)
    if host is not None:
        return [registered.descriptor for registered in host.registry.operations.values()]
    return []


def _descriptor_for(descriptors, operation_id):
    for descriptor in descriptors:
        if descriptor.id == operation_id:
            return descriptor
    raise ContractError('CAPABILITY_UNSUPPORTED', 'operation metadata is unavailable')


def _arg_usage(spec) -> str:
    flags = spec.get('flags') or ()
    label = spec['name']
    required = spec.get('required') is True
    if flags:
        head = '/'.join(flags)
        if spec['type'] == 'boolean' and not spec.get('nargs'):
            return head
        placeholder = label.upper()
        if spec.get('nargs') in ('*', '+', 'REMAINDER'):
            placeholder += '...'
        elif spec.get('nargs') == '?':
            placeholder = '[' + placeholder + ']'
        shown = f'{head} {placeholder}'
        return shown if required else f'[{shown}]'
    placeholder = label.upper()
    if spec.get('nargs') in ('*', '+', 'REMAINDER'):
        placeholder += '...'
    return placeholder if required else f'[{placeholder}]'


def _print_operation(descriptor, stdout) -> None:
    cli = descriptor.cli or {}
    operation = ' '.join(_command_path(cli['command'])) + ' ' + cli['operation']
    args = ' '.join(_arg_usage(spec) for spec in cli.get('args', ()))
    stdout.write(f'usage: ordessa {operation} {args} [--json] [--request-id ID]\n')
    stdout.write(f'       ordessa call {descriptor.id} --input <file|->\n')
    properties = (descriptor.input_schema or {}).get('properties') or {}
    required = set((descriptor.input_schema or {}).get('required') or ())
    if properties:
        stdout.write('input:\n')
        for name, schema in properties.items():
            marker = 'required' if name in required else 'optional'
            kind = schema.get('type', 'value')
            stdout.write(f'  {name} ({kind}, {marker})\n')


def render_help(argv: Sequence[str], descriptors, stdout) -> None:
    """Print help for a command path from the same metadata; no side effects."""
    tokens = [token for token in argv if not token.startswith('-')]
    index = _cli_index(descriptors)
    paths = {key[:-1] for key in index}
    if not tokens:
        stdout.write('usage: ordessa [--state DIR | --config FILE --service NAME] '
                     '[--json] [--request-id ID] [--timeout SECONDS] '
                     '[--save-result FILE] <command...> [options]\n\n')
        stdout.write('commands:\n')
        groups: dict[str, list[tuple[str, ...]]] = {}
        for path in paths:
            groups.setdefault(path[0], []).append(path)
        for top in sorted(groups):
            stdout.write(f'  {top}\n')
            for path in sorted(groups[top]):
                if len(path) > 1:
                    stdout.write(f'    {" ".join(path[1:])}\n')
        stdout.write('\ngeneric:\n  list | describe OPERATION | call OPERATION --input FILE\n')
        stdout.write('  session [--state DIR]\n')
        return
    target = tuple(tokens)
    exact = [key for key in index if key[:-1] == target]
    if exact:
        for key in sorted(exact):
            _print_operation(_descriptor_for(descriptors, index[key]), stdout)
        return
    children = [path for path in paths if path[:len(target)] == target and path != target]
    if children:
        stdout.write('usage: ordessa ' + ' '.join(target) + ' <operation> [options]\n\n')
        stdout.write('operations:\n')
        for path in sorted(children):
            for key in sorted(k for k in index if k[:-1] == path):
                stdout.write(f'  {index[key].split(".", 1)[-1]}\n')
        return
    raise ContractError('CAPABILITY_UNSUPPORTED', 'unknown command for help')


async def async_run(argv: Sequence[str], *, host=None,
                    authenticate: Callable[[str], Mapping[str, Any]] | None = None,
                    metadata=(), stdin=None, stdout=None, stderr=None) -> int:
    """Run one CLI invocation on the caller's current event loop.

    A caller-owned foreground host can await this repeatedly on one loop so
    tasks started by an earlier command stay alive across later commands. The
    synchronous :func:`run` wrapper calls exactly this path once.
    """
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    request_id = uuid.uuid4().hex
    save_target = None
    try:
        options = _parse_globals(argv)
        descriptors = _metadata_descriptors(metadata, host)
        if options.request_id:
            request_id = options.request_id
        if options.help:
            render_help(options.argv, descriptors, stdout)
            return 0
        if options.save_result is not None:
            save_target = _prepare_save_result(options.save_result)
        tokens, operands = _split(options.argv)
        command = ' '.join(tokens) if tokens else 'ordessa'
        if not tokens:
            raise ContractError('INVALID_INPUT', 'a command is required')
        if tokens[0] == 'list' and len(tokens) == 1:
            if host is not None:
                from ...system_access import queries
                result = _completed(queries.list_operations(host.registry))
            else:
                result = _completed({'operations': [_operation_view(d) for d in descriptors]})
            envelope = _envelope(command, request_id, result, host)
            _print(stdout, as_json=options.json, envelope=envelope, stderr=stderr)
            _maybe_save(save_target, envelope, stderr)
            return exit_code(envelope)
        if tokens[0] == 'describe' and len(tokens) == 2:
            if host is not None:
                from ...system_access import queries
                result = _completed(queries.describe(host.registry, tokens[1]))
            else:
                found = [d for d in descriptors if d.id == tokens[1]]
                if not found:
                    raise ContractError('CAPABILITY_UNSUPPORTED', 'unknown operation')
                result = _completed({'operation': _operation_view(found[0])})
            envelope = _envelope(command, request_id, result, host)
            _print(stdout, as_json=options.json, envelope=envelope, stderr=stderr)
            _maybe_save(save_target, envelope, stderr)
            return exit_code(envelope)
        if tokens[0] == 'call':
            if len(tokens) < 2:
                raise ContractError('INVALID_INPUT', 'call requires an operation id')
            if host is None:
                raise ContractError('AUTHORITY_UNAVAILABLE', 'this command needs a built host')
            operation_id = tokens[1]
            rest = _strip_timeout(tokens[2:], options)
            if '--input' in rest:
                index = rest.index('--input')
                try:
                    source = rest[index + 1]
                except IndexError:
                    raise ContractError('INVALID_INPUT', '--input needs a value') from None
                request = _read_json_file(source, stdin=stdin)
                if not isinstance(request, dict):
                    raise ContractError('INVALID_INPUT', 'input must be a JSON object')
            else:
                raise ContractError('INVALID_INPUT', 'call requires --input <file|->')
        else:
            if host is None:
                if _match(tokens, _cli_index(descriptors)) is None:
                    raise ContractError('CAPABILITY_UNSUPPORTED', 'unknown command')
                raise ContractError('AUTHORITY_UNAVAILABLE', 'this command needs a built host')
            index = _cli_index(_metadata_descriptors(None, host))
            match = _match(tokens, index)
            if match is None:
                raise ContractError('CAPABILITY_UNSUPPORTED', 'unknown command')
            _command, operation_id, rest = match
            descriptor = host.registry.descriptor(operation_id)
            if not _descriptor_takes_timeout(descriptor):
                rest = _strip_timeout(rest, options)
            request = _build_request(descriptor, rest, operands, stdin=stdin)
            request = _attach_stdin(request, descriptor, stdin)
        if authenticate is None:
            raise ContractError('AUTHORITY_UNAVAILABLE', 'this command needs an authenticated host')
        principal = authenticate(' '.join(tokens[:2]))
        context = RequestContext(principal=principal, request_id=request_id,
                                 deadline=_deadline(options.timeout))
        result = await host.call(operation_id, request, context)
        envelope = host.envelope(command=' '.join(tokens), request_id=request_id, result=result)
        descriptor = host.registry.descriptor(operation_id)
        override = None
        if (_process_render(descriptor) and result.status == 'completed'
                and isinstance(result.data, Mapping)):
            code = result.data.get('exitCode')
            if type(code) is int and type(code) is not bool:
                override = code
        if (not options.json and _process_render(descriptor)
                and result.status == 'completed'):
            out = result.data.get('stdout')
            err = result.data.get('stderr')
            if type(out) is str and out:
                stdout.write(out)
            if type(err) is str and err:
                stderr.write(err)
        else:
            _print(stdout, as_json=options.json, envelope=envelope, stderr=stderr,
                   descriptor=descriptor if result.data is not None else None, data=result.data,
                   request_id=None if options.json else request_id)
        _maybe_save(save_target, envelope, stderr)
        return override if override is not None else exit_code(envelope)
    except ContractError as error:
        envelope = _refused_envelope(' '.join(argv), request_id, error.code, error.message)
        _print(stdout, as_json='--json' in argv, envelope=envelope, stderr=stderr)
        _maybe_save(save_target, envelope, stderr)
        return exit_code(envelope)
    except OSError:
        envelope = _refused_envelope(' '.join(argv), request_id, 'INVALID_INPUT',
                                     'input file cannot be read')
        _print(stdout, as_json='--json' in argv, envelope=envelope, stderr=stderr)
        _maybe_save(save_target, envelope, stderr)
        return exit_code(envelope)


def _envelope(command, request_id, result, host):
    if host is not None:
        return host.envelope(command=command, request_id=request_id, result=result)
    from ordessa_interfaces_contracts import envelope_from_result
    return envelope_from_result(request_id=request_id, command=command, result=result)


def _deadline(timeout) -> float | None:
    seconds = DEFAULT_DEADLINE_SECONDS if timeout is None else timeout
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    return loop.time() + seconds


def _maybe_save(target, envelope, stderr) -> None:
    if target is None:
        return
    try:
        _save_envelope(target, envelope)
    except OSError as error:
        stderr.write(f'ordessa: result could not be saved to {target}: {error.strerror or error}\n')


def _operation_view(descriptor) -> dict:
    return {'id': descriptor.id, 'inputSchema': descriptor.input_schema,
            'outputSchema': descriptor.output_schema, 'scopes': list(descriptor.scopes),
            'cli': descriptor.cli, 'mcp': descriptor.mcp}


def run(argv: Sequence[str], *, host=None, authenticate=None, metadata=(),
        stdin=None, stdout=None, stderr=None) -> int:
    """One-shot synchronous wrapper over :func:`async_run` (same code path)."""
    return asyncio.run(async_run(argv, host=host, authenticate=authenticate, metadata=metadata,
                                 stdin=stdin, stdout=stdout, stderr=stderr))


def _completed(data: Mapping[str, Any]):
    from ordessa_interfaces_contracts import OperationResult
    return OperationResult(status='completed', data=data)


def main(argv: Sequence[str] | None = None) -> int:
    raise SystemExit('the generic channel requires an application-built host; see apps/cli')


__all__ = ['run', 'async_run', 'render_help', 'main']
