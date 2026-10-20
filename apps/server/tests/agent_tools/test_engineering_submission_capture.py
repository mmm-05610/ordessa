"""Actual held Use/Manager/ACP/Process/files; captures are not normal Submission."""
import asyncio,sys
import pytest
from test_fresh_server_owner import root_owner,Provider
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_units.public import DirectoryBindingRef
from ordessa_units.bindings.publication import decode_node_ref
from ordessa_infrastructure.encoding import decode_json
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_server.composition.engineering_submission_sources import EngineeringSubmissionCapture,EngineeringSubmissionSource


@pytest.mark.parametrize('exit_code,refusal',[(0,None),(3,None),(0,'overflow'),(0,'symlink')])
def test_real_file_bytes_test_output_effect_and_original_execution_correlation(tmp_path,monkeypatch,exit_code,refusal):
    held={};acquire=Provider.acquire
    def remember(self,*args,**kwargs):
        use=acquire(self,*args,**kwargs);held['use']=use;return use
    monkeypatch.setattr(Provider,'acquire',remember)
    with root_owner(tmp_path/'owner','default') as j:
        env=j.env.environment_id
        profile=j.services.profiles.create(profile_id='capture-fixed',name='Capture',content={
            'schemaVersion':'1','harnessDefinitionRef':j.holder['definition'],'declarations':[]},request=RequestKey(env,'local','profile'))
        prep=j.services.assembly.prepare(RequestKey(env,'local','prepare'),profile.current_revision,{}, {})
        node=decode_node_ref(prep.intent.node_ref);ref=decode_json(safe_json(j.services.nodes.read(node)['binding']['harnessUnitRef']))
        unit=j.services.unit_manager.find(ref);lease=unit.lease_port.grant(ref)
        params={'sessionId':unit.projection.read_session(ref).native_facts['sessionId'],'prompt':[]}
        digest=unit.records.acp_prompt_input_digest(ref,params)
        original=unit.prompt(ref,lease,operation_ref='capture-original-acp',timeout=3,**params)
        assert original['state']=='completed'
        j.holder['current'].acquired=dict(prep.intent.node_ref);j.holder['current'].evidence=dict(ref)
        query=j.services.authorize_acp_turn_query(RequestKey(env,'local','source-read'),ref,'capture-original-acp',expected_prompt_input_digest=digest)
        directory=DirectoryBindingRef.from_dict(decode_json(safe_json(prep.intent.context_ref['directoryBindingRef'])))
        snapshot=j.services.snapshot_live_unit_selection(ref,expected_profile_revision=profile.current_revision,
            expected_directory_binding_ref=directory,query_invocation=query,query_input_digest=query.facts['inputDigest'])
        use=held['use'];use.files.write_text('cwd/input.txt','actual-before')
        lib=EngineeringLibrary.create((tmp_path/'engineering.sqlite').resolve(),library_id='capture-fixture',schema_version=14)
        try:
            blobs=SQLiteBlobStore(lib)
            command=(sys.executable,'-c',"import pathlib,sys;pathlib.Path('output.bin').write_bytes(b'actual-after\\x00');sys.stdout.buffer.write(b'complete-out\\x00');sys.stderr.write('complete-err');sys.exit("+str(exit_code)+")")
            capture=EngineeringSubmissionCapture(j.services.unit_manager,use,snapshot,blobs,authority_id=blobs.authority_id,
                argv=command,cwd='cwd',env={},allowed_paths=('cwd',),tool_version='controlled-python',timeout=3)
            if refusal=='overflow':
                import ordessa_server.composition.engineering_submission_sources as source
                monkeypatch.setattr(source,'_MAX_OUTPUT_BYTES',4)
                with pytest.raises(ApplicationError,match='SUBMISSION_CAPTURE_OUTPUT_BOUND_EXCEEDED'):
                    asyncio.run(capture.capture_test(ref,operation_ref='capture-original-acp',prompt_input_digest=digest,query_invocation=query))
            elif refusal=='symlink':
                from pathlib import Path
                outside=tmp_path/'outside.txt';outside.write_bytes(b'outside-must-not-be-read')
                Path(use.files.path('cwd/escape')).symlink_to(outside)
                with pytest.raises(ApplicationError,match='SUBMISSION_CAPTURE_SYMLINK_REFUSED'):
                    asyncio.run(capture.capture_test(ref,operation_ref='capture-original-acp',prompt_input_digest=digest,query_invocation=query))
            else:
                facts=asyncio.run(capture.capture_test(ref,operation_ref='capture-original-acp',prompt_input_digest=digest,query_invocation=query))
                assert facts.exit_code==exit_code and facts.execution_operation_ref=='capture-original-acp'
                assert blobs.read_verified(facts.stdout)==b'complete-out\x00' and blobs.read_verified(facts.stderr)==b'complete-err'
                changed=next(f for f in facts.files if f.path=='cwd/output.bin')
                assert changed.before is None and blobs.read_verified(changed.after)==b'actual-after\x00'
                assert facts.before_tree_digest!=facts.after_tree_digest
            with pytest.raises(ApplicationError,match='SUBMISSION_SOURCE_PROVENANCE_UNAVAILABLE'):
                EngineeringSubmissionSource().guard_submission(None,None,None)
            assert lib._connection.execute('SELECT count(*) FROM eng_submissions').fetchone()[0]==0
        finally:lib.close()
        j.services.lifecycle.stop(RequestKey(env,'local','stop'),node,{})
        j.services.lifecycle.release(RequestKey(env,'local','release'),node,{})
        assert j.local.instance.snapshot.active_uses==0
