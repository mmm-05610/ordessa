from datetime import datetime, timedelta
import re
from ordessa_infrastructure.identifiers import now, opaque_id


def test_timestamp_is_current_timezone_aware_utc_isoformat():
    before = datetime.now().astimezone()
    stamp = now()
    after = datetime.now().astimezone()
    parsed = datetime.fromisoformat(stamp)
    assert parsed.utcoffset() == timedelta(0)
    assert before <= parsed <= after


def test_uuid_hex_is_opaque_unique_and_preserves_owner_prefix():
    ids = [opaque_id('owner/custom') for _ in range(100)]
    assert len(set(ids)) == 100
    assert all(re.fullmatch(r'owner/custom_[0-9a-f]{32}', value) for value in ids)
    assert opaque_id('').startswith('_')  # prefix policy belongs to the owner
