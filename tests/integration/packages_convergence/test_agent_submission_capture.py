"""Original Agent -> BlobStore -> v2 Submission -> original SQLite repository.

The repository access is the original lower storage access, not full business
UoW/admission (yaml remains missing). No synthetic turn/session/provenance.
"""
import asyncio,hashlib,runpy
from dataclasses import replace
from pathlib import Path
from contextlib import contextmanager
import pytest
from test_agent_guarded_bootstrap import setup,PEER
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_agents.sdk.interactions import InteractionService,InteractionsRefused
from ordessa_engineering.adapters.native_records.agent_execution import AgentExecutionConsumer
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import _RepositoryAccess
from ordessa_engineering.adapters.persistence.sqlite.submission_repository import SQLiteSubmissionRepository
from ordessa_engineering.domain.changes.agent_execution_ref import AgentExecutionRecordRef
from ordessa_engineering.domain.changes.submission_codec import encode_submission,decode_submission
from ordessa_engineering.domain.changes.submission import require_online_execution
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.changes.execution_capture import capture_agent_observation


def test_original_cold_capture_agent_submission_storage_and_refusal_boundaries(tmp_path):
    async def scenario():
        text='{"result":"observed"}'
        case=await setup(tmp_path,PEER.replace("'original-bootstrap-peer'",repr(text)))
        try:
            started=await case.manager.start(case.request,case.endpoint,case.fixture.invocation)
            assert started.state=='running'
            source=InteractionService(case.records,case.authority,case.fixture.resolver)
            library=EngineeringLibrary.create((tmp_path/'engineering.sqlite').resolve(),library_id='submission-source',schema_version=13)
            blobs=SQLiteBlobStore(library);consumer=AgentExecutionConsumer(source,blobs)
            raw=canonical_bytes({'sessionId':started.session_id,'prompt':[]})
            with consumer.prepared_dispatch(started.instance_ref.projection(),raw,request_id='report',
                    engineering_attempt_ref='attempt',send_invocation=case.fixture.invocation,
                    read_invocation=case.fixture.invocation) as prepared:
                class Cut:
                    calls=0
                    @contextmanager
                    def guard_write(self,binding,invocation):
                        assert invocation is case.fixture.invocation
                        assert binding.agent_operation_ref==prepared.agent_operation_ref
                        self.calls+=1;yield
                cut=Cut()
                receipt=await case.manager.send_prompt('report',started.instance_ref,case.fixture.invocation,
                    prompt=source.freeze_prompt(started.instance_ref,raw),interaction_service=source,
                    engineering_attempt_ref='attempt',write_guard=cut,deadline=asyncio.get_running_loop().time()+2)
                captured=consumer.capture(prepared,read_invocation=case.fixture.invocation)
            assert receipt.state=='completed' and cut.calls==1
            ref=AgentExecutionRecordRef(prepared.agent_ref_bytes,prepared.turn_ref_bytes,case.prepared.source_revision,
                prepared.agent_operation_ref,'attempt',Digest('sha256',prepared.prompt_input_digest[7:]),prepared.query_digest,captured.blob_ref)
            # Read permission survives independently of revoked send rights.
            case.authority.send=False
            # Reviewer identity is read independently from the ORIGINAL Agent
            # binding authority; source facts do not carry assigned roles.
            assert consumer.read_agent_reference(started.instance_ref.projection(),
                read_invocation=case.fixture.invocation)==ref.agent_ref_bytes
            with pytest.raises(InteractionsRefused):
                consumer.read_agent_reference(started.instance_ref.projection(),read_invocation=object())
            assert consumer.prompt_input_digest(ref,{'sessionId':started.session_id,'prompt':[]})=='sha256:'+ref.prompt_input_digest.hex
            with pytest.raises(ApplicationError,match='AGENT_PROMPT_DIGEST_MISMATCH'):
                consumer.prompt_input_digest(ref,{'sessionId':started.session_id,'prompt':[{'type':'text','text':'changed'}]})
            def capture(value=ref):
                return capture_agent_observation(consumer,blobs,authority_id=library.library_id,
                    execution_ref=value,query_invocation=case.fixture.invocation)
            observed=capture()
            assert observed.state=='completed' and observed.report_text==text
            assert observed.blob_ref==captured.blob_ref and blobs.read_verified(observed.blob_ref)==canonical_bytes(receipt.projection())
            old=runpy.run_path(str(Path(__file__).parents[3]/'packages/engineering/tests/domain/test_submission.py'))['record']()
            submission=replace(old,execution_ref=ref,test_evidence=())
            encoded=encode_submission(submission)
            assert decode_submission(encoded)==submission and require_online_execution(submission)==ref
            # Actual original library connection/access/repository, no second DB.
            with library.transaction() as connection:
                access=_RepositoryAccess(connection,submission.scope,'write',library.library_id)
                repo=SQLiteSubmissionRepository(access)
                assert repo.create(submission)==submission.ref
                assert repo.resolve(submission.ref)==submission
                with pytest.raises(ReferenceError,match='AGENT_EXECUTION_RECORD_REQUIRED'):repo.create(old)
            assert library._connection.execute('SELECT canonical_bytes FROM eng_submissions').fetchone()[0]==encoded
            for changed,code in ((replace(ref,operation_ref='foreign'),'AGENT_RECEIPT_BINDING_MISMATCH'),
                    (replace(ref,engineering_attempt_ref='foreign'),'AGENT_RECEIPT_BINDING_MISMATCH'),
                    (replace(ref,source_revision='foreign'),'AGENT_ORIGINAL_PROVENANCE_UNAVAILABLE')):
                with pytest.raises(ApplicationError,match=code):capture(changed)
            case.authority.read=False
            with pytest.raises(InteractionsRefused,match='READ_NOT_AUTHORIZED'):
                consumer.read_agent_reference(started.instance_ref.projection(),read_invocation=case.fixture.invocation)
            with pytest.raises(InteractionsRefused,match='READ_NOT_AUTHORIZED'):capture()
            assert cut.calls==1 and case.records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0]==1
            assert library._connection.execute('SELECT count(*) FROM eng_action_consumptions').fetchone()[0]==0
            assert library._connection.execute('SELECT count(*) FROM step_log').fetchone()[0]==0
            assert case.fixture.retained_use_count==1
        finally:case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())
