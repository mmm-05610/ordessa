"""Persistent probe evidence and cleanup through original owner ports only."""
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import traceback


def failure_boundary(error):
    return {'error_type':type(error).__name__, 'frames':[
        {'file':frame.filename, 'line':frame.lineno, 'function':frame.name}
        for frame in traceback.extract_tb(error.__traceback__)]}


@contextmanager
def retained_attempt_root(output, *, prefix='ordessa-v1-live-pi-'):
    """Reserve an audit locator before work; never delete files on any exit."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    locator = output.with_suffix('.root.json')
    with locator.open('x') as stream:
        root = Path(tempfile.mkdtemp(prefix=prefix))
        stream.write(json.dumps({'root':str(root),
            'journal':str(root/'original.sqlite'),
            'environment_store':str(root/'environment.sqlite'),
            'retained_for_original_reconciliation':True,
            'cleanup_requires_separate_authorization':True})+'\n')
    yield root


def cleanup_attempt(unit, authority, *, prepared=None, released=None, binding=None):
    """Separate Unit confirmation from native/Use cleanup; never claim a replay."""
    cleanup = {}
    errors = {}
    owner_released = released is not None and released.get('state') == 'confirmed'
    if prepared is not None and not owner_released:
        try:
            cleanup['stop'] = unit.stop(prepared['unitRef'], authority.issue('stop'))['state']
            cleanup['release'] = unit.release(prepared['unitRef'], authority.issue('release'))['state']
            owner_released = cleanup['release'] == 'confirmed'
        except Exception as error:
            errors['unit_owner'] = failure_boundary(error)
    factory = unit.channel_factory
    record = factory.owned_record
    if record is not None and not owner_released:
        try:
            if record.process.observe().state != 'exited':
                factory.close(record.entry)
            cleanup['native_release'] = factory.release(record.entry)
        except Exception as error:
            errors['native_owner'] = failure_boundary(error)
    use_released = False
    try:
        factory.release_environment()
        use_released = True
    except Exception as error:
        errors['use_owner'] = failure_boundary(error)
    finally:
        if binding is not None:
            try:
                binding.close()
            except Exception as error:
                errors['product_binding'] = failure_boundary(error)
    return {'owner_cleanup':cleanup, 'errors':errors,
        'owner_release_confirmed':owner_released,
        'use_release_confirmed':use_released,
        'cleanup_completed':owner_released and use_released and not errors}
