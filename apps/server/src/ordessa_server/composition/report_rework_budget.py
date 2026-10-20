"""One explicit report/review run's local, conservative HTTP spending authority.

The Pi provider adapter asks before every paid request. Reservations are durable,
atomic, never refunded (including ambiguous sends), and cover the full declared
model context/output at peak cache-miss prices. This owns no model credential,
Engineering Grant, Unit lifecycle or provider client.
"""
from datetime import datetime, timedelta, timezone
import fcntl
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
from threading import RLock, Thread
import time


CAP_NANODOLLARS = 1_000_000_000
RESERVATION_NANODOLLARS = 319_660_800
PRICE_BASIS = {
    'source': 'https://api-docs.deepseek.com/quick_start/pricing/',
    'verified_date_utc': '2026-10-18', 'provider': 'deepseek', 'model': 'deepseek-flash',
    'currency': 'USD', 'input_uncached_peak_per_million': '0.30',
    'input_cached_peak_per_million': '0.006',
    # Cache writes receive no separate entitlement: conservatively charge the
    # full input miss price as well. No discounted cache assumption funds sends.
    'cache_write_upper_per_million': '0.30', 'output_peak_per_million': '1.20',
    'max_input_tokens': 1_000_000, 'max_output_tokens': 16384,
}
_ROLES = frozenset({'report', 'review'})
_RESUME_CONTRACT = 'ordessa.report-rework-budget-resume/1'


def _utc(value):
    return value.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


class ReportReworkBudgetRefused(RuntimeError):
    pass


