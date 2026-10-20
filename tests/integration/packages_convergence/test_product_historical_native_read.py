"""Exact historical schema, opaque existing authority, read-only SQLite IO."""
import ast,sqlite3
from pathlib import Path
import pytest
from ordessa_server.composition.configuration import HistoricalNativeEvidenceReader,NativeEvidenceUnavailable


def test_exact_old_native_rows_unknown_state_read_only_and_authorization(tmp_path):
    source=Path('packages/execution/units/src/ordessa_units/records/operation_journal.py').read_text()
    tree=ast.parse(source)
    schema=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=='BASE_SCHEMA_SQL' for t in n.targets))
    path=tmp_path/'historical.sqlite'
    receipt=' {"opaque":"old native receipt bytes"} '
    result='{"status":"unknown","pending":["native readback"]}'
    with sqlite3.connect(path) as db:
        db.executescript(schema)
        db.execute('INSERT INTO plans VALUES (?,?,?,?)',('plan','original-principal','{}','fingerprint'))
        db.execute('INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            ('operation','original-principal','server','session','channel',1,'original-key','plan','fingerprint','unknown',result))
        db.execute('INSERT INTO native_evidence VALUES (?,?,?)',('operation','manifest',receipt))
    before=path.read_bytes();stamp=path.stat().st_mtime_ns
    invocation=object();allowed=[True];calls=[]
    target={'server_id':'server','session_id':'session','channel_id':'channel','runtime_generation':1}
    def authorize(actual,principal,ref,operation):
        calls.append((principal,ref,operation))
        return actual is invocation and allowed[0] and principal=='original-principal' and ref==target and operation=='operation'
    reader=HistoricalNativeEvidenceReader(path,authorize=authorize)
    actual=reader.read('original-principal',target,'operation',invocation=invocation)
    assert actual['historical'] is True and actual['operation']['state']=='unknown'
    assert actual['operation']['result_json']==result and actual['native']['receipt_json']==receipt
    assert actual['verification'] is None
    for principal,ref,op,caller in [('forged',target,'operation',invocation),
            ('original-principal',{**target,'runtime_generation':2},'operation',invocation),
            ('original-principal',target,'different',invocation),('original-principal',target,'operation',object())]:
        with pytest.raises(NativeEvidenceUnavailable,match='read refused'):reader.read(principal,ref,op,invocation=caller)
    allowed[0]=False
    with pytest.raises(NativeEvidenceUnavailable):reader.read('original-principal',target,'operation',invocation=invocation)
    assert len(calls)==6 and path.read_bytes()==before and path.stat().st_mtime_ns==stamp
    assert not hasattr(reader,'apply') and not hasattr(reader,'reconcile')
    assert not hasattr(reader,'journal')


def test_historical_missing_database_and_symlink_are_never_created_or_adopted(tmp_path):
    missing=tmp_path/'missing.sqlite';target={'server_id':'s','session_id':'s','channel_id':'c','runtime_generation':1}
    reader=HistoricalNativeEvidenceReader(missing,authorize=lambda *args:True)
    with pytest.raises(NativeEvidenceUnavailable):reader.read('principal',target,'op',invocation=object())
    assert not missing.exists()
    target_path=tmp_path/'target';target_path.write_bytes(b'sentinel');missing.symlink_to(target_path)
    with pytest.raises(NativeEvidenceUnavailable,match='symlink'):reader.read('principal',target,'op',invocation=object())
    assert target_path.read_bytes()==b'sentinel' and missing.is_symlink()
