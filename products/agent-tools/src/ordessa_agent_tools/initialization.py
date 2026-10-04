"""Caller-local executable observations; never starts or configures a Harness."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from importlib import resources
import json
import os
from pathlib import Path
import re
import stat

from .client import ClientError, MAX_BYTES, parse_json

NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')


def catalog():
    try:
        raw = resources.files('ordessa_agent_tools').joinpath('harness_commands.json').read_bytes()
        if len(raw) > MAX_BYTES:
            raise ValueError()
        document = parse_json(raw)
        if set(document) != {'catalog', 'catalogDigest'}:
            raise ValueError()
        value = document['catalog']
        encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        if document['catalogDigest'] != 'sha256:' + hashlib.sha256(encoded).hexdigest():
            raise ValueError()
        if set(value) != {'catalogVersion', 'candidates'} or value['catalogVersion'] != 'harness-command-discovery/1':
            raise ValueError()
        if not isinstance(value['candidates'], list) or not 0 < len(value['candidates']) <= 64:
            raise ValueError()
        families = set()
        for candidate in value['candidates']:
            if not isinstance(candidate, dict) or set(candidate) != {'familyId', 'commands'}:
                raise ValueError()
            family, commands = candidate['familyId'], candidate['commands']
            if not isinstance(family, str) or not NAME.fullmatch(family) or family in families:
                raise ValueError()
            families.add(family)
            if (not isinstance(commands, list) or not 0 < len(commands) <= 8
                    or any(not isinstance(name, str) or not NAME.fullmatch(name) for name in commands)
                    or len(set(commands)) != len(commands)):
                raise ValueError()
        return document
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise ClientError('HARNESS_CATALOG_UNAVAILABLE', 'Published Harness command catalog is unavailable or invalid', 4) from None


def discover(path=None):
    document = catalog()
    search = os.environ.get('PATH', '') if path is None else path
    if not isinstance(search, str) or len(search) > 32768 or '\x00' in search:
        raise ClientError('PARAMETER_INVALID', 'Search path must be bounded and valid', 2)
    entries = search.split(os.pathsep)
    if len(entries) > 256:
        raise ClientError('PARAMETER_INVALID', 'Search path contains too many entries', 2)
    directories, ignored = [], 0
    for entry in entries:
        if not entry or not os.path.isabs(entry):
            ignored += 1
            continue
        if entry not in directories:
            directories.append(entry)
    extensions = ['']
    if os.name == 'nt':
        raw_extensions = os.environ.get('PATHEXT', '.COM;.EXE;.BAT;.CMD')
        if len(raw_extensions) > 2048 or len(raw_extensions.split(';')) > 32:
            raise ClientError('PARAMETER_INVALID', 'Executable extension list exceeds the scan limit', 2)
        for extension in raw_extensions.split(';'):
            if re.fullmatch(r'\.[A-Za-z0-9]{1,8}', extension) and extension.lower() not in [x.lower() for x in extensions]:
                extensions.append(extension)
    harnesses = []
    for candidate in document['catalog']['candidates']:
        observations = []
        for command in candidate['commands']:
            matches, issues, observed = [], [], set()
            for directory in directories:
                for extension in extensions:
                    name = command if extension and command.lower().endswith(extension.lower()) else command + extension
                    location = Path(directory) / name
                    if str(location) in observed:
                        continue
                    observed.add(str(location))
                    try:
                        facts = location.stat()
                        if not stat.S_ISREG(facts.st_mode):
                            issues.append({'path': str(location), 'reason': 'invalidFile'})
                        elif not os.access(location, os.X_OK):
                            issues.append({'path': str(location), 'reason': 'notExecutable'})
                        else:
                            matches.append({'path': str(location), 'resolvedPath': str(location.resolve(strict=True)),
                                            'isSymlink': location.is_symlink()})
                    except FileNotFoundError:
                        try:
                            if location.is_symlink():
                                issues.append({'path': str(location), 'reason': 'invalidFile'})
                        except (OSError, RuntimeError):
                            issues.append({'path': str(location), 'reason': 'scanUnavailable'})
                    except (OSError, RuntimeError):
                        issues.append({'path': str(location), 'reason': 'scanUnavailable'})
            unavailable = any(item['reason'] == 'scanUnavailable' for item in issues)
            observations.append({'command': command, 'status': 'executableFound' if matches else ('scanUnavailable' if unavailable else 'notFound'),
                                 'matches': matches, 'issues': issues})
        harnesses.append({'familyId': candidate['familyId'],
                          'status': 'executableFound' if any(x['matches'] for x in observations) else ('scanUnavailable' if any(x['status'] == 'scanUnavailable' for x in observations) else 'notFound'),
                          'commands': observations, 'installedArtifact': 'notChecked',
                          'providerAdmission': 'notChecked', 'runtimeReady': 'unknown'})
    data = {'scanScope': 'clientMachine', 'source': 'PATH', 'observedAt': datetime.now(timezone.utc).isoformat(),
            'catalogVersion': document['catalog']['catalogVersion'], 'catalogDigest': document['catalogDigest'],
            'ignoredRelativeOrEmptyPathEntries': ignored, 'harnesses': harnesses,
            'scanCompleteForSearchedEntries': not any(issue['reason'] == 'scanUnavailable' for item in harnesses for command in item['commands'] for issue in command['issues']),
            'foundFamilies': [item['familyId'] for item in harnesses if item['status'] == 'executableFound'],
            'nextStep': 'Connect to the selected service with doctor; server-host installation and trusted provider admission require separate verification'}
    if len(json.dumps(data, ensure_ascii=False).encode('utf-8')) > MAX_BYTES:
        raise ClientError('LOCAL_DISCOVERY_TOO_LARGE', 'Local discovery exceeds the output limit', 4)
    return data


def save_report(path, envelope):
    """Explicit project-local observation snapshot, never configuration truth."""
    encoded = (json.dumps(envelope, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    descriptor = None
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            descriptor = None
            stream.write(encoded)
    except OSError:
        raise ClientError('INIT_REPORT_REFUSED', 'Report destination must be a new writable file', 2) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