class ReportReworkBudget:
    """Trusted host instance shared serially by both original Unit processes."""

    def __init__(self, path, *, plan_digest, clock=None):
        if (type(plan_digest) is not str or len(plan_digest) != 64
                or any(c not in '0123456789abcdef' for c in plan_digest)):
            raise ReportReworkBudgetRefused('Invalid fixed report plan')
        self.path = Path(path)
        self._lock_path = self.path.with_name(self.path.name + '.owner.lock')
        if (not self.path.is_absolute() or self.path.resolve() != self.path
                or self.path.exists() or self.path.is_symlink()
                or self._lock_path.exists() or self._lock_path.is_symlink()):
            raise ReportReworkBudgetRefused('A fresh, canonical run ledger is required')
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()
        self._owner_lock_fd = self._acquire_owner_lock(create=True)
        self._token = secrets.token_urlsafe(32)
        self._server = self._thread = None
        self._configs = {}
        now = self._clock()
        if now.tzinfo is None:
            self._release_owner_lock(remove=True)
            raise ReportReworkBudgetRefused('UTC clock required')
        self._start_monotonic = time.monotonic()
        self._state = {'contract': 'ordessa.report-rework-budget/1',
            'plan_digest': plan_digest, 'not_before': _utc(now),
            'expires_at': _utc(now + timedelta(minutes=90)),
            'price_basis': dict(PRICE_BASIS),
            'cap_nanodollars': CAP_NANODOLLARS, 'reserved_nanodollars': 0,
            'phases': {}, 'reservations': [], 'usage': [], 'resume_fence': None}
        # Exclusive creation is the no-reset fence. A caller cannot reopen this
        # file with a fresh allowance or renew the time window.
        try:
            with self.path.open('x', encoding='utf-8') as stream:
                os.chmod(self.path, 0o600)
                json.dump(self._state, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            self._release_owner_lock(remove=True)
            raise
        self._resume_mode = False
        self._resume_deadline_monotonic = None

    def _acquire_owner_lock(self, *, create):
        """Serialize authority owners across processes; keep the inode as a fence."""
        flags = os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
        if create:
            flags |= os.O_CREAT | os.O_EXCL
        else:
            flags |= os.O_CREAT
        try:
            fd = os.open(self._lock_path, flags, 0o600)
            if os.fstat(fd).st_mode & 0o077:
                os.close(fd)
                raise ReportReworkBudgetRefused('Budget owner lock must be private')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except (FileExistsError, BlockingIOError, OSError) as error:
            if isinstance(error, ReportReworkBudgetRefused):
                raise
            raise ReportReworkBudgetRefused('Another budget authority owns this ledger') from None

    def _release_owner_lock(self, *, remove=False):
        fd = getattr(self, '_owner_lock_fd', None)
        if fd is None:
            return
        self._owner_lock_fd = None
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
        if remove:
            try:
                self._lock_path.unlink()
            except FileNotFoundError:
                pass

    @property
    def plan_digest(self):
        return self._state['plan_digest']

    @property
    def not_before(self):
        return self._state['not_before']

    @property
    def expires_at(self):
        return self._state['expires_at']

    @property
    def resumed_review_only(self):
        """True only for a durable one-shot restore, never for a fresh ledger."""
        return self._resume_mode is True

    @property
    def ledger_digest(self):
        """SHA-256 of the exact durable ledger bytes, for an explicit resume receipt."""
        try:
            raw = self.path.read_bytes()
        except OSError as error:
            raise ReportReworkBudgetRefused('Budget ledger unavailable') from error
        return sha256(raw).hexdigest()

    def require_current(self):
        now = _utc(self._clock())
        if (not self.not_before <= now < self.expires_at
                or (self._resume_deadline_monotonic is None
                    and time.monotonic() - self._start_monotonic >= 5400)
                or (self._resume_deadline_monotonic is not None
                    and time.monotonic() >= self._resume_deadline_monotonic)):
            raise ReportReworkBudgetRefused('Report-only run window expired')

    @classmethod
    def resume(cls, path, *, plan_digest, ledger_digest, clock=None):
        """Resume one exact unexpired ledger for a single, unready review phase.

        ``ledger_digest`` must be the SHA-256 receipt for the exact bytes being
        resumed. A durable one-time fence is written before this method returns;
        any subsequent restore attempt is refused, even if this process exits.
        """
        path = Path(path)
        lock_path = path.with_name(path.name + '.owner.lock')
        if (not path.is_absolute() or path.resolve() != path or path.is_symlink()
                or not path.is_file() or not lock_path.resolve(strict=False).parent == path.parent
                or type(plan_digest) is not str or len(plan_digest) != 64
                or any(c not in '0123456789abcdef' for c in plan_digest)
                or type(ledger_digest) is not str
                or len(ledger_digest) != 64
                or any(c not in '0123456789abcdef' for c in ledger_digest)):
            raise ReportReworkBudgetRefused('Exact canonical resume identity required')
        instance = cls.__new__(cls)
        instance.path = path
        instance._lock_path = lock_path
        instance._clock = clock or (lambda: datetime.now(timezone.utc))
        instance._lock = RLock()
        instance._owner_lock_fd = instance._acquire_owner_lock(create=False)
        try:
            raw = path.read_bytes()
            if sha256(raw).hexdigest() != ledger_digest:
                raise ReportReworkBudgetRefused('Budget ledger digest changed')
            try:
                state = json.loads(raw)
            except Exception:
                raise ReportReworkBudgetRefused('Budget ledger is invalid') from None
            if json.dumps(state, sort_keys=True).encode('utf-8') != raw:
                raise ReportReworkBudgetRefused('Budget ledger is not canonical')
            instance._validate_resume_state(state, plan_digest=plan_digest)
            now = instance._clock()
            if now.tzinfo is None:
                raise ReportReworkBudgetRefused('UTC clock required')
            not_before = datetime.fromisoformat(state['not_before'].replace('Z', '+00:00'))
            expires_at = datetime.fromisoformat(state['expires_at'].replace('Z', '+00:00'))
            if not not_before <= now < expires_at:
                raise ReportReworkBudgetRefused('Report-only run window expired')
            remaining = (expires_at - now.astimezone(timezone.utc)).total_seconds()
            if remaining <= 0 or remaining > 5400:
                raise ReportReworkBudgetRefused('Invalid original run window')
            if state.get('resume_fence') is not None:
                raise ReportReworkBudgetRefused('Budget ledger was already resumed')
            # An earlier schema-1 ledger may lack this field; normalize only by
            # adding the fence, leaving every original reservation/usage intact.
            state['resume_fence'] = {
                'contract': _RESUME_CONTRACT, 'source_ledger_sha256': ledger_digest,
                'plan_digest': plan_digest, 'resumed_at': _utc(now),
                'resumed_by_pid': os.getpid(), 'review_only': True,
            }
            instance._state = state
            instance._token = secrets.token_urlsafe(32)
            instance._server = instance._thread = None
            instance._configs = {}
            instance._resume_mode = True
            instance._start_monotonic = time.monotonic()
            instance._resume_deadline_monotonic = instance._start_monotonic + remaining
            instance._persist()
            return instance
        except Exception:
            instance._release_owner_lock()
            raise

    def _validate_resume_state(self, state, *, plan_digest):
        old_fields = {'contract', 'plan_digest', 'not_before', 'expires_at',
            'price_basis', 'cap_nanodollars', 'reserved_nanodollars', 'phases',
            'reservations', 'usage'}
        if (type(state) is not dict or set(state) not in (old_fields, old_fields | {'resume_fence'})
                or state.get('contract') != 'ordessa.report-rework-budget/1'
                or state.get('plan_digest') != plan_digest
                or state.get('price_basis') != PRICE_BASIS
                or state.get('cap_nanodollars') != CAP_NANODOLLARS
                or type(state.get('reserved_nanodollars')) is not int
                or type(state.get('phases')) is not dict
                or set(state['phases']) - _ROLES
                or type(state.get('reservations')) is not list
                or type(state.get('usage')) is not list):
            raise ReportReworkBudgetRefused('Budget ledger binding or schema differs')
        try:
            not_before = datetime.fromisoformat(state['not_before'].replace('Z', '+00:00'))
            expires_at = datetime.fromisoformat(state['expires_at'].replace('Z', '+00:00'))
        except (AttributeError, TypeError, ValueError):
            raise ReportReworkBudgetRefused('Budget ledger deadline is invalid') from None
        if (not_before.tzinfo is None or expires_at.tzinfo is None
                or expires_at - not_before != timedelta(minutes=90)):
            raise ReportReworkBudgetRefused('Budget ledger deadline changed')
        for role, phase in state['phases'].items():
            if (type(phase) is not dict or set(phase) != {'phase_id', 'ready'}
                    or type(phase['phase_id']) is not str or len(phase['phase_id']) != 32
                    or any(c not in '0123456789abcdef' for c in phase['phase_id'])):
                raise ReportReworkBudgetRefused('Budget phase ledger is invalid')
            ready = phase['ready']
            if ready is not None and (type(ready) is not dict
                    or set(ready) != {'contract', 'plan_digest', 'role', 'phase_id', 'pid',
                        'profile', 'provider', 'model', 'api', 'registered'}
                    or ready['contract'] != 'ordessa.pi.request-budget.ready/1'
                    or ready['plan_digest'] != plan_digest or ready['role'] != role
                    or ready['phase_id'] != phase['phase_id']
                    or ready['provider'] != 'deepseek' or ready['model'] != 'deepseek-flash'
                    or ready['api'] != 'openai-completions' or ready['registered'] is not True
                    or type(ready['pid']) is not int or ready['pid'] <= 0
                    or type(ready['profile']) is not str or not Path(ready['profile']).is_absolute()
                    or Path(ready['profile']).resolve() != Path(ready['profile'])):
                raise ReportReworkBudgetRefused('Budget readiness ledger is invalid')
        report_reservations = []
        review_reservations = []
        request_ids = set()
        reservation_ids = set()
        reserved = 0
        expected_reservation_fields = {'contract', 'plan_digest', 'role', 'phase_id', 'pid',
            'request_id', 'provider', 'model', 'request_bytes', 'max_input_tokens',
            'max_output_tokens', 'reserved_usd', 'reservation_id', 'reserved_nanodollars'}
        for row in state['reservations']:
            if (type(row) is not dict or set(row) != expected_reservation_fields
                    or row['contract'] != 'ordessa.pi.request-budget.reserve/1'
                    or row['plan_digest'] != plan_digest or row['role'] not in _ROLES
                    or row['role'] not in state['phases']
                    or row['phase_id'] != state['phases'][row['role']]['phase_id']
                    or row['provider'] != 'deepseek' or row['model'] != 'deepseek-flash'
                    or type(row['pid']) is not int or row['pid'] <= 0
                    or type(row['request_bytes']) is not int or not 0 < row['request_bytes'] <= 256000
                    or row['max_input_tokens'] != 1_000_000
                    or row['max_output_tokens'] != 16384
                    or row['reserved_usd'] != '0.3196608'
                    or row['reserved_nanodollars'] != RESERVATION_NANODOLLARS
                    or type(row['request_id']) is not str or len(row['request_id']) != 36
                    or type(row['reservation_id']) is not str or len(row['reservation_id']) != 32
                    or row['request_id'] in request_ids or row['reservation_id'] in reservation_ids):
                raise ReportReworkBudgetRefused('Budget reservation ledger is invalid')
            request_ids.add(row['request_id'])
            reservation_ids.add(row['reservation_id'])
            reserved += row['reserved_nanodollars']
            (report_reservations if row['role'] == 'report' else review_reservations).append(row)
        if reserved != state['reserved_nanodollars'] or reserved > CAP_NANODOLLARS:
            raise ReportReworkBudgetRefused('Budget reserved total differs from ledger')
        usage_ids = set()
        usage_fields = {'contract', 'plan_digest', 'role', 'phase_id', 'pid',
            'request_id', 'reservation_id', 'provider', 'model', 'input_tokens',
            'output_tokens', 'cache_read_tokens', 'cache_write_tokens', 'total_tokens'}
        for row in state['usage']:
            reservation = next((item for item in state['reservations']
                if item['request_id'] == row.get('request_id')
                and item['reservation_id'] == row.get('reservation_id')), None) if type(row) is dict else None
            counters = ('input_tokens', 'output_tokens', 'cache_read_tokens',
                        'cache_write_tokens', 'total_tokens')
            if (type(row) is not dict or set(row) != usage_fields or reservation is None
                    or row['contract'] != 'ordessa.pi.request-budget.usage/1'
                    or row['plan_digest'] != plan_digest or row['role'] != reservation['role']
                    or row['phase_id'] != reservation['phase_id'] or row['pid'] != reservation['pid']
                    or row['provider'] != 'deepseek' or row['model'] != 'deepseek-flash'
                    or any(type(row[name]) is not int or row[name] < 0 for name in counters)
                    or row['input_tokens'] + row['cache_read_tokens'] + row['cache_write_tokens'] > 1_000_000
                    or row['output_tokens'] > 16384
                    or row['total_tokens'] != sum(row[name] for name in counters[:-1])
                    or row['request_id'] in usage_ids):
                raise ReportReworkBudgetRefused('Budget usage ledger is invalid')
            usage_ids.add(row['request_id'])
        if (len(report_reservations) != 1
                or report_reservations[0]['reserved_nanodollars'] != RESERVATION_NANODOLLARS
                or review_reservations
                or state['phases'].get('report', {}).get('ready') is None
                or state['phases'].get('review', {}).get('ready') is not None
                or any(row['role'] == 'review' for row in state['usage'])
                or len(state['usage']) != 1
                or state['usage'][0]['role'] != 'report'
                or len(report_reservations) != 1
                or state['usage'][0]['request_id'] != report_reservations[0]['request_id']
                or (state.get('resume_fence') is not None)):
            raise ReportReworkBudgetRefused(
                'Only the exact confirmed report-once, review-unstarted ledger can resume')

    def _persist(self):
        temporary = self.path.with_name(self.path.name + '.next')
        with temporary.open('x', encoding='utf-8') as stream:
            os.chmod(temporary, 0o600)
            json.dump(self._state, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)
        fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def phase_config(self, role, *, pi_ai_module, module_sha256, extension_sha256):
        with self._lock:
            self.require_current()
            if self._resume_mode and role != 'review':
                raise ReportReworkBudgetRefused('A resumed budget is permanently review-only')
            if role not in _ROLES or self._server is None or role in self._configs:
                raise ReportReworkBudgetRefused('Exactly one fresh phase per role is permitted')
            existing = self._state['phases'].get(role)
            if existing is not None:
                if (not self._resume_mode or role != 'review'
                        or existing['ready'] is not None
                        or any(row['role'] == 'review' for row in self._state['reservations'])):
                    raise ReportReworkBudgetRefused('Exactly one fresh phase per role is permitted')
                phase_id = existing['phase_id']
            else:
                phase_id = secrets.token_hex(16)
                self._state['phases'][role] = {'phase_id': phase_id, 'ready': None}
                self._persist()
            config = {'endpoint': f'http://127.0.0.1:{self._server.server_port}',
                'token': self._token, 'plan_digest': self.plan_digest,
                'role': role, 'phase_id': phase_id, 'pi_ai_module': pi_ai_module,
                'module_sha256': module_sha256, 'extension_sha256': extension_sha256}
            self._configs[role] = config
            return dict(config)

    def configuration(self, role):
        with self._lock:
            self.require_current()
            if role not in self._configs:
                raise ReportReworkBudgetRefused('Budget phase is not configured')
            return dict(self._configs[role])

    def _phase(self, value):
        self.require_current()
        if (value.get('plan_digest') != self.plan_digest
                or value.get('provider') != 'deepseek'
                or value.get('model') != 'deepseek-flash'
                or type(value.get('pid')) is not int or value['pid'] <= 0):
            raise ReportReworkBudgetRefused('Fixed provider/run identity differs')
        phase = self._state['phases'].get(value.get('role'))
        if phase is None or phase['phase_id'] != value.get('phase_id'):
            raise ReportReworkBudgetRefused('Unknown original Unit phase')
        return phase

    def receive(self, route, value):
        with self._lock:
            if type(value) is not dict:
                raise ReportReworkBudgetRefused('Exact bounded request required')
            phase = self._phase(value)
            if self._resume_mode and value.get('role') != 'review':
                raise ReportReworkBudgetRefused('A resumed budget is permanently review-only')
            if route == '/ready':
                expected = {'contract', 'plan_digest', 'role', 'phase_id', 'pid',
                    'profile', 'provider', 'model', 'api', 'registered'}
                profile = value.get('profile')
                if (set(value) != expected
                        or value['contract'] != 'ordessa.pi.request-budget.ready/1'
                        or value['api'] != 'openai-completions' or value['registered'] is not True
                        or type(profile) is not str or not Path(profile).is_absolute()
                        or Path(profile).resolve() != Path(profile)
                        or not Path(profile).is_dir() or Path(profile).is_symlink()
                        or phase['ready'] is not None):
                    raise ReportReworkBudgetRefused('Budget extension readiness differs')
                phase['ready'] = dict(value)
                self._persist()
                return {'ready': True}
            ready = phase['ready']
            if ready is None or ready['pid'] != value['pid']:
                raise ReportReworkBudgetRefused('Actual Pi provider gate is not ready')
            if route == '/reserve':
                expected = {'contract', 'plan_digest', 'role', 'phase_id', 'pid',
                    'request_id', 'provider', 'model', 'request_bytes',
                    'max_input_tokens', 'max_output_tokens', 'reserved_usd'}
                if (set(value) != expected
                        or value['contract'] != 'ordessa.pi.request-budget.reserve/1'
                        or value['reserved_usd'] != '0.3196608'
                        or value['max_input_tokens'] != 1_000_000
                        or value['max_output_tokens'] != 16384
                        or type(value['request_bytes']) is not int
                        or not 0 < value['request_bytes'] <= 256000
                        or type(value['request_id']) is not str or len(value['request_id']) != 36
                        or any(r['request_id'] == value['request_id'] for r in self._state['reservations'])
                        or self._state['reserved_nanodollars'] + RESERVATION_NANODOLLARS > CAP_NANODOLLARS):
                    raise ReportReworkBudgetRefused('Request refused before spending')
                reservation = dict(value, reservation_id=secrets.token_hex(16),
                    reserved_nanodollars=RESERVATION_NANODOLLARS)
                self._state['reserved_nanodollars'] += RESERVATION_NANODOLLARS
                self._state['reservations'].append(reservation)
                self._persist()  # Must reach durable storage before send permission.
                return {'allowed': True, 'reservation_id': reservation['reservation_id']}
            if route == '/usage':
                counters = {'input_tokens', 'output_tokens', 'cache_read_tokens',
                            'cache_write_tokens', 'total_tokens'}
                expected = {'contract', 'plan_digest', 'role', 'phase_id', 'pid',
                    'request_id', 'reservation_id', 'provider', 'model'} | counters
                reservation = next((r for r in self._state['reservations']
                    if r['request_id'] == value.get('request_id')
                    and r['reservation_id'] == value.get('reservation_id')
                    and r['role'] == value['role'] and r['phase_id'] == value['phase_id']), None)
                if (set(value) != expected or reservation is None
                        or value['contract'] != 'ordessa.pi.request-budget.usage/1'
                        or any(type(value[k]) is not int or value[k] < 0 for k in counters)
                        or value['input_tokens'] + value['cache_read_tokens'] + value['cache_write_tokens'] > 1_000_000
                        or value['output_tokens'] > 16384
                        or value['total_tokens'] != sum(value[k] for k in counters - {'total_tokens'})
                        or any(x['request_id'] == value['request_id'] for x in self._state['usage'])):
                    raise ReportReworkBudgetRefused('Usage is incomplete or outside its reservation')
                self._state['usage'].append(dict(value))
                self._persist()  # Deliberately no refund from observed usage.
                return {'recorded': True}
            raise ReportReworkBudgetRefused('Unknown budget action')

    def require_unit_ready(self, owner, unit, role):
        # This is the actual original owner's private profile identity, not a
        # caller-provided path/PID. Fresh Unit ownership prevents reuse.
        profile = owner.records.owner_read_unit(unit.identity['unitId']).facts['privateRootFacts']['profile']
        with self._lock:
            self.require_current()
            if self._resume_mode and role != 'review':
                raise ReportReworkBudgetRefused('A resumed budget is permanently review-only')
            phase = self._state['phases'].get(role)
            if (phase is None or phase['ready'] is None
                    or phase['ready']['profile'] != profile):
                raise ReportReworkBudgetRefused('Original Unit has no confirmed budget provider')

    def snapshot(self):
        with self._lock:
            return json.loads(json.dumps(self._state))

    def start(self):
        authority = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                try:
                    if self.headers.get('X-Ordessa-Budget-Token') != authority._token:
                        raise ReportReworkBudgetRefused('Unknown budget caller')
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 8192:
                        raise ReportReworkBudgetRefused('Bounded budget message required')
                    result = authority.receive(self.path, json.loads(self.rfile.read(length)))
                    raw, status = json.dumps(result).encode(), 200
                except Exception:
                    raw, status = b'{"refused":true}', 403
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        with self._lock:
            if self._server is not None:
                raise ReportReworkBudgetRefused('Budget authority already started')
            self.require_current()
            self._server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            self._thread = Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
        return self

    def close(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=5)
            self._server = None
        self._release_owner_lock()
